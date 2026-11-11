"""Tests for the label audit, with the network mocked. Run: python evals/dedup/test_audit_labels.py"""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import audit_labels as audit

ANSWER = {
    "id": "gen-dec-1",
    "model": "typesafe/jev-1.14-20261014",
    "answers": {
        "relation": {
            "type": "choice",
            "choice": "different_thing",
            "confidence": 0.88,
            "probabilities": {"same_thing": 0.08, "different_thing": 0.9, "not_a_name": 0.02},
        }
    },
    "usage": {"input_tokens": 300, "output_tokens": 10, "cost": 0.00002},
}


def response(body):
    opened = mock.MagicMock()
    opened.__enter__.return_value = io.BytesIO(json.dumps(body).encode())
    return opened


def failure(code):
    return urllib.error.HTTPError("u", code, "busy", {}, None)  # type: ignore[arg-type]


def row(second, same=0.5, cost=0.001, model="m"):
    probabilities = {"same_thing": same, "different_thing": 1 - same, "not_a_name": 0.0}
    return {
        "type": "tool",
        "first": "A",
        "second": second,
        "verdict": "same_thing",
        "confidence": 0.5,
        "probabilities": probabilities,
        "model": model,
        "input_tokens": 100,
        "output_tokens": 5,
        "cost": cost,
    }


def write(path, rows):
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class Request(unittest.TestCase):
    def test_the_request_carries_the_pair_the_question_and_the_key(self):
        request = audit.request_for("model", "OpenAI o1", "o1-preview", "sk-secret", audit.MODEL)
        body = json.loads(request.data)
        self.assertEqual(request.full_url, audit.ENDPOINT)
        self.assertEqual(request.headers["Authorization"], "Bearer sk-secret")
        self.assertEqual(body["model"], "typesafe/jev-1.14")
        self.assertEqual(
            body["state"], {"entity type": "model", "first name": "OpenAI o1", "second name": "o1-preview"}
        )
        question = body["questions"]["relation"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(sorted(question["criteria"]), ["different_thing", "not_a_name", "same_thing"])

    def test_decide_reads_the_choice_probabilities_snapshot_tokens_and_cost(self):
        with mock.patch("urllib.request.urlopen", return_value=response(ANSWER)):
            found = audit.decide("model", "OpenAI o1", "o1-preview", "k")
        self.assertEqual(found["verdict"], "different_thing")
        self.assertEqual(found["probabilities"]["same_thing"], 0.08)
        self.assertEqual((found["model"], found["cost"]), ("typesafe/jev-1.14-20261014", 0.00002))
        self.assertEqual((found["input_tokens"], found["output_tokens"]), (300, 10))
        self.assertNotIn("k", found)  # the key is never part of a row
        free = {**ANSWER, "usage": None}
        with mock.patch("urllib.request.urlopen", return_value=response(free)):
            found = audit.decide("model", "a", "b", "k")
        self.assertEqual((found["input_tokens"], found["output_tokens"], found["cost"]), (None, None, None))
        self.assertEqual(
            audit.usage_of({"usage": {"cost": 1}}), {"input_tokens": None, "output_tokens": None, "cost": 1}
        )

    def test_post_tries_again_when_busy_and_gives_up_on_other_errors(self):
        request = audit.request_for("tool", "a", "b", "k", audit.MODEL)
        with mock.patch("time.sleep") as slept:
            with mock.patch("urllib.request.urlopen", side_effect=[failure(503), failure(429), response(ANSWER)]):
                self.assertEqual(audit.post(request)["model"], ANSWER["model"])
            self.assertEqual(slept.call_count, 2)
            with mock.patch("urllib.request.urlopen", side_effect=[failure(401)]) as opened:
                with self.assertRaises(urllib.error.HTTPError):
                    audit.post(request)
            self.assertEqual(opened.call_count, 1)  # a refused key is not retried
            with mock.patch("urllib.request.urlopen", side_effect=[failure(502)] * audit.RETRIES):
                with self.assertRaises(urllib.error.HTTPError):
                    audit.post(request)


class Verdicts(unittest.TestCase):
    def test_rejected_only_when_jev_is_confident_it_is_not_the_same_thing(self):
        self.assertTrue(audit.rejected(row("x", same=0.05)))
        self.assertTrue(audit.rejected(row("x", same=audit.MAX_SAME)))  # at the limit
        self.assertFalse(audit.rejected(row("x", same=0.4)))  # unsure: a person decides
        self.assertFalse(audit.rejected(row("x", same=0.95)))
        self.assertFalse(audit.rejected(None))  # never asked
        self.assertTrue(audit.rejected({"probabilities": {"different_thing": 1.0}}))  # no same_thing at all

    def test_load_returns_the_rows_by_pair_and_nothing_when_there_is_no_file(self):
        folder = Path(tempfile.mkdtemp())
        self.assertEqual(audit.load(folder / "audit.jsonl"), {})
        (folder / "audit.jsonl").write_text(
            json.dumps(row("B")) + "\n\n" + json.dumps(row("C")) + "\n", encoding="utf-8"
        )
        self.assertEqual(sorted(audit.load(folder / "audit.jsonl")), [("tool", "A", "B"), ("tool", "A", "C")])


class Judging(unittest.TestCase):
    def test_judge_asks_only_what_is_missing_and_keeps_every_answer(self):
        path = Path(tempfile.mkdtemp()) / "data" / "audit.jsonl"
        path.parent.mkdir()
        write(path, [row("B")])
        pairs = [("tool", "A", "B"), ("tool", "A", "C"), ("tool", "A", "C"), ("tool", "A", "D")]
        asked_for = []

        def decide(entity_type, first, second, key, model):
            asked_for.append(second)
            if second == "D":
                raise failure(400)
            return row(second)

        with mock.patch.object(audit, "decide", side_effect=decide), contextlib.redirect_stdout(io.StringIO()):
            spent = audit.judge(pairs, path, "k", workers=1)
        self.assertEqual(sorted(asked_for), ["C", "D"])  # B was kept, C once
        self.assertEqual((spent["asked"], spent["skipped"], spent["not asked"]), (1, 1, 0))
        self.assertEqual((spent["input_tokens"], spent["output_tokens"]), (100, 5))
        self.assertAlmostEqual(spent["cost"], 0.001)
        self.assertEqual(sorted(audit.load(path)), [("tool", "A", "B"), ("tool", "A", "C")])  # D left for next time

    def test_judge_stops_asking_once_the_budget_is_spent_and_says_how_many_it_left(self):
        path = Path(tempfile.mkdtemp()) / "audit.jsonl"
        pairs = [("tool", "A", str(n)) for n in range(6)]
        with (
            mock.patch.object(audit, "CHUNK", 2),
            mock.patch.object(audit, "decide", side_effect=lambda t, f, s, k, m: row(s)),
        ):
            spent = audit.judge(pairs, path, "k", workers=1, max_cost=0.0015)
        self.assertEqual((spent["asked"], spent["not asked"]), (2, 4))  # two chunks would be 0.004: the first is 0.002
        self.assertEqual(len(audit.load(path)), 2)

    def test_attempt_skips_a_pair_the_service_refuses_or_garbles(self):
        for error in (failure(400), KeyError("answers"), ValueError("not json")):
            with mock.patch.object(audit, "decide", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(audit.attempt(("tool", "A", "B"), "k", audit.MODEL))
        with mock.patch.object(audit, "decide", return_value={"x": 1}):
            self.assertEqual(audit.attempt(("tool", "A", "B"), "k", audit.MODEL), {"x": 1})

    def test_judge_with_nothing_to_ask_makes_no_call(self):
        path = Path(tempfile.mkdtemp()) / "audit.jsonl"
        with mock.patch.object(audit, "decide") as decide:
            spent = audit.judge([], path, "k")
        decide.assert_not_called()
        self.assertEqual(
            spent, dict.fromkeys(("asked", "skipped", "not asked", "input_tokens", "output_tokens", "cost"), 0)
        )

    def test_a_missing_token_count_or_cost_counts_as_nothing(self):
        path = Path(tempfile.mkdtemp()) / "audit.jsonl"
        free = {**row("B"), "cost": None, "input_tokens": None, "output_tokens": None}
        with mock.patch.object(audit, "decide", return_value=free):
            spent = audit.judge([("tool", "A", "B")], path, "k", workers=1)
        self.assertEqual((spent["asked"], spent["input_tokens"], spent["cost"]), (1, 0, 0))

    def test_missing_and_estimate(self):
        known = {("tool", "A", "B"): row("B", cost=0.002), ("tool", "A", "C"): row("C", cost=0.004)}
        pairs = [("tool", "A", "B"), ("tool", "A", "D"), ("tool", "A", "D"), ("tool", "A", "E")]
        self.assertEqual(audit.missing(pairs, known), [("tool", "A", "D"), ("tool", "A", "E")])
        self.assertAlmostEqual(audit.estimate(2, known), 0.006)  # twice the mean of 0.002 and 0.004
        self.assertIsNone(audit.estimate(2, {}))  # nothing to go by
        self.assertIsNone(audit.estimate(2, {("tool", "A", "B"): {**row("B"), "cost": None}}))

    def test_api_key_comes_from_the_environment(self):
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-x"}):
            self.assertEqual(audit.api_key(), "sk-x")
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit) as raised:
                audit.api_key()
        self.assertIn("OPENROUTER_API_KEY", str(raised.exception))
        self.assertNotIn("sk-", str(raised.exception))


class Spending(unittest.TestCase):
    def rows(self):
        old = {**row("D", model="b"), "input_tokens": None, "output_tokens": None}  # written before tokens were kept
        return [row("B", cost=0.001, model="a"), row("C", cost=0.003, model="a"), old]

    def test_report_totals_calls_tokens_and_cost_by_snapshot(self):
        path = Path(tempfile.mkdtemp()) / "audit.jsonl"
        write(path, self.rows())
        found = audit.report(path)
        self.assertEqual(sorted(found), ["a", "b"])
        self.assertEqual(found["a"]["calls"], 2)
        self.assertEqual((found["a"]["input_tokens"], found["a"]["output_tokens"]), (200, 10))
        self.assertEqual((found["a"]["cost"], found["a"]["mean cost"]), (0.004, 0.002))
        self.assertEqual((found["b"]["without tokens"], found["b"]["input_tokens"]), (1, 0))
        self.assertEqual(audit.report(Path(tempfile.mkdtemp()) / "none.jsonl"), {})

    def test_main_prints_the_report_for_a_file_or_says_there_is_none(self):
        path = Path(tempfile.mkdtemp()) / "audit.jsonl"
        write(path, self.rows())
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(audit.main([str(path)]), 0)
        self.assertEqual(json.loads(printed.getvalue())["a"]["calls"], 2)
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            audit.main([str(path.with_name("none.jsonl"))])
        self.assertIn("no answers in", printed.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(sys, "argv", ["audit_labels.py"]):
            audit.main()  # the default file next to the script

    def test_runs_as_a_script(self):
        path = Path(tempfile.mkdtemp()) / "audit.jsonl"
        write(path, self.rows())
        with mock.patch.object(sys, "argv", ["audit_labels.py", str(path)]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(Path(audit.__file__)), run_name="__main__")
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
