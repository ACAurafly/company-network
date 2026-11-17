#!/usr/bin/env python3
"""Package an explicit 1.3 build and Git-tracked sources; never install or publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import zipfile


PAYLOAD_FILES = {
    "engine/" + name for name in (
        "vpnclient_x64.exe", "vpncmd_x64.exe", "vpncmgr_x64.exe", "vpninstall.exe",
        "hamcore.se2", "lang.config", "LICENSE.txt")
} | {"profile.vpn", "transport.vpn", "company-ca.cer", "public-config.json"}
SOURCE_EXTENSIONS = {".cs", ".ps1", ".ico", ".manifest", ".py", ".md", ".txt"}
EXCLUDED_PARTS = {".git", "build", "private", "evidence", "investigation", "client_log", "__pycache__"}
REPOSITORY_ONLY_ROOTS = {".agents", ".claude", ".github", ".githooks", ".specify", "specs", "tooling"}
REPOSITORY_ONLY_FILES = {"AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".gitattributes"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def source_files(repo):
    files = {}
    tracked = git(repo, "ls-files", "-z").decode("utf-8").split("\0")
    for name in filter(None, tracked):
        entry = PurePosixPath(name)
        lower = name.lower()
        if (entry.is_absolute() or ".." in entry.parts or
                any(p.lower() in EXCLUDED_PARTS for p in entry.parts) or
                any(s in lower for s in (".private.", "state.json", "vpn_client.config", "credentials", "accounts"))):
            raise ValueError("Tracked file requires release review: " + name)
        if name in REPOSITORY_ONLY_FILES or entry.parts[0] in REPOSITORY_ONLY_ROOTS:
            continue
        permitted = (name in {".gitignore", "README.md", "INTEGRATION.md", "员工说明.txt"} or
                     (entry.suffix.lower() in SOURCE_EXTENSIONS and
                      len(entry.parts) > 1 and entry.parts[0] in {"bootstrap", "tools", "docs"}))
        if not permitted:
            raise ValueError("Tracked file outside source allowlist: " + name)
        path = repo / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(repo):
            raise ValueError("Missing or linked tracked file: " + name)
        files[name] = path.read_bytes()
    for required in ("bootstrap/Build.ps1", "bootstrap/CompanyNetwork.ico", "README.md", "员工说明.txt", "tools/package_release.py"):
        if required not in files:
            raise ValueError("Required source must be Git-tracked: " + required)
    return files


def read_payload(path):
    raw = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(PAYLOAD_FILES) or set(names) != PAYLOAD_FILES:
            raise ValueError("Payload must contain exactly the 11 public files (no directory entries).")
        if any(i.file_size <= 0 or i.file_size > 128 * 1024 * 1024 for i in archive.infolist()):
            raise ValueError("Payload file size outside supported range.")
        if sum(i.file_size for i in archive.infolist()) > 256 * 1024 * 1024:
            raise ValueError("Payload exceeds supported total size.")
        if archive.testzip() is not None:
            raise ValueError("Payload CRC failure.")
        license_text = archive.read("engine/LICENSE.txt")
    return raw, license_text


def inspect_exe(path):
    if os.name != "nt":
        raise ValueError("Run packaging on Windows to inspect the managed executable resource and version.")
    # Pass the path through the environment, never interpolate it into PowerShell code.
    command = r"""
$ErrorActionPreference = 'Stop'
$p = $env:COMPANY_RELEASE_EXE
$v = [Diagnostics.FileVersionInfo]::GetVersionInfo($p).FileVersion
$a = [Reflection.Assembly]::LoadFile($p)
$s = $a.GetManifestResourceStream('company.payload.zip')
if ($null -eq $s) { throw 'Embedded public payload missing' }
try {
    $h = [Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($h.ComputeHash($s)).Replace('-', '').ToLowerInvariant() }
    finally { $h.Dispose() }
} finally { $s.Dispose() }
@{ version = $v; payload_sha256 = $hash } | ConvertTo-Json -Compress
"""
    env = dict(os.environ, COMPANY_RELEASE_EXE=str(path))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            env=env, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Executable inspection failed; supply a built managed CompanyNetwork 1.3 executable.")
    metadata = json.loads(result.stdout.lstrip("\ufeff"))
    if metadata["version"] != "1.3.0.0":
        raise ValueError("Expected executable FileVersion 1.3.0.0.")
    return metadata


def write_zip(path, files):
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(files):
            raise ValueError("Output ZIP content/CRC failure.")
        for name, data in files.items():
            if sha(archive.read(name)) != sha(data):
                raise ValueError("Output ZIP member hash failure: " + name)


def sums(files):
    return "".join(sha(data) + "  " + name + "\n" for name, data in sorted(files.items())).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New, nonexistent directory; never overwritten")
    args = parser.parse_args()
    repo, exe, payload = (p.resolve(strict=True) for p in (args.source_repo, args.exe, args.payload))
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError("Output directory already exists; choose a new release path.")
    sources = source_files(repo)
    payload_data, license_text = read_payload(payload)
    metadata = inspect_exe(exe)
    if metadata["payload_sha256"] != sha(payload_data):
        raise ValueError("EXE embedded payload differs from --payload.")
    employee = {"公司网络.exe": exe.read_bytes(), "员工说明.txt": sources["员工说明.txt"], "LICENSE.txt": license_text}
    employee["SHA256SUMS.txt"] = sums(employee)
    manifest = {
        "version": metadata["version"], "git_head": git(repo, "rev-parse", "HEAD").decode().strip(),
        "tracked_worktree_modified": bool(git(repo, "diff", "HEAD", "--name-only").strip()),
        "exe_sha256": sha(employee["公司网络.exe"]), "payload_sha256": sha(payload_data),
        "source_sha256": {name: sha(data) for name, data in sorted(sources.items())},
        "checks": {"payload_exact_11_files_crc": "passed", "exe_embedded_payload_matches": "passed",
                   "zip_member_content_crc_sha256": "passed"},
        "validation_scope": "Packaging checks only; this command does not run the app or business acceptance.",
        "release_acceptance": "pending: final-build window X/reopen, installation/upgrade, business regression and employee external-network acceptance; see docs/implementation.md",
        "source_correspondence": "Source snapshot and EXE hashes recorded; packaging alone does not prove EXE was built from this snapshot.",
    }
    sources["company.payload.zip"] = payload_data
    sources["BUILD-MANIFEST.json"] = json_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".company-release-", dir=output.parent) as temporary:
        staging = Path(temporary) / "release"
        staging.mkdir()
        write_zip(staging / "公司网络-1.3-员工.zip", employee)
        write_zip(staging / "公司网络-1.3-源码.zip", sources)
        (staging / "验证摘要.json").write_bytes(json_bytes(manifest))
        artifacts = {p.name: p.read_bytes() for p in staging.iterdir()}
        (staging / "SHA256SUMS.txt").write_bytes(sums(artifacts))
        staging.rename(output)
    print(json.dumps({"output_dir": str(output), "source_files": len(sources), "employee_files": len(employee),
                      "exe_sha256": manifest["exe_sha256"], "packaging_checks": "passed",
                      "release_acceptance": "pending"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        raise SystemExit("Packaging failed: " + str(error))
