"""Offline tests for complexity_report.py. Run: python tools/test_complexity_report.py"""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import complexity_report as cr

LIMITS = {"cyclomatic": 6, "cognitive": 10}
ROOT = Path(".")


def ruff(path, name, score, code="C901"):
    return {"code": code, "filename": path, "message": f"`{name}` is too complex ({score} > 0)"}


def complexipy(path, name, score):
    return {"path": path, "function_name": name, "complexity": score}


def eslint(path, *messages):
    return {"filePath": path, "messages": list(messages)}


def cyclomatic(line, score, kind="Function 'f'"):
    return {
        "ruleId": "complexity",
        "line": line,
        "message": f"{kind} has a complexity of {score}. Maximum allowed is 0.",
    }


def cognitive(line, score):
    message = f"Refactor this function to reduce its Cognitive Complexity from {score} to the 0 allowed."
    return {"ruleId": "sonarjs/cognitive-complexity", "line": line, "message": message}


class Python(unittest.TestCase):
    def test_the_two_tools_are_joined_on_file_and_name(self):
        table = cr.python_scores(
            [ruff("a.py", "f", 3), ruff("a.py", "g", 1)],
            [complexipy("a.py", "f", 5), complexipy("a.py", "h", 2)],
            ROOT,
        )
        self.assertEqual(
            table,
            {
                ("a.py", "f"): {"cyclomatic": 3, "cognitive": 5},
                ("a.py", "g"): {"cyclomatic": 1, "cognitive": 0},
                ("a.py", "h"): {"cyclomatic": 0, "cognitive": 2},
            },
        )

    def test_a_method_is_matched_on_its_bare_name_and_a_shared_name_keeps_the_highest(self):
        table = cr.python_scores(
            [ruff("t.py", "entities", 1), ruff("t.py", "entities", 4)],
            [complexipy("t.py", "A::entities", 3), complexipy("t.py", "B::entities", 2)],
            ROOT,
        )
        self.assertEqual(table, {("t.py", "entities"): {"cyclomatic": 4, "cognitive": 3}})

    def test_other_ruff_findings_and_other_messages_are_ignored(self):
        findings = [ruff("a.py", "f", 9, code="E501"), {"code": "C901", "filename": "a.py", "message": "odd"}, {}]
        self.assertEqual(cr.python_scores(findings, [], ROOT), {})

    def test_the_same_file_named_three_ways_is_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            inside = root / "pkg" / "m.py"
            inside.write_text("", encoding="utf-8")
            table = cr.python_scores(
                [ruff(str(inside), "f", 2)],
                [complexipy("\\\\?\\" + str(inside), "f", 3), complexipy("pkg\\m.py", "g", 1)],
                root,
            )
        self.assertEqual(set(table), {("pkg/m.py", "f"), ("pkg/m.py", "g")})
        self.assertEqual(table["pkg/m.py", "f"], {"cyclomatic": 2, "cognitive": 3})

    def test_a_file_outside_the_root_keeps_its_whole_path(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            outside = Path(other).resolve() / "x.py"
            self.assertEqual(cr.relative(str(outside), Path(tmp)), outside.as_posix())


class JavaScript(unittest.TestCase):
    def test_both_measures_are_joined_on_the_line(self):
        table = cr.javascript_scores(
            [eslint("p.js", cyclomatic(4, 3, "Function 'esc'"), cognitive(4, 2), cyclomatic(9, 1, "Arrow function"))],
            ROOT,
        )
        self.assertEqual(
            table,
            {
                ("p.js", "esc (line 4)"): {"cyclomatic": 3, "cognitive": 2},
                ("p.js", "arrow function (line 9)"): {"cyclomatic": 1, "cognitive": 0},
            },
        )

    def test_a_cognitive_score_with_no_cyclomatic_one_still_counts(self):
        table = cr.javascript_scores([eslint("p.js", cognitive(7, 5))], ROOT)
        self.assertEqual(table, {("p.js", "function (line 7)"): {"cyclomatic": 0, "cognitive": 5}})

    def test_methods_and_other_rules_and_odd_messages(self):
        messages = [
            cyclomatic(2, 2, "Method 'render'"),
            {"ruleId": "no-var", "line": 3, "message": "Unexpected var."},
            {"ruleId": "complexity", "line": 5, "message": "something else"},
            {"ruleId": None, "line": 6},
        ]
        self.assertEqual(
            cr.javascript_scores([eslint("p.js", *messages)], ROOT),
            {("p.js", "render (line 2)"): {"cyclomatic": 2, "cognitive": 0}},
        )


class Report(unittest.TestCase):
    def table(self):
        return {
            ("a.py", "calm"): {"cyclomatic": 1, "cognitive": 0},
            ("a.py", "busy"): {"cyclomatic": 6, "cognitive": 3},
            ("b.py", "deep"): {"cyclomatic": 2, "cognitive": 9},
        }

    def test_the_summary_has_the_count_the_means_the_highest_and_how_many_are_at_a_limit(self):
        self.assertEqual(cr.summary_row("Python", self.table(), LIMITS), "| Python | 3 | 3.0 / 6 | 4.0 / 9 | 1 |")

    def test_an_empty_table_is_a_row_of_zeros(self):
        self.assertEqual(cr.summary_row("JavaScript", {}, LIMITS), "| JavaScript | 0 | - | - | 0 |")

    def test_the_closest_come_first_by_their_higher_share_of_either_limit(self):
        rows = cr.closest("Python", self.table(), LIMITS)
        self.assertEqual(
            rows,
            [
                "| Python | `busy` | `a.py` | 6 | 3 |",
                "| Python | `deep` | `b.py` | 2 | 9 |",
                "| Python | `calm` | `a.py` | 1 | 0 |",
            ],
        )

    def test_ties_are_ordered_by_file_and_name_and_only_the_top_ones_are_shown(self):
        table = {(f"f{n:02}.py", "x"): {"cyclomatic": 3, "cognitive": 0} for n in range(cr.SHOWN + 5)}
        rows = cr.closest("Python", table, LIMITS)
        self.assertEqual(len(rows), cr.SHOWN)
        self.assertEqual(rows[0], "| Python | `x` | `f00.py` | 3 | 0 |")

    def test_a_pipe_or_a_backtick_in_a_path_cannot_break_the_table(self):
        table = {("odd|name`.py", "f"): {"cyclomatic": 1, "cognitive": 1}}
        (row,) = cr.closest("Python", table, LIMITS)
        self.assertEqual(row, "| Python | `f` | `odd\\|name'.py` | 1 | 1 |")
        self.assertEqual(row.replace("\\|", "").count("|"), 6)

    def test_the_whole_report(self):
        lines = cr.report({"Python": self.table(), "JavaScript": {}}, LIMITS)
        self.assertEqual(lines[0], "## Complexity")
        self.assertIn("Limits: cyclomatic 6, cognitive 10. CI fails on a function over either one.", lines)
        self.assertIn("| Python | 3 | 3.0 / 6 | 4.0 / 9 | 1 |", lines)
        self.assertIn("| JavaScript | 0 | - | - | 0 |", lines)
        self.assertEqual(lines[-1], "| Python | `calm` | `a.py` | 1 | 0 |")


class CommandLine(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cr.main(argv)
        return code, out.getvalue()

    def files(self, folder, ruff_data, complexipy_data, eslint_data):
        paths = []
        for name, data in (("r.json", ruff_data), ("c.json", complexipy_data), ("e.json", eslint_data)):
            (folder / name).write_text(json.dumps(data), encoding="utf-8")
            paths.append(str(folder / name))
        return ["--ruff", paths[0], "--complexipy", paths[1], "--eslint", paths[2]]

    def test_prints_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.files(Path(tmp), [ruff("a.py", "f", 2)], [complexipy("a.py", "f", 1)], [])
            code, out = self.run_main([*args, "--cyclomatic-limit", "6", "--cognitive-limit", "10"])
        self.assertEqual(code, 0)
        self.assertIn("| Python | 1 | 2.0 / 2 | 1.0 / 1 | 0 |", out)
        self.assertIn("| JavaScript | 0 | - | - | 0 |", out)

    def test_a_missing_or_broken_file_is_an_error_not_an_empty_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.files(Path(tmp), [], [], [])
            (Path(tmp) / "c.json").write_text("{not json", encoding="utf-8")
            limits = ["--cyclomatic-limit", "6", "--cognitive-limit", "10"]
            with self.assertRaisesRegex(SystemExit, "can't read .*c.json"):
                self.run_main([*args, *limits])
            args[3] = str(Path(tmp) / "missing.json")
            with self.assertRaisesRegex(SystemExit, "can't read .*missing.json"):
                self.run_main([*args, *limits])

    def test_a_limit_must_be_a_whole_number_of_1_or_more(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.files(Path(tmp), [], [], [])
            for bad in ("0", "-3", "six"):
                with self.subTest(bad), contextlib.redirect_stderr(io.StringIO()) as err:
                    with self.assertRaises(SystemExit):
                        cr.main([*args, "--cyclomatic-limit", bad, "--cognitive-limit", "10"])
                    self.assertIn("--cyclomatic-limit", err.getvalue())

    def test_runs_as_a_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.files(Path(tmp), [], [], [])
            argv = ["complexity_report.py", *args, "--cyclomatic-limit", "6", "--cognitive-limit", "10"]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertRaises(SystemExit) as stop:
                    runpy.run_path(cr.__file__, run_name="__main__")
        self.assertEqual(stop.exception.code, 0)
        self.assertIn("## Complexity", out.getvalue())


if __name__ == "__main__":
    unittest.main()
