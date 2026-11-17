"""Agent command separator discovery and formatting."""
from pathlib import Path
import json
import os

def get_invoke_separator(repo_root: Path) -> str:
    integration_json = repo_root / ".specify" / "integration.json"
    if not integration_json.is_file():
        return "."
    # Split the parse out of the lookup and guard the top-level shape, matching
    # read_feature_json_feature_directory above and the bash/PowerShell twins,
    # which both fall back to "." for any unusable integration.json:
    #   * a non-mapping top level ([], "forge", 42, null) is valid JSON, so
    #     json.JSONDecodeError never fires and state.get(...) raised
    #     AttributeError;
    #   * a non-UTF-8 file raises UnicodeDecodeError, which is a ValueError --
    #     not an OSError -- so it escaped the except tuple. Realistic on
    #     Windows, where PowerShell 5.1's Out-File/`>` default to UTF-16.
    try:
        state = json.loads(integration_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "."
    if not isinstance(state, dict):
        return "."
    key = state.get("default_integration") or state.get("integration") or ""
    settings = state.get("integration_settings")
    if isinstance(key, str) and isinstance(settings, dict):
        entry = settings.get(key)
        if isinstance(entry, dict) and entry.get("invoke_separator") in {".", "-"}:
            return entry["invoke_separator"]
    return "."


def format_speckit_command(command_name: str, repo_root: Path) -> str:
    separator = get_invoke_separator(repo_root)
    name = command_name.lstrip("/")
    if name.startswith("speckit."):
        name = name[len("speckit.") :]
    elif name.startswith("speckit-"):
        name = name[len("speckit-") :]
    name = name.replace(".", separator)
    return f"$speckit{separator}{name}"
