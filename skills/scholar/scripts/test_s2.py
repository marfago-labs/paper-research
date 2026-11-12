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

    def test_retries_every_busy_or_failing_status_and_nothing_else(self):
        for code in (429, 500, 502, 503, 504):
            with mock.patch.object(s2.OPENER, "open", side_effect=[http_error(code), fake_response({})]) as opened:
                self.assertEqual(s2.request("GET", "/x"), {}, code)
            self.assertEqual(opened.call_count, 2, code)
        for code in (400, 401, 403, 404, 501):
            with mock.patch.object(s2.OPENER, "open", side_effect=[http_error(code)]) as opened:
                with self.assertRaisesRegex(s2.ApiError, f"HTTP {code}"):
                    s2.request("GET", "/x")
            self.assertEqual(opened.call_count, 1, code)

    def test_an_error_keeps_the_first_300_characters_of_the_reply(self):
        long = urllib.error.HTTPError("https://api.semanticscholar.org/x", 400, "bad", {}, io.BytesIO(b"x" * 400))
        with mock.patch.object(s2.OPENER, "open", side_effect=[long]):
            with self.assertRaises(s2.ApiError) as caught:
                s2.request("GET", "/x")
        self.assertIn("x" * 300, str(caught.exception))
        self.assertNotIn("x" * 301, str(caught.exception))


class RetryDelay(unittest.TestCase):
    def test_backs_off_from_2_seconds_doubling_up_to_30(self):
        self.assertEqual([s2.retry_delay(None, attempt) for attempt in range(6)], [2, 4, 8, 16, 30, 30])

    def test_follows_retry_after_for_at_most_a_minute(self):
        self.assertEqual(s2.retry_delay("5", 0), 5)
        self.assertEqual(s2.retry_delay("60", 0), 60)
        self.assertEqual(s2.retry_delay("61", 0), 60)
        self.assertEqual(s2.retry_delay("soon", 2), 8)


class Links(unittest.TestCase):
    """Each paper carries the ID column of a paper list as a ready link, so it doesn't depend on Claude's wording."""

    def test_a_link_prefers_the_arxiv_id_then_the_doi_then_the_page(self):
        both = {"externalIds": {"ArXiv": "2611.14326", "DOI": "10.1/x"}, "url": "https://www.semanticscholar.org/p/a"}
        self.assertEqual(s2.paper_link(both), "[ARXIV:2611.14326](https://arxiv.org/abs/2611.14326)")
        doi = {"externalIds": {"DOI": "10.1145/3442188.3445922"}, "url": "https://www.semanticscholar.org/p/b"}
        self.assertEqual(s2.paper_link(doi), "[DOI:10.1145/3442188.3445922](https://doi.org/10.1145/3442188.3445922)")
        page = {"externalIds": {"CorpusId": 1}, "url": "https://www.semanticscholar.org/p/c"}
        self.assertEqual(s2.paper_link(page), "https://www.semanticscholar.org/p/c")
        self.assertIsNone(s2.paper_link({"externalIds": None, "url": None}))
        self.assertIsNone(s2.paper_link({"title": "no ids"}))

    def test_a_doi_that_would_break_a_markdown_link_is_escaped(self):
        odd = {"externalIds": {"DOI": "10.1002/(SICI)1097[x]"}}
        self.assertEqual(
            s2.paper_link(odd), r"[DOI:10.1002/(SICI)1097\[x\]](https://doi.org/10.1002/%28SICI%291097%5Bx%5D)"
        )

    def test_every_command_that_returns_papers_adds_their_links(self):
        paper = {"title": "A", "externalIds": {"ArXiv": "2401.00001"}}
        link = "[ARXIV:2401.00001](https://arxiv.org/abs/2401.00001)"
        cases = (
            (["search", "agents"], {"total": 1, "data": [paper]}, lambda out: out["data"][0]),
            (
                ["recommend", "--like", "2401.00001"],
                {"recommendedPapers": [paper]},
                lambda out: out["recommendedPapers"][0],
            ),
            (["batch", "2401.00001"], [paper], lambda out: out[0]),
            (["paper", "2401.00001"], paper, lambda out: out),
        )
        for argv, answer, pick in cases:
            args = s2.build_parser().parse_args(argv)
            with mock.patch.object(s2, "request", return_value=answer):
                self.assertEqual(pick(args.func(args))["link"], link, argv)

    def test_citing_and_cited_papers_get_links_too(self):
        args = s2.build_parser().parse_args(["paper", "2303.11366", "--citations"])
        citing = {"title": "B", "externalIds": {"DOI": "10.1/b"}}
        responses = [{"title": "A"}, {"data": [{"citingPaper": citing, "isInfluential": False}]}]
        with mock.patch.object(s2, "request", side_effect=responses):
            result = args.func(args)
        self.assertEqual(result["citations"][0]["link"], "[DOI:10.1/b](https://doi.org/10.1/b)")

    def test_citing_and_cited_papers_ask_for_the_page_their_link_falls_back_to(self):
        # A citing paper with no arXiv id or DOI is linked to its Semantic Scholar page, so the page must be asked for.
        self.assertIn("url", s2.LINK_FIELDS.split(","))
        args = s2.build_parser().parse_args(["paper", "2303.11366", "--references"])
        cited = {"title": "C", "externalIds": {"CorpusId": 7}, "url": "https://www.semanticscholar.org/paper/c"}
        responses = [{"title": "A"}, {"data": [{"citedPaper": cited, "isInfluential": False}]}]
        with mock.patch.object(s2, "request", side_effect=responses) as sent:
            result = args.func(args)
        self.assertIn("url", sent.call_args_list[1].args[2]["fields"].split(","))
        self.assertEqual(result["references"][0]["link"], "https://www.semanticscholar.org/paper/c")

    def test_papers_without_an_id_or_page_and_missing_papers_get_no_link(self):
        args = s2.build_parser().parse_args(["batch", "2401.00001", "2401.00002"])
        with mock.patch.object(s2, "request", return_value=[{"title": "A"}, None]):
            result = args.func(args)
        self.assertNotIn("link", result[0])
        self.assertEqual(result[1], {"requestedId": "ARXIV:2401.00002", "error": "not found"})
        search = s2.build_parser().parse_args(["search", "agents"])
        with mock.patch.object(s2, "request", return_value={"total": 0}):
            self.assertEqual(search.func(search), {"total": 0})


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

    def test_limits_are_accepted_at_their_edges_and_refused_past_them(self):
        ranges = (
            (lambda value: ["search", "x", "--limit", value], 1, 100),
            (lambda value: ["search", "x", "--offset", value], 0, 9999),
            (lambda value: ["paper", "2401.00001", "--limit", value], 1, 1000),
            (lambda value: ["recommend", "--like", "2401.00001", "--limit", value], 1, 500),
        )
        for argv, low, high in ranges:
            for value in (low, high):
                args = s2.build_parser().parse_args(argv(str(value)))
                with mock.patch.object(s2, "request", return_value={}):
                    args.func(args)
            for value in (low - 1, high + 1):
                args = s2.build_parser().parse_args(argv(str(value)))
                with self.assertRaisesRegex(ValueError, "must be between", msg=argv(str(value))):
                    args.func(args)

    def test_batch_takes_exactly_500_ids_on_the_command_line(self):
        args = s2.build_parser().parse_args(["batch", *[f"2401.{n:05d}" for n in range(1, 501)]])
        with mock.patch.object(s2, "request", return_value=[None] * 500) as sent:
            self.assertEqual(len(args.func(args)), 500)
        self.assertEqual(sent.call_count, 1)

    def test_the_documented_defaults(self):
        search = s2.build_parser().parse_args(["search", "x"])
        self.assertEqual((search.limit, search.offset), (10, 0))
        self.assertEqual(s2.build_parser().parse_args(["paper", "2401.00001"]).limit, 20)
        self.assertEqual(s2.build_parser().parse_args(["recommend", "--like", "2401.00001"]).limit, 20)

    def test_a_command_and_liked_papers_are_required(self):
        for argv in ([], ["recommend"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                s2.build_parser().parse_args(argv)
            self.assertEqual(stopped.exception.code, 2, argv)

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
        with self.assertRaisesRegex(ValueError, "at most 500.*--ids-file"):
            args.func(args)

    def test_batch_reads_any_number_of_ids_from_a_file_in_requests_of_500(self):
        ids = [f"ARXIV:2401.{n:05d}" for n in range(1, 1202)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ids.txt"
            path.write_text("\n".join(ids) + "\n\n", encoding="utf-8")
            args = s2.build_parser().parse_args(["batch", "--ids-file", str(path), "2303.11366"])

            def answer(method, route, params, body):
                return [None if requested == "ARXIV:2303.11366" else {} for requested in body["ids"]]

            with mock.patch.object(s2, "request", side_effect=answer) as sent:
                result = args.func(args)
        sizes = [len(call.args[3]["ids"]) for call in sent.call_args_list]
        self.assertEqual(sizes, [500, 500, 202])
        self.assertEqual([paper["requestedId"] for paper in result], ["ARXIV:2303.11366", *ids])
        self.assertEqual(result[0], {"requestedId": "ARXIV:2303.11366", "error": "not found"})

    def test_batch_can_also_ask_for_the_reference_lists_in_requests_of_100(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ids.txt"
            path.write_text("\n".join(f"ARXIV:2401.{n:05d}" for n in range(1, 202)), encoding="utf-8")
            with_references = s2.build_parser().parse_args(["batch", "--ids-file", str(path), "--with-references"])
            plain = s2.build_parser().parse_args(["batch", "--ids-file", str(path)])

            def answer(method, route, params, body):
                return [{} for _ in body["ids"]]

            with mock.patch.object(s2, "request", side_effect=answer) as sent:
                with_references.func(with_references)
            sizes = [len(call.args[3]["ids"]) for call in sent.call_args_list]
            fields = [call.args[2]["fields"] for call in sent.call_args_list]
            with mock.patch.object(s2, "request", side_effect=answer) as plain_sent:
                plain.func(plain)
        self.assertEqual(sizes, [100, 100, 1])
        self.assertTrue(all("references.paperId" in f and "references.externalIds" in f for f in fields), fields)
        self.assertTrue(all("citations" not in f.replace("citationCount", "") for f in fields), fields)
        self.assertEqual(plain_sent.call_count, 1)
        self.assertNotIn("references", plain_sent.call_args.args[2]["fields"])

    def test_a_failed_later_request_keeps_the_papers_already_fetched(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ids.txt"
            path.write_text("\n".join(f"ARXIV:2401.{n:05d}" for n in range(1, 502)), encoding="utf-8")
            argv = ["batch", "--ids-file", str(path)]
            args = s2.build_parser().parse_args(argv)
            failures = [[{}] * 500, s2.ApiError("HTTP 503 from /graph/v1/paper/batch")]
            with mock.patch.object(s2, "request", side_effect=failures):
                with self.assertRaisesRegex(s2.PartialBatch, "500 of 501 papers") as caught:
                    args.func(args)
            self.assertEqual(len(caught.exception.results), 500)
            with mock.patch.object(s2, "request", side_effect=failures[1]):
                with self.assertRaises(s2.ApiError) as first:
                    args.func(args)
            self.assertNotIsInstance(first.exception, s2.PartialBatch)

    def test_batch_needs_some_ids_and_a_readable_file(self):
        with tempfile.TemporaryDirectory() as folder:
            empty = Path(folder) / "empty.txt"
            empty.write_text("\n", encoding="utf-8")
            for argv, expected in (
                (["batch"], "give at least one"),
                (["batch", "--ids-file", str(empty)], "give at least one"),
                (["batch", "--ids-file", str(Path(folder) / "missing.txt")], "can't read"),
            ):
                args = s2.build_parser().parse_args(argv)
                with self.assertRaisesRegex(ValueError, expected):
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

    def pace_at(self, now, last, interval=0.5):
        """Pace at a fixed time, with the previous request at last. Exact binary fractions keep the sums exact."""
        self.cache.mkdir(exist_ok=True)
        (self.cache / s2.STATE_NAME).write_text(repr(last), encoding="utf-8")
        with mock.patch.object(s2, "MIN_INTERVAL", interval), mock.patch.object(s2.time, "time", return_value=now):
            s2.pace()

    def test_waits_exactly_the_rest_of_the_interval(self):
        self.pace_at(now=1000.25, last=1000.0)
        self.sleep.assert_called_once_with(0.25)

    def test_does_not_wait_once_the_interval_has_passed(self):
        for now in (1000.5, 1001.0):
            self.sleep.reset_mock()
            self.pace_at(now=now, last=1000.0)
            self.sleep.assert_not_called()

    def test_creates_the_cache_folder_with_its_parents(self):
        nested = self.cache / "a" / "b"
        with mock.patch.object(s2, "CACHE_DIR", nested):
            s2.pace()
        self.assertTrue((nested / s2.STATE_NAME).is_file())

    def test_a_held_lock_is_tried_until_its_deadline_has_passed(self):
        self.cache.mkdir()
        lock = self.cache / "held.lock"
        clock = [100.0]

        def sleep(seconds):
            clock[0] += 0.25  # exact steps, so the deadline is hit exactly

        self.sleep.side_effect = sleep
        with open(lock, "a+b") as holder, mock.patch.object(s2.time, "monotonic", lambda: clock[0]):
            self.assertTrue(s2.try_lock(holder))
            with self.assertRaisesRegex(s2.ApiError, "busy"):
                with s2.file_lock(lock, 0.5, "busy"):
                    pass
            s2.unlock(holder)
        # Tried at 100.0, 100.25, 100.5 (the deadline itself), and 100.75, which is past it.
        self.assertEqual(self.sleep.call_count, 3)

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

    def test_gives_up_when_a_sleep_overran_the_deadline(self):
        # The wait was checked against the deadline before sleeping, but the sleep itself ran 89 seconds long. The next
        # round starts past the deadline and must stop there, not ask once more.
        clock, asked = [0.0], []

        def fail(request, timeout=None):
            asked.append(1)
            raise http_error(503)

        def overrunning_sleep(seconds):
            clock[0] += seconds + 89

        with (
            mock.patch.object(s2.OPENER, "open", fail),
            mock.patch.object(s2.time, "monotonic", lambda: clock[0]),
            mock.patch.object(s2.time, "sleep", overrunning_sleep),
            self.assertRaises(s2.ApiError) as caught,
        ):
            s2.request("GET", "/x")
        self.assertEqual(str(caught.exception), "gave up on /x after about 90 seconds")
        self.assertEqual(len(asked), 1)

    def test_gives_up_when_the_next_wait_would_pass_the_deadline(self):
        self.assertIn("gave up on /x after about 90 seconds of retries", self.run_on_a_fake_clock(40))

    def test_gives_up_when_the_deadline_is_reached_exactly(self):
        message = self.run_on_a_fake_clock(30)
        self.assertIn("gave up on /x after about 90 seconds", message)
        self.assertNotIn("of retries", message)

    def test_each_request_gets_the_time_left_before_the_deadline(self):
        timeouts = []

        def opened(request, timeout):
            timeouts.append(timeout)
            return fake_response({})

        for elapsed in (0.0, 70.0, s2.DEADLINE - 0.5):
            with (
                mock.patch.object(s2.OPENER, "open", opened),
                mock.patch.object(s2.time, "monotonic", return_value=1000.0 + elapsed),
            ):
                s2.read_json(s2.build_request("GET", "/x", None, None), "/x", 1000.0)
        # The usual timeout, then what is left of the deadline, then never less than a second.
        self.assertEqual(timeouts, [s2.TIMEOUT, s2.DEADLINE - 70.0, 1])

    def test_the_wait_for_the_pacing_lock_shrinks_with_the_time_left(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        def busy(request, timeout=None):
            raise http_error(503, {"Retry-After": "40"})

        with (
            mock.patch.object(s2.OPENER, "open", busy),
            mock.patch.object(s2.time, "monotonic", lambda: clock[0]),
            mock.patch.object(s2.time, "sleep", sleep),
            self.assertRaises(s2.ApiError),
        ):
            s2.request("GET", "/x")
        waits = [call.args[0] for call in s2.pace.call_args_list]
        self.assertEqual(waits, [min(s2.LOCK_WAIT, s2.DEADLINE), s2.DEADLINE - 40, s2.DEADLINE - 80])

    def test_reads_one_byte_past_the_cap_and_accepts_a_reply_of_exactly_the_cap(self):
        asked = []

        class Reply(io.BytesIO):
            def read(self, size=-1):
                asked.append(size)
                return super().read(size)

        with mock.patch.object(s2, "MAX_BYTES", 2), mock.patch.object(s2.OPENER, "open", return_value=Reply(b"{}")):
            self.assertEqual(s2.request("GET", "/x"), {})
        self.assertEqual(asked, [3])

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

    def test_a_partly_failed_batch_prints_what_it_fetched_and_exits_with_1(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ids.txt"
            path.write_text("\n".join(f"ARXIV:2401.{n:05d}" for n in range(1, 502)), encoding="utf-8")
            with mock.patch.object(s2, "request", side_effect=[[{}] * 500, s2.ApiError("HTTP 503")]):
                code, out, err = self.run_main(["batch", "--ids-file", str(path)])
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out)), 500)
        self.assertIn("500 of 501 papers", err)

    def test_success_prints_json_without_escaping_text(self):
        with mock.patch.object(s2, "request", return_value={"title": "τ²"}):
            code, out, _ = self.run_main(["search", "agents"])
        self.assertEqual(code, 0)
        # Indented, so it reads in a terminal, and unescaped, so titles stay readable.
        self.assertEqual(out, json.dumps({"title": "τ²"}, ensure_ascii=False, indent=2) + "\n")

    def test_a_partly_failed_batch_prints_what_it_fetched_the_same_way(self):
        with mock.patch.object(s2, "request", side_effect=[[{"title": "τ²"}] * 500, s2.ApiError("HTTP 503")]):
            code, out, _ = self.run_main(["batch", *[f"2401.{n:05d}" for n in range(1, 501)], "--with-references"])
        self.assertEqual(code, 1)
        fetched = [{"requestedId": f"ARXIV:2401.{n:05d}", "title": "τ²"} for n in range(1, 101)]
        self.assertEqual(out, json.dumps(fetched, ensure_ascii=False, indent=2) + "\n")

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
