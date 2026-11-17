"""Company SDD scaffolding and deterministic checks; no AI or network required."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ARTIFACTS = ("spec", "plan", "tasks", "verification")


def selected_spec(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError("Spec must be a repository-relative path under specs/.")
    if len(relative.parts) != 2 or relative.parts[0] != "specs" or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", relative.parts[1]):
        raise ValueError("Spec: must select one directory such as specs/007-example.")
    target = (root / relative).resolve()
    if not target.is_relative_to((root / "specs").resolve()) or target == (root / "specs").resolve():
        raise ValueError("Spec resolves outside specs/.")
    # Reject a symlinked specs directory as well as symlinked feature folders.
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Spec resolves outside the repository.")
    return target


def metadata(text: str) -> dict:
    import yaml
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        raise ValueError("spec.md needs YAML metadata (id, issue, owner, status, paths).")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid spec metadata YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("spec.md metadata must be a mapping.")
    return data


def check_spec(root: Path, directory: Path, complete: bool, linked: bool) -> list[str]:
    errors = []
    docs = {}
    for name in ARTIFACTS:
        file = directory / f"{name}.md"
        if not file.is_file() or not file.resolve().is_relative_to(directory):
            errors.append(f"{directory.name}: missing or unsafe {name}.md")
        else:
            docs[name] = file.read_text(encoding="utf-8")
            if not docs[name].strip():
                errors.append(f"{directory.name}: empty {name}.md")
    if len(docs) != len(ARTIFACTS):
        return errors
    try:
        data = metadata(docs["spec"])
    except ValueError as exc:
        return errors + [f"{directory.name}: {exc}"]
    if data.get("id") != directory.name:
        errors.append(f"{directory.name}: metadata id does not match directory")
    if not isinstance(data.get("owner"), str) or not data["owner"].strip():
        errors.append(f"{directory.name}: owner is required")
    if linked and (type(data.get("issue")) is not int or data["issue"] < 1):
        errors.append(f"{directory.name}: issue must be a positive GitHub Issue number")
    if data.get("status") not in {"draft", "specified", "planned", "implementing", "verified", "completed"}:
        errors.append(f"{directory.name}: status must be draft/specified/planned/implementing/verified/completed")
    paths = data.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p and not p.startswith("/") and ".." not in Path(p).parts for p in paths):
        errors.append(f"{directory.name}: paths must list affected repository files/globs")
    requirements = set(re.findall(r"\*\*(FR-\d{3})\*\*", docs["spec"]))
    if not requirements:
        errors.append(f"{directory.name}: define at least one FR-001 requirement")
    tasks = re.findall(r"^\s*- \[([ xX])\] (T\d{3})\b(.*)$", docs["tasks"], re.M)
    if not tasks:
        errors.append(f"{directory.name}: tasks.md needs numbered checkbox tasks")
    ids = [task[1] for task in tasks]
    if len(ids) != len(set(ids)):
        errors.append(f"{directory.name}: task IDs must be unique")
    task_requirements = set(re.findall(r"FR-\d{3}", "\n".join(task[2] for task in tasks)))
    evidence = {}
    for line in docs["verification"].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"FR-\d{3}", cells[0]):
            if cells[0] in evidence:
                errors.append(f"{directory.name}: duplicate evidence row for {cells[0]}")
            evidence[cells[0]] = (cells[1], cells[2].lower())
    for requirement in sorted(requirements):
        if requirement not in task_requirements:
            errors.append(f"{directory.name}: {requirement} has no implementation task")
        if requirement not in evidence or not evidence[requirement][0]:
            errors.append(f"{directory.name}: {requirement} has no verification evidence")
        elif complete and evidence[requirement][1] not in {"passed", "verified", "not-applicable"}:
            errors.append(f"{directory.name}: {requirement} verification is {evidence[requirement][1]}")
    if complete:
        for mark, task_id, _ in tasks:
            if mark.lower() != "x":
                errors.append(f"{directory.name}: {task_id} is incomplete")
        for name, content in docs.items():
            if re.search(r"\[NEEDS CLARIFICATION[^\]]*\]|\{\{[A-Z_]+\}\}|\bTODO\b", content):
                errors.append(f"{directory.name}: unresolved placeholder in {name}.md")
    return errors


def changed_files(root: Path, base: str) -> list[str]:
    resolved = subprocess.run(["git", "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"], cwd=root, text=True, capture_output=True)
    if resolved.returncode:
        raise ValueError("base must resolve to an existing Git commit")
    result = subprocess.run(["git", "diff", "--name-only", "-z", resolved.stdout.strip(), "HEAD"], cwd=root, text=True, capture_output=True, check=True)
    return [path for path in result.stdout.split("\0") if path]


def check(root: Path, args) -> None:
    body = None
    draft = args.draft
    if args.event:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
        pr = event.get("pull_request")
        if not isinstance(pr, dict):
            raise ValueError("event must contain a pull_request")
        body = pr.get("body") or ""
        draft = pr.get("draft") is True
    elif args.pr_body:
        body = Path(args.pr_body).read_text(encoding="utf-8")
    if body is not None:
        matches = re.findall(r"^Spec:\s*(specs/[a-z0-9][a-z0-9-]*)\s*$", body, re.M)
        if len(matches) != 1:
            raise ValueError("PR body needs exactly one line: Spec: specs/007-example")
        value = matches[0]
        if args.spec and args.spec != value:
            raise ValueError("Spec: disagrees with --spec")
        directories = [selected_spec(root, value)]
    elif args.spec:
        directories = [selected_spec(root, args.spec)]
    else:
        directories = [selected_spec(root, str(p.relative_to(root))) for p in sorted((root / "specs").glob("*/spec.md")) for p in [p.parent]]
    if not directories:
        raise ValueError("No feature specifications found under specs/.")
    errors = []
    for directory in directories:
        errors.extend(check_spec(root, directory, args.require_complete or (body is not None and not draft), body is not None))
    if args.base and len(directories) != 1:
        errors.append("--base requires exactly one selected spec")
    elif args.base and not errors:
        data = metadata((directories[0] / "spec.md").read_text(encoding="utf-8"))
        paths = data.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p and not p.startswith("/") and ".." not in Path(p).parts for p in paths):
            errors.append("spec metadata paths must list affected repository paths/globs")
        else:
            spec_prefix = directories[0].relative_to(root).as_posix() + "/"
            for file in changed_files(root, args.base):
                if not file.startswith(spec_prefix) and not any(fnmatch.fnmatchcase(file, pattern) for pattern in paths):
                    errors.append(f"change outside spec paths: {file}")
    if errors:
        raise ValueError("\n".join(errors))
    print(f"SDD checks passed ({len(directories)} specification(s), {'ready' if args.require_complete or (body is not None and not draft) else 'structure'}).")


def new_feature(root: Path, args) -> None:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug) or args.issue < 1:
        raise ValueError("slug must use lowercase letters, digits and hyphens; issue must be positive")
    feature_id = f"{args.issue:03d}-{args.slug}"
    directory = selected_spec(root, "specs/" + feature_id)
    if directory.exists():
        raise ValueError("Feature already exists; refusing to overwrite it.")
    rendered = {}
    for name in ARTIFACTS:
        source = root / ".specify/templates" / f"{name}-template.md"
        content = source.read_text(encoding="utf-8")
        rendered[name] = content.replace("{{FEATURE_ID}}", feature_id).replace("{{ISSUE}}", str(args.issue))
    directory.mkdir(parents=True, exist_ok=False)
    for name, content in rendered.items():
        (directory / f"{name}.md").write_text(content, encoding="utf-8")
    state = root / ".specify/feature.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"feature_directory": directory.relative_to(root).as_posix()}, indent=2) + "\n", encoding="utf-8")
    print(f"Created {directory.relative_to(root)}. Fill in the four artifacts before the ready gate.")


def sync_agents(root: Path, readonly: bool) -> None:
    shared = (root / "AGENTS.md").read_text(encoding="utf-8")
    generated = "<!-- Generated by python tooling/sdd.py sync-agents. Edit AGENTS.md. -->\n\n" + shared
    outputs = {root / "CLAUDE.md": generated, root / ".github/copilot-instructions.md": generated}
    sources = list((root / "tooling/skills").glob("*/SKILL.md"))
    if not sources:
        raise ValueError("No team skills found under tooling/skills/.")
    for source in sources:
        for integration in (".agents", ".claude", ".github"):
            outputs[root / integration / "skills" / source.parent.name / "SKILL.md"] = source.read_text(encoding="utf-8")
    names = {source.parent.name for source in sources}
    orphans = [path for integration in (".agents", ".claude", ".github")
               for path in (root / integration / "skills").glob("company-*")
               if path.name not in names]
    drift = [f"orphan {path.relative_to(root)}" for path in orphans] if readonly else []
    if not readonly:
        for path in orphans:
            if path.is_symlink() or path.is_file(): path.unlink()
            else: shutil.rmtree(path)
            print(f"Removed orphan managed skill: {path.relative_to(root)}")
    for destination, content in outputs.items():
        if not destination.exists() or destination.read_text(encoding="utf-8") != content:
            if readonly:
                drift.append(str(destination.relative_to(root)))
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
    if drift:
        raise ValueError("Agent files drifted; run sync-agents:\n" + "\n".join(drift))
    print(f"Agent {'consistency checked' if readonly else 'files synchronized'} ({len(outputs)} files).")


def current_feature(root: Path) -> None:
    value = os.environ.get("SPECIFY_FEATURE_DIRECTORY")
    if not value:
        pointer = root / ".specify/feature.json"
        if pointer.is_file():
            value = json.loads(pointer.read_text(encoding="utf-8")).get("feature_directory")
    if not isinstance(value, str) or not value:
        raise ValueError("Select a feature with sdd.py new or SPECIFY_FEATURE_DIRECTORY=specs/<id>.")
    directory = selected_spec(root, value)
    if not (directory / "spec.md").is_file():
        raise ValueError("Selected feature is missing spec.md; select an existing specs/<id>.")
    print(json.dumps({"FEATURE_DIR": str(directory),
                      "RELATIVE_DIR": directory.relative_to(root).as_posix()}, ensure_ascii=True))


def contracts(root: Path) -> None:
    from jsonschema import FormatChecker
    from jsonschema.validators import validator_for
    from referencing import Registry, Resource
    documents = []
    resources = []
    for path in sorted((root / "contracts").rglob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        validator_for(schema).check_schema(schema)
        documents.append(schema)
        if schema.get("$id"):
            resources.append((schema["$id"], Resource.from_contents(schema)))
    registry = Registry().with_resources(resources)
    validators = {}
    for schema in documents:
        cls = validator_for(schema)
        identifier = schema.get("properties", {}).get("schema", {}).get("const")
        if not identifier:  # Shared $defs documents are resolved through the registry.
            continue
        if identifier in validators:
            raise ValueError(f"Duplicate schema identifier: {identifier}")
        validators[identifier] = cls(schema, registry=registry, format_checker=FormatChecker())
    if not validators:
        raise ValueError("No contract schemas found.")
    fixtures = list((root / "contracts/fixtures").rglob("*.json"))
    if not fixtures:
        raise ValueError("No shared contract fixtures found.")
    for path in fixtures:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") not in validators:
            raise ValueError(f"Fixture has unknown schema: {path.relative_to(root)}")
        errors = list(validators[data["schema"]].iter_errors(data))
        if errors:
            raise ValueError(f"{path.relative_to(root)}: {errors[0].message}")
    print(f"Contract schemas/fixtures passed ({len(documents)} schemas, {len(fixtures)} fixture files).")


def doctor(root: Path) -> None:
    print(f"Repository: {root}\nPython: {sys.version.split()[0]}")
    if sys.version_info < (3, 11):
        raise ValueError("Python >=3.11 required")
    for name in ("git", "node", "pnpm", "gh", "specify"):
        print(f"{name}: {shutil.which(name) or 'not installed (see CONTRIBUTING.md)'}")
    print("Employee payload, Windows compiler and production access are checked separately; doctor does not connect or publish.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("new")
    create.add_argument("slug"); create.add_argument("--issue", type=int, required=True)
    validate = commands.add_parser("check")
    validate.add_argument("--spec"); validate.add_argument("--require-complete", action="store_true")
    validate.add_argument("--pr-body"); validate.add_argument("--event"); validate.add_argument("--draft", action="store_true")
    validate.add_argument("--base")
    sync = commands.add_parser("sync-agents"); sync.add_argument("--check", action="store_true")
    commands.add_parser("contracts"); commands.add_parser("doctor"); commands.add_parser("current")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "new": new_feature(root, args)
        elif args.command == "check": check(root, args)
        elif args.command == "sync-agents": sync_agents(root, args.check)
        elif args.command == "contracts": contracts(root)
        elif args.command == "current": current_feature(root)
        else: doctor(root)
    except (ValueError, OSError, ImportError, subprocess.CalledProcessError) as exc:
        print(f"SDD error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
