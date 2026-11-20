"""Offline tests for run_mutation.py. Run: python tools/test_run_mutation.py"""

import contextlib
import io
import json
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_mutation

CONFIG = '[cosmic-ray]\nmodule-path = "x.py"\n\n[cosmic-ray.distributor]\nname = "local"\n'


class Ports(unittest.TestCase):
    def test_every_worker_gets_its_own_free_port(self):
        ports = run_mutation.free_ports(4)
        self.assertEqual(len(set(ports)), 4)
        for port in ports:
            with contextlib.closing(socket.socket()) as probe:
                probe.bind(("127.0.0.1", port))  # still free, so a worker can take it


class Startup(unittest.TestCase):
    def test_a_worker_that_has_stopped_is_reported_whatever_listens_on_its_port(self):
        with contextlib.closing(socket.socket()) as other:
            other.bind(("127.0.0.1", 0))
            other.listen()
            stopped = mock.Mock()
            stopped.poll.return_value = 1
            with self.assertRaisesRegex(SystemExit, "stopped before it was ready"):
                run_mutation.wait_until_listening(other.getsockname()[1], stopped)

    def test_a_running_worker_is_ready_once_its_port_listens(self):
        with contextlib.closing(socket.socket()) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            running = mock.Mock()
            running.poll.return_value = None
            run_mutation.wait_until_listening(listener.getsockname()[1], running)

    def test_a_worker_that_never_listens_is_reported(self):
        running = mock.Mock()
        running.poll.return_value = None
        with mock.patch.object(run_mutation, "STARTUP", 0), self.assertRaisesRegex(SystemExit, "did not start"):
            run_mutation.wait_until_listening(run_mutation.free_ports(1)[0], running)


class Configuration(unittest.TestCase):
    def test_mutants_are_sent_to_the_workers(self):
        text = run_mutation.http_config(CONFIG, [9001, 9002])
        self.assertIn('name = "http"', text)
        self.assertIn("worker-urls = ['http://127.0.0.1:9001', 'http://127.0.0.1:9002']", text)
        self.assertNotIn('name = "local"', text)
        self.assertIn('module-path = "x.py"', text)

    def test_windows_line_endings_are_read_too(self):
        self.assertIn('name = "http"', run_mutation.http_config(CONFIG.replace("\n", "\r\n"), [9001]))

    def test_a_configuration_without_the_local_distributor_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "expected the configuration to contain"):
            run_mutation.http_config('[cosmic-ray]\nmodule-path = "x.py"\n', [9001])


class Workers(unittest.TestCase):
    def test_one_worker_means_the_run_tests_mutants_itself(self):
        with run_mutation.workers(mock.Mock(), 1) as ports:
            self.assertEqual(ports, [])


class Fingerprint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for folder in ("mutation", "tools", "s", "dep/sub", ".github/workflows"):
            (self.root / folder).mkdir(parents=True)
        run_mutation.run(["git", "init", "-q"], self.root)
        self.write(
            ".github/workflows/mutation.yml", b'- {module: m, limit: 0, paths: "s dep"}\n- {module: o, paths: "x"}\n'
        )
        self.write("mutation/m.toml", b"[cosmic-ray]\n")
        self.write("tools/run_tests.py", b"run\n")
        self.write("s/m.py", b"a = 1\n")
        self.write("dep/sub/helper.py", b"b = 2\n")
        self.write("other.py", b"c = 3\n")

    def write(self, name, data):
        (self.root / name).write_bytes(data)
        run_mutation.run(["git", "add", "-f", name], self.root)

    def hash(self):
        return run_mutation.fingerprint(self.root, "m")

    def test_the_paths_the_workflow_lists_are_what_it_depends_on(self):
        self.assertEqual(run_mutation.dependencies(self.root, "m"), ["s", "dep"])

    def test_the_configuration_the_test_runner_and_every_listed_file_each_change_the_hash(self):
        before = self.hash()
        for name in ("mutation/m.toml", "tools/run_tests.py", "s/m.py", "dep/sub/helper.py"):
            original = (self.root / name).read_bytes()
            self.write(name, original + b"# changed\n")
            self.assertNotEqual(self.hash(), before, name)
            self.write(name, original)
        self.assertEqual(self.hash(), before)

    def test_a_file_outside_those_paths_does_not(self):
        before = self.hash()
        self.write("other.py", b"changed\n")
        self.assertEqual(self.hash(), before)

    def test_a_file_git_does_not_track_does_not(self):
        before = self.hash()
        (self.root / "dep/scratch.py").write_bytes(b"x\n")
        (self.root / "dep/.coverage").write_bytes(b"x\n")
        (self.root / "dep/node_modules").mkdir()
        (self.root / "dep/node_modules/pkg.js").write_bytes(b"x\n")
        self.assertEqual(self.hash(), before)

    def test_skill_instructions_are_not_read_by_a_test_and_do_not_count(self):
        before = self.hash()
        self.write("dep/SKILL.md", b"how Claude uses this\n")
        self.write("s/SKILL.md", b"how Claude uses this\n")
        self.assertEqual(self.hash(), before)

    def test_a_file_listed_by_name_counts(self):
        self.write(".github/workflows/mutation.yml", b'- {module: m, paths: "other.py"}\n')
        before = self.hash()
        self.write("other.py", b"changed\n")
        self.assertNotEqual(self.hash(), before)

    def test_line_endings_do_not_change_the_hash(self):
        before = self.hash()
        self.write("s/m.py", b"a = 1\r\n")
        self.assertEqual(self.hash(), before)

    def test_a_tracked_file_deleted_before_the_commit_changes_the_hash_instead_of_failing(self):
        before = self.hash()
        (self.root / "dep/sub/helper.py").unlink()
        self.assertNotEqual(self.hash(), before)

    def test_a_missing_git_is_reported_with_what_to_do(self):
        with mock.patch.object(run_mutation, "run", side_effect=FileNotFoundError("git")):
            with self.assertRaisesRegex(SystemExit, "install git, and trust the repository"):
                self.hash()

    def test_a_repository_git_refuses_is_reported_the_same_way(self):
        refused = subprocess.CalledProcessError(128, "git", stderr="detected dubious ownership")
        with mock.patch.object(run_mutation, "run", side_effect=refused):
            with self.assertRaisesRegex(SystemExit, "safe.directory"):
                self.hash()

    def test_the_hash_is_taken_before_any_mutant_runs(self):
        with (
            mock.patch.object(run_mutation, "fingerprint", side_effect=SystemExit("no git")),
            mock.patch.object(run_mutation.shutil, "copytree") as copied,
            self.assertRaisesRegex(SystemExit, "no git"),
        ):
            run_mutation.main(["init"])
        copied.assert_not_called()


class Limit(unittest.TestCase):
    def test_a_limit_of_zero_fails_on_any_survivor(self):
        # cr-rate --fail-over 0 let 4.09% through, so the limit is compared here.
        self.assertFalse(run_mutation.within_limit("4.09", 0.0))
        self.assertFalse(run_mutation.within_limit("0.15", 0.0))
        self.assertTrue(run_mutation.within_limit("0.00", 0.0))

    def test_a_rate_at_the_limit_passes(self):
        self.assertTrue(run_mutation.within_limit("5.00", 5.0))
        self.assertFalse(run_mutation.within_limit("5.01", 5.0))


REPORT = "total jobs: 367\nsurviving mutants: 2 (0.54%)\n"


class Record(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_the_counts_of_the_run_are_kept(self):
        run_mutation.record(self.root, "init", REPORT, "2026-11-20", "0123abcd")
        kept = json.loads((self.root / "mutation/results/init.json").read_text())
        self.assertEqual(
            kept, {"module": "init", "total": 367, "survivors": 2, "date": "2026-11-20", "hash": "0123abcd"}
        )

    def test_the_badge_adds_up_every_module_that_has_run(self):
        clean = "total jobs: {}\nsurviving mutants: 0 (0.00%)\n"
        run_mutation.record(self.root, "init", clean.format(10), "2026-11-20", "a")
        run_mutation.record(self.root, "graph", clean.format(20), "2026-11-18", "b")
        badge = json.loads((self.root / "mutation/badge.json").read_text())
        self.assertEqual(badge["message"], "0 survivors, 2 modules, 2026-11-18")
        self.assertEqual(badge["color"], "brightgreen")

    def test_a_repository_that_cannot_be_written_does_not_fail_the_run(self):
        (self.root / "mutation").write_text("a file where the folder should be", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as warned:
            run_mutation.record(self.root, "init", REPORT, "2026-11-20", "a")
        self.assertIn("the result of init was not kept", warned.getvalue())

    def test_a_report_without_the_counts_is_refused(self):
        for report in ("nothing here", "total jobs: 3\n"):
            with self.assertRaisesRegex(SystemExit, "did not print the number of mutants"):
                run_mutation.record(self.root, "init", report, "2026-11-20", "a")


if __name__ == "__main__":
    unittest.main()
