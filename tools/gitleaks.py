#!/usr/bin/env python3
"""Scan the repository for secrets with gitleaks, the same way locally and in CI.

Downloads the pinned gitleaks release for this platform once, checks it against the SHA-256 below,
keeps it in .cache/gitleaks/, and runs it.

Usage:
  python tools/gitleaks.py            scan every commit reachable from HEAD (CI runs this)
  python tools/gitleaks.py --staged   scan only the staged changes (the pre-commit hook runs this)
Exit codes: 0 no leaks, 1 leaks found (or gitleaks itself failed; it says which), 2 gitleaks couldn't be set up.
To change the version, update VERSION, every checksum from the release's checksums.txt, and the asset ids.
"""

import argparse
import hashlib
import io
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "8.30.1"
SHA256 = {
    "darwin_arm64.tar.gz": "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5",
    "darwin_x64.tar.gz": "dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709",
    "linux_arm64.tar.gz": "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080",
    "linux_x64.tar.gz": "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    "windows_x64.zip": "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e",
}
# Release asset ids, for the GitHub API download, which still works when the github.com download URL fails.
ASSET_IDS = {
    "darwin_arm64.tar.gz": 378332059,
    "darwin_x64.tar.gz": 378332053,
    "linux_arm64.tar.gz": 378332057,
    "linux_x64.tar.gz": 378332058,
    "windows_x64.zip": 378333178,
}
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "gitleaks" / VERSION
URL = "https://github.com/gitleaks/gitleaks/releases/download/v{version}/gitleaks_{version}_{asset}"
API_URL = "https://api.github.com/repos/gitleaks/gitleaks/releases/assets/{id}"


class SetupError(Exception):
    pass


def asset_name():
    system = {"linux": "linux", "darwin": "darwin", "win32": "windows"}.get(sys.platform)
    machine = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    suffix = "zip" if system == "windows" else "tar.gz"
    asset = f"{system}_{machine}.{suffix}"
    if asset not in SHA256:
        raise SetupError(f"no pinned gitleaks build for {sys.platform} on {platform.machine()}")
    return asset


def extract(archive, asset, binary_name):
    """Return the bytes of the gitleaks binary inside the archive, ignoring every other member."""
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            return bundle.read(binary_name)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        member = bundle.extractfile(binary_name)
        if member is None:
            raise SetupError(f"{binary_name} is not a file in {asset}")
        return member.read()


def download(asset):
    """The archive for this platform. Tries the release URL, then the API, and checks the SHA-256 of what it got."""
    urls = [URL.format(version=VERSION, asset=asset), API_URL.format(id=ASSET_IDS[asset])]
    failures = []
    for url in urls:
        # Fixed https URLs. The API one redirects to a signed download, which the checksum below covers.
        request = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
                archive = response.read()
        except OSError as err:
            failures.append(f"{url}: {err}")
            continue
        digest = hashlib.sha256(archive).hexdigest()
        if digest == SHA256[asset]:
            return archive
        failures.append(f"{url}: checksum mismatch, expected {SHA256[asset]}, got {digest}")
    raise SetupError("couldn't download gitleaks:\n  " + "\n  ".join(failures))


def ensure_binary():
    """The path to a verified gitleaks binary, downloading it the first time."""
    asset = asset_name()
    binary_name = "gitleaks.exe" if asset.endswith(".zip") else "gitleaks"
    binary = CACHE / binary_name
    if binary.exists():
        return binary
    print(f"downloading gitleaks {VERSION} ({asset})", file=sys.stderr)
    archive = download(asset)
    try:
        data = extract(archive, asset, binary_name)
    except (KeyError, tarfile.TarError, zipfile.BadZipFile) as err:
        raise SetupError(f"couldn't unpack {asset}: {err}") from None
    CACHE.mkdir(parents=True, exist_ok=True)
    # Write beside the target and rename, so a run that stops halfway never leaves a broken binary.
    with tempfile.NamedTemporaryFile(dir=CACHE, delete=False) as handle:
        handle.write(data)
    os.chmod(handle.name, 0o755)
    os.replace(handle.name, binary)
    return binary


def main(argv):
    parser = argparse.ArgumentParser(description="Scan the repository for secrets with gitleaks.")
    parser.add_argument("--staged", action="store_true", help="scan only the staged changes")
    args = parser.parse_args(argv)
    try:
        binary = ensure_binary()
    except SetupError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    command = [str(binary), "git", "--no-banner", "--redact"]
    if args.staged:
        command += ["--pre-commit", "--staged"]
    command.append(str(ROOT))
    result = subprocess.run(command, check=False)
    if result.returncode == 1:
        print(
            "gitleaks found something that looks like a secret. If it's real, remove it and rotate it."
            " If it isn't, add `gitleaks:allow` in a comment on that line.",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
