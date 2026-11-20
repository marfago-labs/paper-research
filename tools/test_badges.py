"""Offline tests for badges.py. Run: python tools/test_badges.py"""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import badges

HERE = Path(__file__).resolve().parent


def write_coverage(folder, name, lines, covered, branches=0, covered_branches=0):
    totals = {"num_statements": lines, "covered_lines": covered}
    if branches:
        totals.update(num_branches=branches, covered_branches=covered_branches)
    path = Path(folder) / name
    path.write_text(json.dumps({"totals": totals}), encoding="utf-8")
    return path


def write_junit(folder, name, tests, failures=0, errors=0, skipped=0):
    attrs = f'tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"'
    (Path(folder) / name).write_text(f'<testsuite name="x" {attrs}></testsuite>', encoding="utf-8")


class Folder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = tmp.name


class Coverage(Folder):
    def test_lines_and_branches_of_every_script_are_added_up(self):
        reports = [
            write_coverage(self.folder, "a.json", 10, 10, 4, 4),
            write_coverage(self.folder, "b.json", 6, 6),
        ]
        self.assertEqual(badges.coverage_counts(reports), (20, 20))

    def test_full_coverage_reads_100_and_is_green(self):
        badge = badges.coverage_badge([write_coverage(self.folder, "a.json", 10, 10, 2, 2)])
        self.assertEqual(
            badge, {"schemaVersion": 1, "label": "unit coverage", "message": "100%", "color": "brightgreen"}
        )

    def test_a_miss_never_rounds_up_to_100(self):
        self.assertEqual(badges.percent_text(9995, 10000), "99.9%")
        self.assertEqual(badges.percent_text(995, 1000), "99.5%")
        self.assertEqual(badges.percent_text(99, 100), "99%")

    def test_the_colour_follows_the_share(self):
        yellow = badges.coverage_badge([write_coverage(self.folder, "a.json", 100, 90)])
        red = badges.coverage_badge([write_coverage(self.folder, "b.json", 100, 89)])
        self.assertEqual((yellow["color"], yellow["message"]), ("yellow", "90%"))
        self.assertEqual((red["color"], red["message"]), ("red", "89%"))

    def test_no_lines_is_an_error(self):
        with self.assertRaisesRegex(SystemExit, "no lines"):
            badges.coverage_badge([write_coverage(self.folder, "a.json", 0, 0)])


class Scenarios(Folder):
    def test_every_feature_file_is_counted(self):
        write_junit(self.folder, "a.xml", 5)
        write_junit(self.folder, "b.xml", 3)
        badge = badges.scenario_badge(self.folder)
        self.assertEqual(badge["message"], "8 passing")
        self.assertEqual(badge["color"], "brightgreen")

    def test_failed_and_errored_scenarios_are_not_passing(self):
        write_junit(self.folder, "a.xml", 10, failures=1, errors=2)
        badge = badges.scenario_badge(self.folder)
        self.assertEqual(badge["message"], "7 of 10 passing")
        self.assertEqual(badge["color"], "red")

    def test_a_skipped_scenario_is_left_out_and_does_not_turn_the_badge_red(self):
        write_junit(self.folder, "a.xml", 10, skipped=3)
        badge = badges.scenario_badge(self.folder)
        self.assertEqual((badge["message"], badge["color"]), ("7 passing", "brightgreen"))

    def test_a_suite_without_counts_adds_nothing(self):
        (Path(self.folder) / "a.xml").write_text("<testsuite/>", encoding="utf-8")
        write_junit(self.folder, "b.xml", 2)
        self.assertEqual(badges.scenario_counts(self.folder), (2, 2))

    def test_no_scenarios_is_an_error(self):
        with self.assertRaisesRegex(SystemExit, "no scenarios"):
            badges.scenario_badge(self.folder)


class Mutation(Folder):
    def write(self, name, survivors, date):
        result = {"module": name, "total": 100, "survivors": survivors, "date": date, "commit": "a"}
        (Path(self.folder) / f"{name}.json").write_text(json.dumps(result), encoding="utf-8")

    def test_no_survivors_is_green_and_shows_the_oldest_run(self):
        self.write("a", 0, "2026-11-20")
        self.write("b", 0, "2026-11-18")
        badge = badges.mutation_badge(self.folder)
        self.assertEqual(badge["message"], "0 survivors, 2 modules, 2026-11-18")
        self.assertEqual((badge["label"], badge["color"]), ("mutation", "brightgreen"))

    def test_a_survivor_is_red_and_counted_in_the_singular(self):
        self.write("a", 1, "2026-11-20")
        badge = badges.mutation_badge(self.folder)
        self.assertEqual((badge["message"], badge["color"]), ("1 survivor, 1 module, 2026-11-20", "red"))

    def test_survivors_of_every_module_are_added_up(self):
        self.write("a", 2, "2026-11-20")
        self.write("b", 3, "2026-11-20")
        self.assertIn("5 survivors", badges.mutation_badge(self.folder)["message"])

    def test_no_results_is_an_error(self):
        with self.assertRaisesRegex(SystemExit, "no results"):
            badges.mutation_badge(self.folder)


class Command(Folder):
    def arguments(self, out):
        report = write_coverage(self.folder, "a.json", 4, 4)
        write_junit(self.folder, "a.xml", 2)
        return ["--coverage", str(report), "--junit", self.folder, "--out", str(out)]

    def test_both_badges_are_written(self):
        out = Path(self.folder) / "out" / "badges"
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = badges.main(self.arguments(out))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((out / "coverage.json").read_text())["message"], "100%")
        self.assertEqual(json.loads((out / "scenarios.json").read_text())["message"], "2 passing")
        self.assertIn("scenarios.json: scenarios 2 passing", printed.getvalue())

    def test_running_the_file_exits_with_the_status(self):
        argv = ["badges.py", *self.arguments(Path(self.folder) / "o")]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(HERE / "badges.py"), run_name="__main__")
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
