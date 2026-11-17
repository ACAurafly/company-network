"""Optional local or delegated PyYAML loading for template composition."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

_NON_NATIVE_MARKER_KEY = "$speckit_non_native"

class TemplateResolutionError(RuntimeError):
    """Raised when template layers exist but cannot be composed safely."""



class _DelegatedYAMLError(Exception):
    """Raised when a SPECKIT_PYTHON_EXECUTABLE-delegated manifest parse fails."""



class _NonNativeYAMLValue:
    """Marker for a YAML value with no native JSON equivalent (e.g. a date).

    Preserves the fact that native ``yaml.safe_load`` would not have produced
    a string/int/etc. here, so callers validating field types (e.g. that
    ``file`` is a string) reject it the same way the in-process parser would,
    instead of silently accepting a stringified value.
    """

    def __repr__(self) -> str:
        return "<non-native YAML value>"



def _delegated_yaml_object_hook(obj: dict) -> object:
    if len(obj) == 1 and obj.get(_NON_NATIVE_MARKER_KEY) is True:
        return _NonNativeYAMLValue()
    return obj



class _DelegatedYAML:
    """``yaml.safe_load`` proxy that shells out to SPECKIT_PYTHON_EXECUTABLE.

    Used when this interpreter lacks PyYAML but SPECKIT_PYTHON_EXECUTABLE
    (or the deprecated SPECKIT_PYTHON alias) names one that has it (e.g. a
    `uv tool install` / `pipx` venv invisible to the bare `python3` a script
    is launched with). See #4443.

    Only ``_preset_template_layer`` calls this, and only the ``type``,
    ``name``, ``file``, and ``strategy`` fields of each ``provides.templates``
    entry are ever inspected, so the child drops every other top-level
    manifest field (e.g. free-form ``metadata``) and every other per-entry
    field (e.g. ``description``) before serializing: a valid, ignored YAML
    alias DAG in either place is otherwise unrepresentable in JSON without
    exponential blow-up on the round trip.
    """

    YAMLError = _DelegatedYAMLError

    def __init__(self, python_exe: str) -> None:
        self._python_exe = python_exe

    def safe_load(self, text: str) -> object:
        child_env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            proc = subprocess.run(
                [
                    self._python_exe,
                    "-c",
                    "import sys, json, yaml\n"
                    "def _default(value):\n"
                    f"    return {{'{_NON_NATIVE_MARKER_KEY}': True}}\n"
                    "def _stringify_keys(obj, stack=None):\n"
                    "    if stack is None:\n"
                    "        stack = set()\n"
                    "    if isinstance(obj, (dict, list, tuple)):\n"
                    "        if id(obj) in stack:\n"
                    f"            return {{'{_NON_NATIVE_MARKER_KEY}': True}}\n"
                    "        stack.add(id(obj))\n"
                    "        try:\n"
                    "            if isinstance(obj, dict):\n"
                    "                return {\n"
                    "                    (k if isinstance(k, (str, int, float, bool)) or k is None else str(k)): _stringify_keys(v, stack)\n"
                    "                    for k, v in obj.items()\n"
                    "                }\n"
                    "            return [_stringify_keys(v, stack) for v in obj]\n"
                    "        finally:\n"
                    "            stack.discard(id(obj))\n"
                    "    return obj\n"
                    "def _only_entry_fields(entry):\n"
                    "    if not isinstance(entry, dict):\n"
                    "        return _default(entry)\n"
                    "    fields = {}\n"
                    "    for k in ('type', 'name', 'file', 'strategy'):\n"
                    "        if k not in entry:\n"
                    "            continue\n"
                    "        v = entry[k]\n"
                    "        fields[k] = v if isinstance(v, str) else _default(v)\n"
                    "    return fields\n"
                    "def _only_templates(data):\n"
                    "    if not isinstance(data, dict):\n"
                    "        return _default(data)\n"
                    "    if 'provides' not in data:\n"
                    "        return {}\n"
                    "    provides = data['provides']\n"
                    "    if not isinstance(provides, dict):\n"
                    "        return {'provides': _default(provides)}\n"
                    "    if 'templates' not in provides:\n"
                    "        return {'provides': {}}\n"
                    "    templates = provides['templates']\n"
                    "    if not isinstance(templates, list):\n"
                    "        return {'provides': {'templates': _default(templates)}}\n"
                    "    return {\n"
                    "        'provides': {\n"
                    "            'templates': [_only_entry_fields(e) for e in templates]\n"
                    "        }\n"
                    "    }\n"
                    "try:\n"
                    "    data = yaml.safe_load(sys.stdin.read())\n"
                    "except yaml.YAMLError as exc:\n"
                    "    print(str(exc), file=sys.stderr)\n"
                    "    sys.exit(1)\n"
                    "json.dump(_stringify_keys(_only_templates(data)), sys.stdout, default=_default)",
                ],
                input=text,
                capture_output=True,
                encoding="utf-8",
                env=child_env,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _DelegatedYAMLError(
                f"SPECKIT_PYTHON_EXECUTABLE could not parse the manifest: {exc}"
            ) from exc
        if proc.returncode != 0:
            raise _DelegatedYAMLError(
                proc.stderr.strip()
                or "SPECKIT_PYTHON_EXECUTABLE could not parse the manifest"
            )
        try:
            return json.loads(proc.stdout, object_hook=_delegated_yaml_object_hook)
        except json.JSONDecodeError as exc:
            raise _DelegatedYAMLError(
                f"SPECKIT_PYTHON_EXECUTABLE returned invalid JSON: {exc}"
            ) from exc



def _import_yaml() -> object | None:
    """Import PyYAML, delegating to SPECKIT_PYTHON_EXECUTABLE (or the
    deprecated SPECKIT_PYTHON alias) if this interpreter lacks it."""
    try:
        import yaml

        return yaml
    except ImportError:
        pass

    python_override = os.environ.get("SPECKIT_PYTHON_EXECUTABLE") or os.environ.get(
        "SPECKIT_PYTHON"
    )
    if not python_override:
        return None
    try:
        probe = subprocess.run(
            [
                python_override,
                "-c",
                "import sys, yaml\nraise SystemExit(sys.version_info.major != 3)",
            ],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if probe.returncode != 0:
        return None
    return _DelegatedYAML(python_override)
