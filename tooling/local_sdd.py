#!/usr/bin/env python3
"""Select local Spec Kit features and check their delivery artifacts (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tooling/local_speckit"))
from common import persist_feature_json, resolve_template_content  # noqa: E402

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TASK = re.compile(r"^\s*- \[([ xX])\] (T\d{3,})\b\s+(.+)$", re.MULTILINE)
PLACEHOLDER = re.compile(r"\[NEEDS CLARIFICATION\b|TODO\(|\[(?:FEATURE|FEATURE NAME|PROJECT_NAME|DATE|DESCRIPTION|###-feature-name)\]")


def feature_path(value: str) -> Path:
    """Accept a slug or a directory under this checkout's .scratch/."""
    candidate = ROOT / ".scratch" / value if SLUG.fullmatch(value) else ROOT / value
    candidate = candidate.resolve()
    scratch = (ROOT / ".scratch").resolve()
    if not scratch.is_relative_to(ROOT) or not candidate.is_relative_to(scratch) or candidate == scratch:
        raise ValueError("Feature must be a directory inside this repository's .scratch/.")
    return candidate


def current_feature(explicit: str | None = None) -> Path:
    value = explicit or os.environ.get("SPECIFY_FEATURE_DIRECTORY")
    if not value:
        pointer = ROOT / ".specify/feature.json"
        if pointer.is_file():
            value = json.loads(pointer.read_text(encoding="utf-8")).get("feature_directory")
    if not isinstance(value, str) or not value:
        raise ValueError("Select a feature first: python tooling/local_sdd.py new <slug> or use <slug>.")
    feature = feature_path(value)
    if not (feature / "spec.md").is_file():
        raise ValueError(f"spec.md not found in {feature}; use 'new <slug>' for new work.")
    return feature


def select_feature(feature: Path) -> None:
    override = os.environ.get("SPECIFY_FEATURE_DIRECTORY")
    if override and feature_path(override) != feature:
        raise ValueError("SPECIFY_FEATURE_DIRECTORY selects another feature; clear or update it first.")
    if os.environ.get("SPECIFY_FEATURE_NO_PERSIST", "") not in ("1", "true"):
        persist_feature_json(ROOT, feature.relative_to(ROOT).as_posix())


def describe(feature: Path) -> dict:
    return {
        "FEATURE_DIR": str(feature),
        "SPEC_FILE": str(feature / "spec.md"),
        "PLAN_FILE": str(feature / "plan.md"),
        "TASKS_FILE": str(feature / "tasks.md"),
        "EVIDENCE_FILE": str(feature / "evidence.md"),
    }


def new_feature(slug: str) -> Path:
    if not SLUG.fullmatch(slug) or slug.split("-")[0].upper() in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))
    }:
        raise ValueError("Use a portable lowercase slug, for example camera-calibration.")
    feature = feature_path(slug)
    if feature.exists():
        raise ValueError(f"Feature already exists: {feature}. Select it with 'use {slug}'.")
    override = os.environ.get("SPECIFY_FEATURE_DIRECTORY")
    if override and feature_path(override) != feature:
        raise ValueError("SPECIFY_FEATURE_DIRECTORY selects another feature; clear or update it first.")
    template = resolve_template_content("spec-template", ROOT)
    if not template or not template.strip():
        raise ValueError("The Spec Kit spec-template is missing or empty.")
    feature.mkdir(parents=True)
    (feature / "spec.md").write_text(template, encoding="utf-8")
    select_feature(feature)
    return feature


def check_feature(feature: Path, complete: bool) -> dict:
    required = ["spec.md", "plan.md", "tasks.md"]
    if complete:
        required.append("evidence.md")
    contents = {}
    errors = []
    for name in required:
        path = feature / name
        if not path.is_file() or not (content := path.read_text(encoding="utf-8")).strip():
            errors.append(f"{name}: missing or empty")
            continue
        contents[name] = content
        if PLACEHOLDER.search(content):
            errors.append(f"{name}: unresolved template placeholder or clarification")
    # Ignore fenced examples; only actual task lines count toward completion.
    task_text = re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$", "", contents.get("tasks.md", ""))
    tasks = TASK.findall(task_text)
    for line in task_text.splitlines():
        if re.match(r"\s*- \[[ xX]\]", line) and not TASK.fullmatch(line):
            errors.append(f"tasks.md: malformed task: {line.strip()}")
    if not tasks:
        errors.append("tasks.md: no tasks in '- [ ] T001 description' format")
    ids = [task_id for _, task_id, _ in tasks]
    if len(ids) != len(set(ids)):
        errors.append("tasks.md: duplicate task IDs")
    unchecked = [task_id for state, task_id, _ in tasks if state == " "]
    if complete and unchecked:
        errors.append("tasks.md: unfinished tasks: " + ", ".join(unchecked))
    if complete:
        for checklist in sorted((feature / "checklists").glob("*.md")):
            if re.search(r"^\s*- \[ \]", checklist.read_text(encoding="utf-8"), re.MULTILINE):
                errors.append(f"checklists/{checklist.name}: unchecked criteria")
    return {"FEATURE_DIR": str(feature), "ok": not errors, "tasks": len(tasks), "unfinished": unchecked, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("new", help="Create and select a feature without replacing existing files").add_argument("slug")
    commands.add_parser("use", help="Select an existing local feature").add_argument("feature")
    commands.add_parser("current", help="Print the selected feature paths as JSON")
    check = commands.add_parser("check", help="Check artifact structure; does not execute product tests")
    check.add_argument("--spec", help="Feature directory or slug; defaults to the selected feature")
    check.add_argument("--require-complete", action="store_true", help="Also require evidence and completed tasks/checklists")
    args = parser.parse_args()
    try:
        if args.command == "new":
            result = describe(new_feature(args.slug))
        elif args.command == "use":
            feature = current_feature(args.feature)
            select_feature(feature)
            result = describe(feature)
        elif args.command == "current":
            result = describe(current_feature())
        else:
            result = check_feature(current_feature(args.spec), args.require_complete)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result.get("ok", True) else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
