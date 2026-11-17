"""Verify the pinned, unmodified upstream Spec Kit integration files."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def verify(root=ROOT):
    manifest = json.loads((root / "tooling/vendor/spec-kit/manifest.json").read_text())
    if manifest["version"] != "1.1.2": raise ValueError("Unexpected Spec Kit pin")
    for relative, expected in manifest["files"].items():
        file = (root / relative).resolve()
        if not file.is_relative_to(root.resolve()): raise ValueError("Unsafe vendor path")
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Upstream file changed: {relative}; upgrade with reviewed manifest")
    print(f"Spec Kit v{manifest['version']} verified: {len(manifest['files'])} files")

if __name__ == "__main__": verify()
