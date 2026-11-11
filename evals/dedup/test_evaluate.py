"""Tests for the pair evaluation. Run: python evals/dedup/test_evaluate.py"""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import evaluate as ev

import graph


def side(name, aliases=(), ids=None, gold="g"):
    return {"gold": gold, "name": name, "aliases": list(aliases), "ids": ids or {}}


def pair(kind, label, existing, new, split="dev", **extra):
    row = {"kind": kind, "label": label, "type": "tool", "source": "wikidata", "split": split}
    return {**row, **extra, "existing": existing, "new": {k: v for k, v in new.items() if k != "aliases"}}


def pairs():
    """One of each kind, with the outcome that graph.py gives each."""
    return [
        pair("same name", "different", side("Jing Chen", ids={"orcid": "1"}), side("Jing Chen", ids={"orcid": "2"})),
        pair("alias collision", "different", side("Jie S. Li", ["Jie Li"]), side("Jie Li")),
        pair("known alias", "same", side("Apache Airflow", ["Airflow"]), side("Airflow")),
        pair("look-alike", "different", side("Llama-3.2-1B"), side("Llama-3.2-1B-Instruct")),
        pair("look-alike", "different", side("Zorbit"), side("Quentra")),
        pair("similar name", "same", side("GPT-3"), side("GPT 3.5")),
        pair("messy", "same", side("Zorbit"), side("zorbit "), messy="case"),
        pair("dissimilar name", "same", side("Emotional Speech Database"), side("ESD")),
        pair("similar name", "same", side("Zorbit", ids={"github": "a/b"}), side("Zorbit Net", ids={"github": "A/B"})),
    ]


class Statistics(unittest.TestCase):
    def test_wilson_interval_and_cell(self):
        self.assertIsNone(ev.wilson(0, 0))
        low, high = ev.wilson(0, 5)
        self.assertEqual(low, 0.0)
        self.assertAlmostEqual(high, 0.4344, places=3)  # no errors in five still allows a large rate
        self.assertEqual(ev.wilson(5, 5)[1], 1.0)
        low, high = ev.wilson(50, 100)
        self.assertAlmostEqual(low, 0.4038, places=3)
        self.assertAlmostEqual(high, 0.5962, places=3)
        self.assertEqual(ev.cell(0, 0), "-")
        self.assertEqual(ev.cell(1, 4), "0.250 (0.046-0.699) 1/4")

    def test_kind_of_names_the_change_of_a_messy_pair(self):
        self.assertEqual(ev.kind_of({"kind": "messy", "messy": "dash"}), "messy: dash")
        self.assertEqual(ev.kind_of({"kind": "look-alike"}), "look-alike")


class Outcomes(unittest.TestCase):
    def prepared(self, existing, new, ids):
        one = pair("x", "same", existing, new)
        return ev.prepare(one, ids)

    def test_prepare_separates_what_decides_a_pair_from_the_settings(self):
        shared = self.prepared(side("A", ids={"github": "a/b"}), side("Other", ids={"github": "A/B"}), True)
        self.assertTrue(shared["strong"])  # a shared id is strong, whatever the names
        self.assertFalse(
            self.prepared(side("A", ids={"github": "a/b"}), side("Other", ids={"github": "a/b"}), False)["held"]
        )
        same = self.prepared(side("Jing Chen", ids={"orcid": "1"}), side("jing-chen", ids={"orcid": "2"}), True)
        self.assertEqual((same["strong"], same["held"]), (False, True))  # conflicting ids: asked, not refused
        self.assertTrue(self.prepared(side("Jing Chen"), side("Jing Chen"), False)["strong"])
        alias = self.prepared(side("Apache Airflow", ["Airflow"]), side("Airflow"), True)
        self.assertEqual((alias["strong"], alias["held"], alias["alias"]), (False, True, True))
        clash = self.prepared(side("X", ["Airflow"], {"orcid": "1"}), side("Airflow", ids={"orcid": "2"}), True)
        self.assertFalse(clash["alias"])  # the alias rule does not override conflicting ids
        none = self.prepared(side("Zorbit"), side("Quentra"), True)
        self.assertEqual((none["strong"], none["held"], none["alias"]), (False, False, False))
        self.assertEqual(graph.SIMILARITY, 0.5)  # the override is undone

    def test_outcome_by_threshold_and_alias_rule(self):
        near = {"strong": False, "held": False, "alias": False, "score": 0.6}
        self.assertEqual([ev.outcome(near, t, "ask") for t in (0.5, 0.6, 0.7)], ["ask", "ask", "add"])
        alias = {"strong": False, "held": True, "alias": True, "score": 0.0}
        self.assertEqual((ev.outcome(alias, 0.5, "ask"), ev.outcome(alias, 0.5, "refuse")), ("ask", "refuse"))
        held = {"strong": False, "held": True, "alias": False, "score": 0.0}
        self.assertEqual(ev.outcome(held, 0.9, "refuse"), "ask")  # only an alias match is refused by the rule
        self.assertEqual(ev.outcome({**near, "strong": True}, 0.9, "ask"), "refuse")

    def test_the_override_is_undone_even_when_the_check_fails(self):
        with self.assertRaises(ZeroDivisionError):
            with ev.similarity_threshold(0.9):
                self.assertEqual(graph.SIMILARITY, 0.9)
                raise ZeroDivisionError
        self.assertEqual(graph.SIMILARITY, 0.5)


class Reports(unittest.TestCase):
    def test_rates_count_each_bad_outcome_over_the_pairs_it_can_happen_to(self):
        rows = pairs()
        outcomes = [ev.outcome(ev.prepare(row, False), 0.5, "ask") for row in rows]
        found = ev.rates(ev.tally(rows, outcomes, lambda row: "all")["all"])
        self.assertEqual(found["wrong merges"], (1, 4))  # the same-name pair, with names only
        self.assertEqual(found["needless asks"][1], 4)
        self.assertEqual(found["missed duplicates"][1], 5)

    def test_tables_have_a_row_per_kind_and_per_kind_and_type(self):
        rows = pairs()
        outcomes = ev.replay(rows, [(0.5, "ask")])["names only"][(0.5, "ask")]
        text = ev.table(ev.by_kind(rows, outcomes), "kind")
        self.assertIn("| alias collision | 1 | - | 0.000 (0.000-0.793) 0/1 | 1.000 (0.207-1.000) 1/1 |", text)
        self.assertIn("| messy: case | 1 |", text)
        self.assertIn("| look-alike / tool | 2 |", ev.table(ev.by_kind_and_type(rows, outcomes), "kind / type"))

    def test_the_ids_run_and_the_names_only_run_differ_on_ids(self):
        rows = pairs()[:1] + pairs()[-1:]
        results = ev.replay(rows, [(0.5, "ask")])
        self.assertEqual(results["ids"][(0.5, "ask")], ["ask", "refuse"])  # orcids conflict; the same repository
        self.assertEqual(results["names only"][(0.5, "ask")], ["refuse", "ask"])

    def test_changes_list_the_pairs_whose_outcome_changed(self):
        rows = pairs()
        settings = ev.settings_of([0.5], ["ask", "refuse"])
        results = ev.replay(rows, settings)["names only"]
        text = ev.report_changes(rows, results, "names only", settings[0], settings[1])
        self.assertIn("2 pairs changed", text)  # the alias pair and the alias collision
        self.assertIn("| known alias | same | ask | refuse | 1 | Apache Airflow -> Airflow |", text)
        same = ev.report_changes(rows, results, "names only", settings[0], settings[0])
        self.assertIn("0 pairs changed", same)
        self.assertTrue(same.endswith("None."))
        self.assertEqual(ev.settings_of([0.5, 0.6], ["ask"]), [(0.5, "ask"), (0.6, "ask")])

    def test_build_report_covers_every_run_and_setting(self):
        settings = ev.settings_of([0.5, 0.6], ["ask"])
        text, data = ev.build_report(pairs(), settings, "dev")
        for expected in (
            "## Duplicate detection, dev split",
            "### ids, threshold 0.5, alias rule ask",
            "### names only, threshold 0.6, alias rule ask",
            "threshold 0.5, alias rule ask to threshold 0.6",
        ):
            self.assertIn(expected, text)
        self.assertEqual(data["pairs"], 9)
        self.assertEqual(
            sorted(data["settings"]["ids, threshold 0.5, alias rule ask"]["alias collision"]),
            ["missed duplicates", "needless asks", "wrong merges"],
        )


class Sweep(unittest.TestCase):
    def points(self, missed):
        return [{"threshold": t, "missed": m, "needless": (0, 1)} for t, m in missed]

    def test_curve_covers_the_sweep_and_counts_only_its_kinds(self):
        rows = pairs()
        found = ev.curve(rows, [ev.prepare(row, False) for row in rows])
        self.assertEqual([point["threshold"] for point in found], ev.SWEEP)
        self.assertEqual(ev.SWEEP[0], 0.3)
        self.assertEqual(ev.SWEEP[-1], 0.9)
        self.assertEqual(found[0]["missed"][1], 2)  # similar-name pairs
        self.assertEqual(found[0]["needless"][1], 2)  # look-alike pairs

    def test_choose_takes_the_highest_threshold_within_the_limit(self):
        points = self.points([(0.3, (0, 100)), (0.4, (4, 100)), (0.5, (6, 100)), (0.6, (0, 0))])
        self.assertEqual(ev.choose(points, 0.05), 0.4)  # a threshold with no pairs to count is not chosen
        self.assertIsNone(ev.choose(self.points([(0.3, (50, 100))]), 0.05))
        self.assertIsNone(ev.choose([], 0.05))

    def test_sweep_report_says_which_threshold_dev_chose(self):
        rows = pairs()
        text, data = ev.sweep_report({"dev": rows, "test": rows}, 1.0)
        self.assertIn("### Threshold sweep, dev, names only", text)
        self.assertIn("### Threshold sweep, test, names only", text)
        self.assertEqual(data["chosen on dev"], 0.9)
        self.assertIn("is 0.90.", text)
        self.assertIn("(chosen on dev)", text)
        text, data = ev.sweep_report({"dev": rows}, -1.0)  # a limit nothing can meet
        self.assertIn("is none of them.", text)
        self.assertIsNone(data["chosen on dev"])
        text, data = ev.sweep_report({"test": rows}, 0.05)  # without dev there is nothing to choose from
        self.assertIsNone(data["chosen on dev"])


class Running(unittest.TestCase):
    def folder(self):
        folder = Path(tempfile.mkdtemp())
        rows = pairs() + [{**row, "split": "test"} for row in pairs()[:3]]
        (folder / "pairs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "\n", encoding="utf-8")
        return folder

    def run_main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = ev.main([str(a) for a in args])
        return code, printed.getvalue()

    def test_main_reports_one_split_and_writes_the_summary_and_json(self):
        folder = self.folder()
        code, printed = self.run_main(
            "--pairs",
            folder / "pairs.jsonl",
            "--summary",
            folder / "s.md",
            "--json",
            folder / "r.json",
            "--sweep",
            "--threshold",
            0.5,
            0.6,
        )
        self.assertEqual(code, 0)
        self.assertIn("9 pairs.", printed)
        self.assertEqual((folder / "s.md").read_text(encoding="utf-8").strip(), printed.strip())
        data = json.loads((folder / "r.json").read_text(encoding="utf-8"))
        self.assertEqual((data["split"], data["pairs"]), ("dev", 9))
        self.assertIn("chosen on dev", data["sweep"])
        code, printed = self.run_main("--pairs", folder / "pairs.jsonl", "--split", "test")
        self.assertIn("3 pairs.", printed)
        self.assertNotIn("sweep", printed)

    def test_main_uses_the_current_threshold_by_default_and_says_when_pairs_are_missing(self):
        folder = self.folder()
        _, printed = self.run_main("--pairs", folder / "pairs.jsonl")
        self.assertIn(f"threshold {graph.SIMILARITY}, alias rule ask", printed)
        with contextlib.redirect_stderr(io.StringIO()) as said:
            code = ev.main(["--pairs", str(folder / "none.jsonl")])
        self.assertEqual(code, 2)
        self.assertIn("no pairs at", said.getvalue())

    def test_the_committed_pairs_load(self):
        found = ev.load_pairs(ev.PAIRS)
        self.assertEqual({row["split"] for row in found}, {"dev", "test"})

    def test_runs_as_a_script(self):
        folder = self.folder()
        argv = ["evaluate.py", "--pairs", str(folder / "pairs.jsonl")]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(Path(ev.__file__)), run_name="__main__")
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
