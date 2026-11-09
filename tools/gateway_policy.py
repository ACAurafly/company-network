"""Generate candidates only; never overwrite active Mihomo configuration."""
import argparse
import hashlib
import json
import re
from pathlib import Path

DOMAIN = "office-trial-2dd76438.vpnazure.net"
RULE = "DOMAIN," + DOMAIN + ",DIRECT"


def candidate(text):
    # Deliberately support a narrow block-list YAML grammar; fail closed on flow lists/ambiguity.
    lines = text.splitlines(keepends=True)
    headers = [i for i, line in enumerate(lines) if re.match(r"^rules\s*:", line)]
    if len(headers) != 1 or not re.match(r"^rules\s*:\s*(?:#.*)?(?:\r?\n)?$", lines[headers[0]]):
        raise ValueError("Expected one top-level block-style rules list")
    start = headers[0] + 1
    end = start
    while end < len(lines) and (not lines[end].strip() or lines[end].lstrip().startswith("#") or
                               lines[end][0].isspace() or re.match(r"^-\s", lines[end])):
        end += 1
    entries = []
    for i in range(start, end):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^(\s*)-\s+(['\"]?)([^'\"#]+)\2\s*(?:#.*)?$", lines[i].rstrip("\r\n"))
        if not match:
            raise ValueError("Unsupported rules syntax; no candidate written")
        fields = [v.strip() for v in match.group(3).split(",")]
        if DOMAIN in fields:
            if fields != ["DOMAIN", DOMAIN, "DIRECT"]:
                raise ValueError("Conflicting exact-domain rule; review required")
            entries.append(i)
    # Move any existing duplicate exact rule to the first priority position, preserving all other lines.
    newline = "\r\n" if "\r\n" in text else "\n"
    remaining = [line for i, line in enumerate(lines) if i not in entries]
    if not remaining[headers[0]].endswith("\n"):
        remaining[headers[0]] += newline
    insertion = start
    indent = "  "
    for line in lines[start:end]:
        match = re.match(r"^(\s*)-\s", line)
        if match:
            indent = match.group(1)
            break
    remaining.insert(insertion, indent + "- " + RULE + newline)
    return "".join(remaining)


def generate(source, destination):
    if source.resolve() == destination.resolve():
        raise ValueError("Candidate destination must differ from source")
    original = source.read_bytes()
    updated = candidate(original.decode("utf-8-sig")).encode("utf-8")
    if original.startswith(b"\xef\xbb\xbf"):
        updated = b"\xef\xbb\xbf" + updated
    # Exclusive creation also prevents accidental overwrite of a previous candidate or symlink target.
    with destination.open("xb") as output:
        output.write(updated)
    return {"source_sha256": hashlib.sha256(original).hexdigest(),
            "candidate_sha256": hashlib.sha256(updated).hexdigest(), "changed": original != updated}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active", required=True, type=Path)
    parser.add_argument("--tail", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        # Validate both before producing either candidate. Do not echo source text or exceptions.
        candidate(args.active.read_bytes().decode("utf-8-sig"))
        candidate(args.tail.read_bytes().decode("utf-8-sig"))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        print(json.dumps({"rule": RULE, "active": generate(args.active, args.output_dir / "config.candidate.yaml"),
                          "tail": generate(args.tail, args.output_dir / "gateway-tail.candidate.yaml")}, indent=2))
    except (ValueError, OSError, UnicodeError):
        parser.exit(1, "Candidate generation failed; check paths, existing outputs, block rules syntax, or conflicting exact-domain rules. No source configuration overwritten.\n")


if __name__ == "__main__":
    main()
