"""Disable one active Codex provider's WS flag without reserializing private TOML.

Python 3.11+; no dependencies. Errors deliberately omit input and parser details.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class Refused(ValueError):
    """A safe, public failure message."""


def parsed(data: bytes) -> dict:
    try:
        return tomllib.loads(data.decode("utf-8-sig"))
    except (UnicodeError, tomllib.TOMLDecodeError):
        raise Refused("Invalid UTF-8 TOML; no change made.") from None


def validate(data: bytes, provider: str, expected_url: str, state: bool) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", provider):
        raise Refused("Provider must be a simple TOML table name.")
    url = urlsplit(expected_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise Refused("Expected URL must be an HTTP(S) endpoint without credentials, query or fragment.")
    document = parsed(data)
    entry = document.get("model_providers", {}).get(provider, {})
    if document.get("model_provider") != provider:
        raise Refused("Active provider differs from the expected provider.")
    if entry.get("base_url") != expected_url:
        raise Refused("Provider endpoint differs from the expected endpoint.")
    if entry.get("supports_websockets") is not state:
        raise Refused("Provider WS flag differs from the required current state.")
    return document


def disable(data: bytes, provider: str, expected_url: str) -> bytes:
    before = validate(data, provider, expected_url, True)
    # Match only a conventional, explicitly named table. Semantic comparison
    # below rejects apparent headers/assignments embedded in multiline strings.
    header = re.compile(rb"(?m)^[ \t]*\[model_providers\." + provider.encode() + rb"\][ \t]*(?:#[^\r\n]*)?\r?$")
    headers = list(header.finditer(data))
    if len(headers) != 1:
        raise Refused("Expected exactly one conventional provider table header.")
    start = headers[0].end()
    next_table = re.search(rb"(?m)^[ \t]*\[", data[start:])
    end = start + next_table.start() if next_table else len(data)
    matches = list(re.finditer(rb"(?m)^[ \t]*supports_websockets[ \t]*=[ \t]*(true)(?=[ \t]*(?:#[^\r\n]*)?\r?$)", data[start:end]))
    if len(matches) != 1:
        raise Refused("Expected exactly one literal true WS assignment in the provider table.")
    match = matches[0]
    left, right = start + match.start(1), start + match.end(1)
    changed = data[:left] + b"false" + data[right:]
    expected = copy.deepcopy(before)
    expected["model_providers"][provider]["supports_websockets"] = False
    if validate(changed, provider, expected_url, False) != expected:
        raise Refused("Semantic check found an unexpected configuration change.")
    return changed


def restore_bytes(current: bytes, backup: bytes, provider: str, expected_url: str) -> bytes:
    validate(current, provider, expected_url, False)
    if current != disable(backup, provider, expected_url):
        raise Refused("Configuration changed since backup; automatic rollback refused.")
    return backup


def private_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise Refused("LOCALAPPDATA is required for private backups.")
    root = Path(local) / "CodexPrivate"
    if not root.is_dir() or root.is_symlink():
        raise Refused("Existing controlled CodexPrivate directory is required.")
    return root.resolve()


def write_config(path: Path, original: bytes, replacement: bytes) -> None:
    # Editors must be idle. Recheck immediately before atomic replacement;
    # never rewrite TOML or print any part of the document.
    descriptor, temporary = tempfile.mkstemp(prefix=".codex-transport-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        if path.read_bytes() != original:
            raise Refused("Configuration changed during operation; retry after closing editors.")
        os.replace(temporary, path)
        if path.read_bytes() != replacement:
            raise Refused("Post-write byte verification failed; inspect private backup.")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--expected-base-url", required=True, help="Endpoint only; never pass credentials")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--rollback", type=Path, metavar="PRIVATE_BACKUP")
    args = parser.parse_args()
    try:
        if args.config.is_symlink() or not args.config.is_file():
            raise Refused("Configuration must be an existing regular file, not a symbolic link.")
        config = args.config.resolve()
        original = config.read_bytes()
        backup_path = None
        if args.rollback:
            root = private_root()
            backup_path = args.rollback.resolve()
            if not backup_path.is_relative_to(root) or args.rollback.is_symlink() or backup_path == config:
                raise Refused("Rollback backup must be a separate file inside CodexPrivate.")
            replacement = restore_bytes(original, backup_path.read_bytes(), args.provider, args.expected_base_url)
            write_config(config, original, replacement)
            status = "rolled_back"
        else:
            replacement = disable(original, args.provider, args.expected_base_url)
            status = "validated"
            if args.apply:
                root = private_root()
                # mkstemp supplies a unique backup; inherited ACLs are those of
                # the existing controlled private root, never the repository.
                descriptor, name = tempfile.mkstemp(prefix="codex-transport-", suffix=".toml.bak", dir=root)
                backup_path = Path(name)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
                if backup_path.read_bytes() != original:
                    raise Refused("Private backup byte verification failed.")
                # Revalidate both identity and endpoint immediately before write.
                validate(config.read_bytes(), args.provider, args.expected_base_url, True)
                write_config(config, original, replacement)
                status = "applied"
        print(json.dumps({
            "status": status, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "provider": args.provider, "only_field": "supports_websockets",
            "before_ws": bool(args.rollback is None), "after_ws": bool(args.rollback),
            "before_sha256": hashlib.sha256(original).hexdigest(),
            "after_sha256": hashlib.sha256(replacement).hexdigest(),
            "exact_bytes_verified": True, "private_backup": str(backup_path) if backup_path else None,
            "runtime_validation": "pending; start independent new Codex sessions",
        }, ensure_ascii=False))
        return 0
    except Refused as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
    except (OSError, ValueError, TypeError, AttributeError):
        # No exception detail: paths, TOML and environment may contain secrets.
        print(json.dumps({"status": "error", "reason": "Operation failed; no private content emitted. Inspect local state and private backup."}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
