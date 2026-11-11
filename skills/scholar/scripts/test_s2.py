"""Offline tests for s2.py. Run: python .claude/skills/scholar/scripts/test_s2.py"""

import contextlib
import io
import json
import os
import runpy
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import s2

_CACHE = tempfile.TemporaryDirectory()  # keep request pacing state out of the real .cache
s2.CACHE_DIR = Path(_CACHE.name)


def fake_response(payload):
    response = io.BytesIO(json.dumps(payload).encode("utf-8"))
    return response


def http_error(code, headers=None):
    return urllib.error.HTTPError(
        "https://api.semanticscholar.org/x", code, "error", headers or {}, io.BytesIO(b"detail")
    )


class NormalizeId(unittest.TestCase):
    def test_arxiv_forms(self):
        for value in (
            "2303.11366",
            "2303.11366v2",
            "arxiv:2303.11366",
            "https://arxiv.org/abs/2303.11366v2",
            "https://arxiv.org/pdf/2303.11366.pdf",
            "https://arxiv.org/html/2303.11366v1",
            "https://huggingface.co/papers/2303.11366",
        ):
            self.assertEqual(s2.normalize_id(value), "ARXIV:2303.11366", value)

    def test_doi_and_other_links(self):
        self.assertEqual(s2.normalize_id("https://doi.org/10.1000/abc"), "DOI:10.1000/abc")
        self.assertEqual(s2.normalize_id("10.1000/abc"), "DOI:10.1000/abc")
        self.assertEqual(s2.normalize_id("DOI:10.1000/abc"), "DOI:10.1000/abc")

    def test_old_style_arxiv_forms(self):
        for value in (
            "hep-th/9901001",
            "hep-th/9901001v2",
            "arXiv:hep-th/9901001",
            "https://arxiv.org/abs/hep-th/9901001v1",
            "https://arxiv.org/pdf/hep-th/9901001.pdf",
        ):
            self.assertEqual(s2.normalize_id(value), "ARXIV:hep-th/9901001", value)
        self.assertEqual(s2.normalize_id("math.GT/0309136"), "ARXIV:math.GT/0309136")
        self.assertEqual(
            s2.normalize_id("https://aclanthology.org/N18-3011"),
            "URL:https://aclanthology.org/N18-3011",
        )

    def test_rejects_unsafe_values(self):
        for value in ("", "a b", "x/../y", "a\nb"):
            with self.assertRaises(ValueError, msg=value):
                s2.normalize_id(value)

    def test_path_cannot_add_query_or_fragment(self):
        path = s2.paper_path("URL:https://example.org/a?b=c#d")
        self.assertNotIn("?", path)
        self.assertNotIn("#", path)


class RequestBehaviour(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(s2.time, "sleep"), mock.patch.object(s2, "pace")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_uses_fixed_host_and_sends_key_only_as_header(self):
        with mock.patch.dict(os.environ, {"SEMANTIC_SCHOLAR_API_KEY": "secret"}):
            with mock.patch.object(s2.OPENER, "open", return_value=fake_response({})) as opened:
                s2.request("GET", "/graph/v1/paper/x", {"fields": "title"})
        sent = opened.call_args.args[0]
        self.assertTrue(sent.full_url.startswith("https://api.semanticscholar.org/"))
        self.assertNotIn("secret", sent.full_url)
        self.assertEqual(sent.get_header("X-api-key"), "secret")

    def test_retries_rate_limit_then_succeeds(self):
        responses = [http_error(429, {"Retry-After": "1"}), fake_response({"ok": True})]
        with mock.patch.object(s2.OPENER, "open", side_effect=responses) as opened:
            self.assertEqual(s2.request("GET", "/x"), {"ok": True})
        self.assertEqual(opened.call_count, 2)

    def test_does_not_retry_not_found(self):
        with mock.patch.object(s2.OPENER, "open", side_effect=[http_error(404)]) as opened:
            with self.assertRaises(s2.ApiError):
                s2.request("GET", "/x")
        self.assertEqual(opened.call_count, 1)

    def test_gives_up_after_max_attempts(self):
        errors = [http_error(503) for _ in range(s2.MAX_ATTEMPTS)]
        with mock.patch.object(s2.OPENER, "open", side_effect=errors) as opened:
            with self.assertRaises(s2.ApiError):
                s2.request("GET", "/x")
        self.assertEqual(opened.call_count, s2.MAX_ATTEMPTS)

    def test_redirects_are_refused(self):
        handler = s2.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example"))


class Commands(unittest.TestCase):
    def test_batch_keeps_requested_id_and_marks_missing(self):
        args = s2.build_parser().parse_args(["batch", "2303.11366", "2210.03629"])
        with mock.patch.object(s2, "request", return_value=[{"title": "A"}, None]):
            result = args.func(args)
        self.assertEqual(result[0], {"requestedId": "ARXIV:2303.11366", "title": "A"})
        self.assertEqual(result[1], {"requestedId": "ARXIV:2210.03629", "error": "not found"})

    def test_recommend_sends_likes_and_dislikes(self):
        args = s2.build_parser().parse_args(["recommend", "--like", "2303.11366", "--dislike", "2210.03629"])
        with mock.patch.object(s2, "request", return_value={}) as sent:
            args.func(args)
        self.assertEqual(
            sent.call_args.args[3],
            {"positivePaperIds": ["ARXIV:2303.11366"], "negativePaperIds": ["ARXIV:2210.03629"]},
        )

    def test_authors_marks_missing_and_rejects_bad_ids(self):
        args = s2.build_parser().parse_args(["authors", "123", "456"])
        with mock.patch.object(s2, "request", return_value=[{"name": "A", "hIndex": 3}, None]):
            result = args.func(args)
        self.assertEqual(result[0]["hIndex"], 3)
        self.assertEqual(result[1], {"authorId": "456", "error": "not found"})
        bad = s2.build_parser().parse_args(["authors", "../x"])
        with self.assertRaises(ValueError):
            bad.func(bad)

    def test_search_sends_only_the_filters_given(self):
        plain = s2.build_parser().parse_args(["search", "agents"])
        with mock.patch.object(s2, "request", return_value={}) as sent:
            plain.func(plain)
        self.assertNotIn("year", sent.call_args.args[2])
        self.assertNotIn("minCitationCount", sent.call_args.args[2])

        filtered = s2.build_parser().parse_args(["search", "agents", "--year", "2025-", "--min-citations", "0"])
        with mock.patch.object(s2, "request", return_value={}) as sent:
            filtered.func(filtered)
        self.assertEqual(sent.call_args.args[2]["year"], "2025-")
        self.assertEqual(sent.call_args.args[2]["minCitationCount"], 0)

    def test_paper_only_fetches_the_lists_requested(self):
        args = s2.build_parser().parse_args(["paper", "2303.11366"])
        with mock.patch.object(s2, "request", return_value={"title": "A"}) as sent:
            self.assertEqual(args.func(args), {"title": "A"})
        self.assertEqual(sent.call_count, 1)

    def test_paper_unwraps_citations_and_references(self):
        args = s2.build_parser().parse_args(["paper", "2303.11366", "--citations", "--references"])
        responses = [
            {"title": "A"},
            {"data": [{"citingPaper": {"title": "B"}, "isInfluential": True}, {"citingPaper": None}]},
            {"data": None},
        ]
        with mock.patch.object(s2, "request", side_effect=responses):
            result = args.func(args)
        self.assertEqual(
            result["citations"],
            [{"title": "B", "isInfluential": True}, {"isInfluential": None}],
        )
        self.assertEqual(result["references"], [])

    def test_rejects_out_of_range_limits(self):
        for argv in (
            ["search", "x", "--limit", "0"],
            ["search", "x", "--offset", "-1"],
            ["paper", "2401.00001", "--limit", "1001"],
            ["recommend", "--like", "2401.00001", "--limit", "501"],
        ):
            args = s2.build_parser().parse_args(argv)
            with self.assertRaisesRegex(ValueError, "must be between"):
                args.func(args)

    def test_rejects_unexpected_batch_responses(self):
        for argv in (["batch", "2401.00001"], ["authors", "123"]):
            args = s2.build_parser().parse_args(argv)
            with mock.patch.object(s2, "request", return_value={"error": "x"}):
                with self.assertRaisesRegex(s2.ApiError, "unexpected response"):
                    args.func(args)

    def test_author_ids_must_be_ascii_digits(self):
        args = s2.build_parser().parse_args(["authors", "12\u00b2"])
        with self.assertRaisesRegex(ValueError, "invalid author ID"):
            args.func(args)

    def test_batch_rejects_too_many_ids(self):
        args = s2.build_parser().parse_args(["batch", *[f"id{n}" for n in range(501)]])
        with self.assertRaisesRegex(ValueError, "at most 500"):
            args.func(args)


class Pacing(unittest.TestCase):
    """Spacing is shared through a state file and a lock the operating system releases if a process dies."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache = Path(folder.name) / "cache"
        cache = mock.patch.object(s2, "CACHE_DIR", self.cache)
        cache.start()
        self.addCleanup(cache.stop)
        sleep = mock.patch.object(s2.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_waits_only_when_called_too_soon(self):
        s2.pace()
        self.sleep.assert_not_called()
        s2.pace()
        self.assertLessEqual(self.sleep.call_args.args[0], s2.MIN_INTERVAL)
        self.assertGreater(self.sleep.call_args.args[0], s2.MIN_INTERVAL - 1)
        (self.cache / s2.STATE_NAME).write_text("garbage", encoding="utf-8")
        self.sleep.reset_mock()
        s2.pace()
        self.sleep.assert_not_called()

    def test_a_held_lock_blocks_until_time_runs_out(self):
        self.cache.mkdir()
        lock = self.cache / f"{s2.STATE_NAME}.lock"
        with open(lock, "a+b") as holder:
            self.assertTrue(s2.try_lock(holder))
            with self.assertRaisesRegex(s2.ApiError, "still queued"):
                s2.pace(0)
            s2.unlock(holder)
        s2.pace()

    def test_a_leftover_lock_file_blocks_nobody(self):
        self.cache.mkdir()
        (self.cache / f"{s2.STATE_NAME}.lock").write_bytes(b"left by a process that died")
        s2.pace()

    def test_waits_for_a_lock_that_is_released_meanwhile(self):
        self.cache.mkdir()
        holder = open(self.cache / f"{s2.STATE_NAME}.lock", "a+b")  # noqa: SIM115  closed by the cleanup
        self.addCleanup(holder.close)
        self.assertTrue(s2.try_lock(holder))
        released = []

        def release(seconds):
            if not released:
                released.append(1)
                s2.unlock(holder)

        self.sleep.side_effect = release
        s2.pace()
        self.assertEqual(released, [1])


class Workspace(unittest.TestCase):
    def test_finds_the_workspace_from_a_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "research").mkdir()
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            with mock.patch.object(s2.Path, "cwd", return_value=nested):
                self.assertEqual(s2.find_workspace(), root)
                with mock.patch.object(s2, "CACHE_DIR", None):
                    self.assertEqual(s2.cache_dir(), root / ".cache")

    def test_refuses_to_guess_when_there_is_no_workspace(self):
        with mock.patch.object(s2.Path, "is_dir", return_value=False):
            with self.assertRaisesRegex(ValueError, "run the init skill"):
                s2.find_workspace()


class RequestFailures(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(s2.time, "sleep"), mock.patch.object(s2, "pace")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_sends_json_body_without_a_query_string(self):
        with mock.patch.object(s2.OPENER, "open", return_value=fake_response({})) as opened:
            s2.request("POST", "/x", body={"ids": ["a"]})
        sent = opened.call_args.args[0]
        self.assertEqual(json.loads(sent.data), {"ids": ["a"]})
        self.assertEqual(sent.get_header("Content-type"), "application/json")
        self.assertNotIn("?", sent.full_url)

    def test_retries_network_failures_then_succeeds(self):
        responses = [urllib.error.URLError("down"), TimeoutError(), fake_response({"ok": True})]
        with mock.patch.object(s2.OPENER, "open", side_effect=responses):
            self.assertEqual(s2.request("GET", "/x"), {"ok": True})

    def test_gives_up_on_repeated_network_failures(self):
        errors = [urllib.error.URLError("down") for _ in range(s2.MAX_ATTEMPTS)]
        with mock.patch.object(s2.OPENER, "open", side_effect=errors) as opened:
            with self.assertRaisesRegex(s2.ApiError, "network failure"):
                s2.request("GET", "/x")
        self.assertEqual(opened.call_count, s2.MAX_ATTEMPTS)

    def run_on_a_fake_clock(self, seconds_per_request):
        """Every request takes this long and fails with a 60 second Retry-After. Returns the error."""
        clock = [0.0]

        def fail(request, timeout=None):
            clock[0] += seconds_per_request
            raise http_error(503, {"Retry-After": "60"})

        def sleep(seconds):
            clock[0] += seconds

        with (
            mock.patch.object(s2.OPENER, "open", fail),
            mock.patch.object(s2.time, "monotonic", lambda: clock[0]),
            mock.patch.object(s2.time, "sleep", sleep),
            self.assertRaises(s2.ApiError) as caught,
        ):
            s2.request("GET", "/x")
        return str(caught.exception)

    def test_gives_up_when_the_next_wait_would_pass_the_deadline(self):
        self.assertIn("gave up on /x after about 90 seconds of retries", self.run_on_a_fake_clock(40))

    def test_gives_up_when_the_deadline_is_reached_exactly(self):
        message = self.run_on_a_fake_clock(30)
        self.assertIn("gave up on /x after about 90 seconds", message)
        self.assertNotIn("of retries", message)

    def test_refuses_oversized_responses(self):
        with (
            mock.patch.object(s2, "MAX_BYTES", 5),
            mock.patch.object(s2.OPENER, "open", return_value=io.BytesIO(b"[1,2,3,4]")),
        ):
            with self.assertRaisesRegex(s2.ApiError, "larger than 5 bytes"):
                s2.request("GET", "/x")

    def test_reports_invalid_json(self):
        with mock.patch.object(s2.OPENER, "open", return_value=io.BytesIO(b"not json")):
            with self.assertRaisesRegex(s2.ApiError, "not valid JSON"):
                s2.request("GET", "/x")


class CommandLine(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8"), io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = s2.main(argv)
        out.seek(0)
        err.seek(0)
        return code, out.read(), err.read()

    def test_success_prints_json_without_escaping_text(self):
        with mock.patch.object(s2, "request", return_value={"title": "τ²"}):
            code, out, _ = self.run_main(["search", "agents"])
        self.assertEqual(code, 0)
        self.assertIn("τ²", out)

    def test_invalid_input_exits_2(self):
        code, _, err = self.run_main(["paper", "a b"])
        self.assertEqual(code, 2)
        self.assertIn("invalid paper ID", err)

    def test_api_failure_exits_1(self):
        with mock.patch.object(s2, "request", side_effect=s2.ApiError("HTTP 429")):
            code, _, err = self.run_main(["search", "agents"])
        self.assertEqual(code, 1)
        self.assertIn("HTTP 429", err)

    def test_runs_as_a_script(self):
        out, err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8"), io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with mock.patch.object(sys, "argv", ["s2.py", "authors", "not-a-number"]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as stopped:
                    runpy.run_path(s2.__file__, run_name="__main__")
        self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
