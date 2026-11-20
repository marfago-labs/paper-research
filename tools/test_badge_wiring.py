"""Offline checks that CI, the badges workflow, badges.py and the README agree. Run: python tools/test_badge_wiring.py

The workflow runs on GitHub only after a merge to main, so a mismatched artifact name or file name would show up
as a broken badge, not as a failing build. These tests catch it first.
"""

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import badges
import run_mutation

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


CI = read(".github/workflows/ci.yml")
PUBLISH = read(".github/workflows/badges.yml")
README = read("README.md")
CONTRIBUTING = read("CONTRIBUTING.md")
GUARD = "github.event_name == 'push' && github.ref == 'refs/heads/main'"


def written_files():
    """The badge files that badges.main writes."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        report = folder / "a.json"
        report.write_text('{"totals": {"num_statements": 1, "covered_lines": 1}}', encoding="utf-8")
        (folder / "a.xml").write_text('<testsuite tests="1"/>', encoding="utf-8")
        with mock.patch("builtins.print"):
            badges.main(["--coverage", str(report), "--junit", str(folder), "--out", str(folder / "out")])
        return {path.name for path in (folder / "out").iterdir()}


class Artifacts(unittest.TestCase):
    def test_the_artifacts_ci_uploads_are_the_ones_the_workflow_downloads(self):
        uploaded = re.findall(r"upload-artifact@.*\n\s+with:\n\s+name: (\S+)\n\s+path: (\S+)", CI)
        downloaded = re.findall(r"download-artifact@.*\n\s+with:\n\s+name: (\S+)\n\s+path: (\S+)", PUBLISH)
        self.assertEqual(
            sorted(uploaded), [("coverage-numbers", "coverage-numbers"), ("scenario-numbers", "scenario-numbers")]
        )
        self.assertEqual(sorted(uploaded), sorted(downloaded))

    def test_ci_writes_into_the_folders_it_uploads(self):
        self.assertIn('coverage json --quiet -o "coverage-numbers/$module.json"', CI)
        self.assertIn("--junit --junit-directory scenario-numbers", CI)

    def test_badges_py_reads_those_folders(self):
        self.assertIn("--coverage coverage-numbers/*.json --junit scenario-numbers --out badges", PUBLISH)

    def test_only_a_push_to_main_uploads(self):
        for step in re.findall(r"- name: Keep the .*?(?=\n      #|\n      - |\Z)", CI, re.S):
            self.assertIn(GUARD, step)


class Publishing(unittest.TestCase):
    def test_it_follows_ci_and_never_a_pull_request(self):
        self.assertIn("workflows: [CI]", PUBLISH)
        self.assertRegex(CI, r"(?m)^name: CI$")
        self.assertNotIn("pull_request", PUBLISH)
        self.assertIn("github.event.workflow_run.event == 'push'", PUBLISH)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", PUBLISH)
        self.assertRegex(PUBLISH, r"(?m)^permissions: \{\}$")

    def test_runs_do_not_overlap_and_each_repository_publishes_to_its_own_branch(self):
        self.assertRegex(PUBLISH, r"(?m)^concurrency:\n  group: badges\n  cancel-in-progress: false$")
        self.assertNotIn("github.repository ==", PUBLISH)
        self.assertIn("https://github.com/${GITHUB_REPOSITORY}.git", PUBLISH)

    def test_the_token_is_never_written_to_the_clone(self):
        self.assertNotIn("x-access-token:${GH_TOKEN}@", PUBLISH)
        self.assertIn("http.extraheader", PUBLISH)

    def test_it_writes_with_no_more_than_it_needs(self):
        self.assertEqual(re.findall(r"(?m)^\s+(\w+): (?:write|read)", PUBLISH), ["contents", "actions"])
        self.assertIn("contents: write", PUBLISH)

    def test_it_pushes_the_branch_the_readme_reads(self):
        self.assertIn("push --quiet origin badges", PUBLISH)
        for name in written_files():
            self.assertIn(f"/badges/{name}", README.replace("%2F", "/"))


class Mutation(unittest.TestCase):
    def test_the_readme_reads_the_file_the_runner_writes(self):
        self.assertIn("/main/mutation/badge.json", README.replace("%2F", "/"))
        self.assertEqual(run_mutation.BADGE.as_posix(), "mutation/badge.json")

    def test_the_documented_container_command_can_write_the_results(self):
        self.assertIn('-v "$PWD/mutation:/src/mutation"', CONTRIBUTING)

    def test_the_documented_container_command_installs_git_and_trusts_the_mount(self):
        # The runner hashes the tracked files with git: python:3.12-slim has none, and git refuses a mount that
        # another user owns.
        self.assertIn("apt-get install -y -qq git", CONTRIBUTING)
        self.assertIn("git config --global --add safe.directory /src", CONTRIBUTING)


class Readme(unittest.TestCase):
    def test_every_badge_file_the_readme_reads_is_one_that_badges_py_writes(self):
        named = re.findall(r"/badges/(\w+\.json)", README.replace("%2F", "/"))
        self.assertEqual(sorted(named), sorted(written_files()))


if __name__ == "__main__":
    unittest.main()
