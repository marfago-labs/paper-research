"""Tests for the hand check of the labels. Run: python evals/dedup/test_hand_check.py"""

import contextlib
import io
import json
import random
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hand_check as hc


def answer(first, second, same):
    probabilities = {"same_thing": same, "different_thing": 1 - same, "not_a_name": 0.0}
    return {"type": "tool", "first": first, "second": second, "probabilities": probabilities}


def answers(per_band=3):
    """per_band answers in each of the five bands, keyed like audit_labels.load."""
    found = {}
    for band, (low, _) in enumerate(hc.BANDS):
        for number in range(per_band):
            row = answer(f"First{band}", f"Second{band}.{number}", low + 0.01 * (number + 1))
            found[("tool", row["first"], row["second"])] = row
    return found


def pair(kind, first, second, label="same", aliases=()):
    return {
        "kind": kind,
        "label": label,
        "type": "tool",
        "split": "dev",
        "source": "wikidata",
        "existing": {"gold": "a", "name": first, "aliases": list(aliases), "ids": {}},
        "new": {"gold": "b", "name": second, "ids": {}},
    }


def pairs(per_kind=3):
    rows = []
    for kind in (*hc.JUDGED_KINDS, "same name", "alias collision", "messy"):
        label = "different" if kind in ("look-alike", "same name", "alias collision") else "same"
        rows += [pair(kind, f"{kind} {n}", f"{kind} {n} b", label, ["alias"]) for n in range(per_kind)]
    return rows


class Drawing(unittest.TestCase):
    def test_bands_hold_every_probability_including_one(self):
        self.assertEqual([hc.band_of(p) for p in (0.0, 0.19, 0.2, 0.55, 0.99, 1.0)], [0, 0, 1, 2, 4, 4])

    def test_draw_audit_takes_per_band_from_each_band(self):
        with mock.patch.object(hc, "PER_BAND", 2):
            found = hc.draw_audit(answers(3), random.Random(1))
        self.assertEqual(len(found), 10)
        self.assertEqual(
            sorted(hc.band_of(row["probabilities"]["same_thing"]) for row in found), [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
        )
        short = hc.draw_audit(answers(1), random.Random(1))  # a band with fewer gives all it has
        self.assertEqual(len(short), 5)

    def test_draw_pairs_takes_only_the_kinds_a_person_can_judge(self):
        with mock.patch.object(hc, "PER_KIND", 2):
            found = hc.draw_pairs(pairs(3), random.Random(1))
        self.assertEqual(len(found), 8)
        self.assertEqual({row["kind"] for row in found}, set(hc.JUDGED_KINDS))
        self.assertEqual(len(hc.draw_pairs(pairs(1), random.Random(1))), 4)

    def test_entries_are_numbered_in_a_shuffled_order_and_judge_a_name_pair_once(self):
        known = answers(3)
        same_pair = pair("similar name", "First0", "Second0.0")  # also one of the answers of Jev's
        with mock.patch.object(hc, "PER_BAND", 3), mock.patch.object(hc, "PER_KIND", 3):
            entries = hc.make_entries(known, pairs(3) + [same_pair], random.Random(2))
        sheet = [row for row, _ in entries]
        self.assertEqual([row["id"] for row in sheet], list(range(1, len(sheet) + 1)))
        self.assertEqual([key["id"] for _, key in entries], list(range(1, len(sheet) + 1)))
        names = [(row["first_name"], row["second_name"]) for row in sheet]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(sheet), 15 + 12)
        parts = {key["part"] for _, key in entries}
        self.assertEqual(parts, {"audit", "pair"})

    def test_entries_show_names_only_and_keep_the_rest_in_the_key(self):
        sheet, key = hc.pair_entry(pair("known alias", "Apache Airflow", "Airflow", aliases=["Airflow", "AF"]), 7, {})
        self.assertEqual(set(sheet), {"id", "type", "first_name", "second_name"})  # no aliases: they hold the answer
        self.assertEqual((key["kind"], key["label"], key["jev_same"]), ("known alias", "same", ""))
        known = {("tool", "Apache Airflow", "Airflow"): answer("Apache Airflow", "Airflow", 0.7)}
        self.assertEqual(hc.pair_entry(pair("known alias", "Apache Airflow", "Airflow"), 7, known)[1]["jev_same"], 0.7)
        sheet, key = hc.audit_entry(answer("A", "B", 0.35), 3)
        self.assertEqual((sheet["second_name"], key["part"], key["band"]), ("B", "audit", 1))


class Scoring(unittest.TestCase):
    def files(self, verdicts, keys, claude=()):
        folder = Path(tempfile.mkdtemp())
        claude = list(claude) + [""] * (len(verdicts) - len(claude))
        sheet = [
            {
                "id": i,
                "type": "tool",
                "first_name": "a",
                "second_name": "b",
                "claude_verdict": c,
                "your_verdict": v,
                "notes": "",
            }
            for i, (v, c) in enumerate(zip(verdicts, claude), start=1)
        ]
        hc.write_csv(folder / "sheet.csv", hc.SHEET_FIELDS, sheet)
        hc.write_csv(folder / "key.csv", hc.KEY_FIELDS, keys)
        return folder / "sheet.csv", folder / "key.csv"

    def audit_key(self, number, band, same):
        return {"id": number, "part": "audit", "kind": "", "label": "", "jev_same": same, "band": band}

    def pair_key(self, number, kind, label):
        return {"id": number, "part": "pair", "kind": kind, "label": label, "jev_same": "", "band": ""}

    def test_make_writes_a_sheet_and_a_key_that_score_reads_back(self):
        folder = Path(tempfile.mkdtemp())
        audit = folder / "audit.jsonl"
        audit.write_text("".join(json.dumps(r) + "\n" for r in answers(3).values()), encoding="utf-8")
        pairs_file = folder / "pairs.jsonl"
        pairs_file.write_text("".join(json.dumps(r) + "\n" for r in pairs(3)), encoding="utf-8")
        with mock.patch.object(hc, "PER_BAND", 2), mock.patch.object(hc, "PER_KIND", 2):
            count = hc.make(5, folder / "sheet.csv", folder / "key" / "key.csv", audit, pairs_file)
        self.assertEqual(count, 18)
        rows = hc.read_csv(folder / "sheet.csv")
        self.assertEqual(len(rows), 18)
        self.assertEqual((rows[0]["claude_verdict"], rows[0]["your_verdict"]), ("", ""))
        self.assertEqual(hc.score(folder / "sheet.csv", folder / "key" / "key.csv")["judged"], 0)

    def test_score_reads_verdicts_and_counts_the_disagreements(self):
        verdicts = ["same", "different", "Same ", "unsure", "same", "different", ""]
        keys = [
            self.audit_key(1, 0, 0.1),  # a name Jev would remove, judged the same thing by hand
            self.audit_key(2, 0, 0.1),
            self.audit_key(3, 1, 0.3),
            self.audit_key(4, 1, 0.3),  # unsure: counts for neither
            self.pair_key(5, "look-alike", "different"),  # the person says same: the label is wrong
            self.pair_key(6, "look-alike", "different"),
            self.pair_key(7, "known alias", "same"),  # no verdict yet
        ]
        found = hc.score(*self.files(verdicts, keys))
        self.assertEqual((found["judged"], found["unsure"]), (6, 1))
        self.assertEqual(found["decided by"], {"person": 6, "person, overriding Claude": 0, "Claude only": 0})
        bands = found["same thing by hand, by band of Jev's P(same thing)"]
        self.assertEqual((bands["0.0-0.2"]["bad"], bands["0.0-0.2"]["total"]), (1, 2))
        self.assertEqual((bands["0.2-0.4"]["bad"], bands["0.2-0.4"]["total"]), (1, 1))
        errors = found["label disagrees with the person, by kind"]
        self.assertEqual((errors["look-alike"]["bad"], errors["look-alike"]["total"]), (1, 2))
        self.assertNotIn("known alias", errors)
        self.assertEqual(found["MAX_SAME now"], 0.2)

    def test_the_persons_verdict_overrides_claudes(self):
        keys = [self.pair_key(i, "look-alike", "different") for i in range(1, 5)]
        found = hc.score(*self.files(["", "same", "OK", ""], keys, claude=["different", "different", "different"]))
        self.assertEqual(found["decided by"], {"person": 1, "person, overriding Claude": 1, "Claude only": 1})
        errors = found["label disagrees with the person, by kind"]["look-alike"]
        self.assertEqual((errors["bad"], errors["total"]), (1, 3))  # row 2: the person's same wins; row 4: no verdict

    def test_a_verdict_that_is_not_one_of_the_three_is_an_error(self):
        with self.assertRaises(ValueError) as raised:
            hc.score(*self.files(["yes"], [self.audit_key(1, 0, 0.1)]))
        self.assertIn("row 1", str(raised.exception))
        with self.assertRaises(ValueError) as raised:
            hc.score(*self.files([""], [self.audit_key(1, 0, 0.1)], claude=["maybe"]))
        self.assertIn("claude_verdict", str(raised.exception))
        with self.assertRaises(ValueError) as raised:
            hc.score(*self.files(["ok"], [self.audit_key(1, 0, 0.1)]))  # ok, but Claude gave no verdict
        self.assertIn("no claude_verdict", str(raised.exception))

    def test_suggest_the_highest_threshold_at_which_the_removed_names_were_different(self):
        def bands(*counts):
            return {
                f"band{index}": {"bad": same, "total": total, "upper": 0.2 * (index + 1)}
                for index, (same, total) in enumerate(counts)
            }

        self.assertEqual(hc.suggest(bands((0, 20), (1, 20), (6, 20), (10, 20), (20, 20))), 0.4)  # 1 of 40 is the same
        self.assertIsNone(hc.suggest(bands((10, 20), (0, 20))))  # the lowest band already has too many
        self.assertIsNone(hc.suggest({}))
        self.assertEqual(hc.rate(0, 0)["rate"], None)
        self.assertEqual(hc.rate(1, 4)["rate"], 0.25)


class Running(unittest.TestCase):
    def test_main_makes_scores_and_explains(self):
        folder = Path(tempfile.mkdtemp())
        sheet, key = folder / "sheet.csv", folder / "key.csv"
        hc.write_csv(sheet, hc.SHEET_FIELDS, [])
        hc.write_csv(key, hc.KEY_FIELDS, [])
        with mock.patch.object(hc, "make", return_value=200) as made, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(hc.main(["make"]), 0)
            self.assertEqual(hc.main(["make", "--seed", "9"]), 0)
        self.assertEqual([call.args[0] for call in made.call_args_list], [hc.SEED, 9])
        self.assertIn("wrote 200 rows", out.getvalue())
        with mock.patch.object(hc, "KEY", key), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(hc.main(["score", str(sheet)]), 0)
        self.assertEqual(json.loads(out.getvalue())["judged"], 0)
        with mock.patch.object(hc, "SHEET", sheet), mock.patch.object(hc, "KEY", key):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(hc.main(["score"]), 0)  # the default sheet
        with contextlib.redirect_stderr(io.StringIO()) as said:
            self.assertEqual(hc.main(["nothing"]), 2)
        self.assertIn("hand check", said.getvalue())
        with mock.patch.object(sys, "argv", ["hand_check.py"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(Path(hc.__file__)), run_name="__main__")
        self.assertEqual(raised.exception.code, 2)
        with mock.patch.object(sys, "argv", ["hand_check.py"]), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(hc.main(), 2)  # arguments from the command line


if __name__ == "__main__":
    unittest.main()
