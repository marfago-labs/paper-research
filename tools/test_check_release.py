"""Offline tests for check_release.py. Run: python tools/test_check_release.py"""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_release

CHANGELOG = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-11-12

## [0.1.0] - 2026-11-11
"""


def project(version, changelog=CHANGELOG):
    folder = tempfile.TemporaryDirectory()
    root = Path(folder.name)
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return folder, root


class Checks(unittest.TestCase):
    def test_a_version_with_an_entry_and_a_matching_tag_is_fine(self):
        folder, root = project("0.2.0")
        with folder:
            self.assertEqual(check_release.problems(None, root), [])
            self.assertEqual(check_release.problems("v0.2.0", root), [])

    def test_a_version_without_a_changelog_entry_is_reported(self):
        folder, root = project("0.3.0")
        with folder:
            self.assertEqual(check_release.problems(None, root), ["CHANGELOG.md has no entry for version 0.3.0"])

    def test_only_a_dated_entry_counts(self):
        undated = "## [0.3.0]\n\n## [0.3.0] - unreleased\n\n## 0.3.0 - 2026-11-12\n\n- [0.3.0] - 2026-11-12\n"
        folder, root = project("0.3.0", undated)
        with folder:
            self.assertEqual(check_release.changelog_versions(root), [])

    def test_a_tag_that_is_not_the_version_is_reported(self):
        folder, root = project("0.2.0")
        with folder:
            for tag in ("v0.1.0", "0.2.0", "v0.2.0-rc1", "v0.2"):
                found = check_release.problems(tag, root)
                self.assertEqual(len(found), 1, tag)
                self.assertIn(f"the tag {tag} is not v0.2.0", found[0])

    def test_both_problems_are_reported_together(self):
        folder, root = project("0.3.0")
        with folder:
            self.assertEqual(len(check_release.problems("v0.2.0", root)), 2)


class ThisRepository(unittest.TestCase):
    def test_the_plugin_version_has_a_changelog_entry(self):
        # A release PR that bumps the version without a changelog entry fails here, in every CI run.
        self.assertEqual(check_release.problems(), [])


class CommandLine(unittest.TestCase):
    def run_main(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_release.main(args)
        return code, out.getvalue()

    def test_exit_codes(self):
        version = check_release.plugin_version()
        self.assertEqual(self.run_main([f"v{version}"])[0], 0)
        self.assertEqual(self.run_main([])[0], 0)
        code, out = self.run_main(["v0.0.0"])
        self.assertEqual(code, 1)
        self.assertIn("error: the tag v0.0.0 is not", out)
        self.assertEqual(self.run_main(["a", "b"])[0], 2)

    def test_run_as_a_script_takes_the_tag_from_the_command_line(self):
        for tag, expected in ((f"v{check_release.plugin_version()}", 0), ("v0.0.0", 1)):
            with mock.patch.object(sys, "argv", ["check_release.py", tag]), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    runpy.run_path(check_release.__file__, run_name="__main__")
            self.assertEqual(stopped.exception.code, expected, tag)


if __name__ == "__main__":
    unittest.main()
