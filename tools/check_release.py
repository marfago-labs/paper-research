#!/usr/bin/env python3
"""Check that a release is consistent: the plugin version has a changelog entry, and a tag matches the version.

Usage: python tools/check_release.py [TAG]
Without TAG it checks only the changelog entry. With a tag such as v0.2.0 it also checks that the tag is the
plugin version. Exit 0 if everything agrees, 1 if not, 2 for the wrong arguments.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", re.M)


def plugin_version(root=ROOT):
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return manifest["version"]


def changelog_versions(root=ROOT):
    return ENTRY.findall((root / "CHANGELOG.md").read_text(encoding="utf-8"))


def problems(tag=None, root=ROOT):
    """What disagrees: the changelog has no entry for the plugin version, or the tag is not the version."""
    version = plugin_version(root)
    found = []
    if version not in changelog_versions(root):
        found.append(f"CHANGELOG.md has no entry for version {version}")
    if tag is not None and tag != f"v{version}":
        found.append(f"the tag {tag} is not v{version}, the version in .claude-plugin/plugin.json")
    return found


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print(__doc__)
        return 2
    found = problems(args[0] if args else None)
    for line in found:
        print(f"error: {line}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
