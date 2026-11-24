#!/usr/bin/env python3
"""Tests for debuglog.py. Run: python skills/debug/scripts/test_debuglog.py"""

import argparse
import contextlib
import http.client
import http.server
import io
import json
import os
import runpy
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import debuglog  # noqa: E402


@contextlib.contextmanager
def workspace(on=True):
    """A temporary workspace with a research/ folder, and debugging on unless on is False."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder).resolve()
        (root / "research").mkdir()
        if on:
            (root / "research" / ".debug").write_text("on\n", encoding="utf-8")
        with mock.patch.dict(os.environ):
            for name in debuglog.ENDPOINTS:
                os.environ.pop(name, None)
            yield root


def logged(root):
    path = root / "research" / ".debug.log"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


class Out(io.StringIO):
    """Standard output that a script can reconfigure."""

    def reconfigure(self, **kwargs):
        pass


class Collector(http.server.BaseHTTPRequestHandler):
    received: list = []
    status = 200

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        Collector.received.append((self.path, self.headers["Content-Type"], json.loads(self.rfile.read(length))))
        self.send_response(Collector.status)
        self.send_header("Location", "http://127.0.0.1:1/elsewhere")
        self.end_headers()

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def collector(status=200):
    Collector.received = []
    Collector.status = status
    server = http.server.HTTPServer(("127.0.0.1", 0), Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class Events(unittest.TestCase):
    def test_nothing_is_recorded_while_debug_is_off(self):
        with workspace(on=False) as root:
            debuglog.event("graph", "command", str(root), exit=0)
            self.assertFalse((root / "research" / ".debug.log").exists())

    def test_nothing_is_recorded_outside_a_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            debuglog.event("graph", "command", folder, exit=0)
            self.assertEqual(os.listdir(folder), [])

    def test_an_event_is_one_json_line_with_its_fields(self):
        with workspace() as root:
            debuglog.event("graph", "command", root, exit=0, command="stats", ok=True, ratio=0.5)
            (rec,) = logged(root)
        self.assertEqual(
            {key: rec[key] for key in rec if key != "time"},
            {"source": "graph", "event": "command", "exit": 0, "command": "stats", "ok": True, "ratio": 0.5},
        )
        self.assertRegex(rec["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$")

    def test_events_are_appended_in_order(self):
        with workspace() as root:
            for n in range(3):
                debuglog.event("s", "e", root, n=n)
            self.assertEqual([rec["n"] for rec in logged(root)], [0, 1, 2])

    def test_a_folder_inside_the_workspace_finds_it(self):
        with workspace() as root:
            inner = root / "a" / "b"
            inner.mkdir(parents=True)
            debuglog.event("s", "e", inner)
            self.assertEqual(len(logged(root)), 1)

    def test_the_folder_defaults_to_the_current_one(self):
        with workspace() as root:
            before = Path.cwd()
            os.chdir(root)
            try:
                debuglog.event("s", "e")
            finally:
                os.chdir(before)
            self.assertEqual(len(logged(root)), 1)

    def test_text_is_cut_and_numbers_are_kept(self):
        self.assertEqual(debuglog.clean("x" * 201), "x" * 200)
        self.assertEqual(debuglog.clean("x" * 200), "x" * 200)
        self.assertEqual(debuglog.clean(None), "None")
        for value in (True, 3, 0.25):
            self.assertIs(type(debuglog.clean(value)), type(value))

    def test_an_unreadable_folder_is_no_workspace(self):
        with mock.patch.object(Path, "resolve", side_effect=OSError("no")):
            self.assertIsNone(debuglog.research_folder("."))
        self.assertFalse(debuglog.is_on(None))

    def test_a_failed_write_does_not_raise(self):
        with workspace() as root:
            with mock.patch.object(debuglog, "append", side_effect=OSError("disk full")):
                debuglog.event("s", "e", root)

    def test_a_full_log_moves_aside_and_replaces_the_older_one(self):
        with workspace() as root:
            research = root / "research"
            with mock.patch.object(debuglog, "MAX_BYTES", 400):
                for n in range(12):
                    debuglog.event("s", "e", root, n=n)
            first, last = (research / ".debug.log.1"), (research / ".debug.log")
            self.assertTrue(first.exists())
            for path in (first, last):
                self.assertLessEqual(path.stat().st_size, 400)
            numbers = [json.loads(line)["n"] for path in (first, last) for line in path.read_text().splitlines()]
            self.assertEqual(numbers, sorted(numbers))
            self.assertEqual(numbers[-1], 11)
            self.assertNotIn(0, numbers)

    def test_a_log_that_still_fits_stays_in_one_file(self):
        with workspace() as root:
            for n in range(3):
                debuglog.event("s", "e", root, n=n)
            self.assertFalse((root / "research" / ".debug.log.1").exists())

    def test_a_line_that_exactly_fills_the_log_still_fits(self):
        # A 10-byte log and a 10-byte line: they add up to 20, and their product is 100.
        for limit, moved in ((20, False), (19, True)):
            with self.subTest(limit=limit), workspace() as root:
                research = root / "research"
                (research / ".debug.log").write_text("x" * 10, encoding="utf-8")
                with mock.patch.object(debuglog, "MAX_BYTES", limit):
                    debuglog.append(research, "y" * 9 + "\n")
                self.assertEqual((research / ".debug.log.1").exists(), moved)

    def test_the_size_limit_counts_bytes_not_characters(self):
        with workspace() as root:
            debuglog.event("s", "e", root, text="é" * 150)
            size = (root / "research" / ".debug.log").stat().st_size
            with mock.patch.object(debuglog, "MAX_BYTES", size + 1):
                debuglog.event("s", "e", root, text="é")
            self.assertTrue((root / "research" / ".debug.log.1").exists())


class Export(unittest.TestCase):
    def endpoint(self, value, name="PAPER_RESEARCH_OTLP_ENDPOINT", **others):
        with mock.patch.dict(os.environ, {name: value, **others}):
            for other in debuglog.ENDPOINTS:
                if other != name and other not in others:
                    os.environ.pop(other, None)
            return debuglog.otlp_url()

    def test_only_an_address_on_this_machine_is_used(self):
        self.assertEqual(self.endpoint("http://127.0.0.1:4318/"), "http://127.0.0.1:4318/v1/logs")
        self.assertEqual(self.endpoint("http://[::1]:4318"), "http://[::1]:4318/v1/logs")
        self.assertEqual(self.endpoint("http://127.0.0.1/otlp?x=1"), "http://127.0.0.1/otlp/v1/logs")
        for value in (
            "",
            "https://localhost:4318",
            "http://example.com:4318",
            "http://localhost.evil.com",
            "ftp://localhost",
        ):
            with self.subTest(value=value):
                self.assertIsNone(self.endpoint(value))

    def test_localhost_becomes_127_0_0_1_so_windows_does_not_wait_on_ipv6(self):
        self.assertEqual(self.endpoint("http://localhost:4318"), "http://127.0.0.1:4318/v1/logs")
        self.assertEqual(self.endpoint("http://user@LOCALHOST:4318"), "http://127.0.0.1:4318/v1/logs")

    def test_a_malformed_address_is_no_address(self):
        for value in ("http://[::1", "http://127.0.0.1:port"):
            with self.subTest(value=value):
                self.assertIsNone(self.endpoint(value))

    def test_the_standard_variable_is_used_when_the_plugins_is_unset(self):
        # Claude Code removes OTEL_ variables from the commands it runs, so this serves runs in a terminal.
        url = self.endpoint("http://127.0.0.1:4318", name="OTEL_EXPORTER_OTLP_ENDPOINT")
        self.assertEqual(url, "http://127.0.0.1:4318/v1/logs")

    def test_the_plugins_variable_wins_and_an_empty_one_counts_as_unset(self):
        standard = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1111"}
        self.assertEqual(self.endpoint("http://127.0.0.1:2222", **standard), "http://127.0.0.1:2222/v1/logs")
        self.assertEqual(self.endpoint("", **standard), "http://127.0.0.1:1111/v1/logs")
        self.assertIsNone(self.endpoint("http://example.com", **standard))

    def test_a_malformed_address_does_not_stop_an_event(self):
        with workspace() as root:
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": "http://[::1"}):
                debuglog.event("graph", "command", root, exit=0)
            self.assertEqual(len(logged(root)), 1)

    def test_events_do_not_go_through_a_proxy(self):
        env = {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1"}
        with workspace() as root, collector() as url:
            with mock.patch.dict(os.environ, {**env, "PAPER_RESEARCH_OTLP_ENDPOINT": url}):
                debuglog.event("graph", "command", root, exit=0)
            self.assertEqual(len(Collector.received), 1)

    def test_it_is_off_when_the_variables_are_unset(self):
        with mock.patch.dict(os.environ):
            for name in debuglog.ENDPOINTS:
                os.environ.pop(name, None)
            self.assertIsNone(debuglog.otlp_url())

    def test_the_record_has_the_same_fields_as_the_log(self):
        rec = {"time": "t", "source": "graph", "event": "command", "exit": 0, "ok": True}
        with mock.patch("time.time_ns", return_value=123):
            body = debuglog.otlp_body(rec)
        (resource,) = body["resourceLogs"]
        self.assertEqual(
            resource["resource"], {"attributes": [{"key": "service.name", "value": {"stringValue": "paper-research"}}]}
        )
        (record,) = resource["scopeLogs"][0]["logRecords"]
        self.assertEqual(record["timeUnixNano"], "123")
        self.assertEqual(record["severityText"], "INFO")
        self.assertEqual(record["body"], {"stringValue": "command"})
        self.assertEqual(
            record["attributes"],
            [
                {"key": "source", "value": {"stringValue": "graph"}},
                {"key": "event.name", "value": {"stringValue": "command"}},
                {"key": "exit", "value": {"stringValue": "0"}},
                {"key": "ok", "value": {"stringValue": "True"}},
            ],
        )

    def test_only_the_event_name_is_renamed_and_only_the_time_is_left_out(self):
        # Keys that sort before "event" and after "time", and copies of the two names that are not the same objects
        # as the literals, so a comparison by order or by identity gives a different answer.
        event, time_key = "".join(["ev", "ent"]), "".join(["ti", "me"])
        rec = {time_key: "t", "command": "stats", event: "command", "url": "u"}
        body = debuglog.otlp_body(rec)
        attributes = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]
        self.assertEqual([a["key"] for a in attributes], ["command", "event.name", "url"])

    def test_the_collector_gets_a_short_timeout_and_one_byte_is_read(self):
        reply = mock.MagicMock()
        reply.__enter__.return_value = reply
        with mock.patch.object(debuglog.OPENER, "open", return_value=reply) as opened:
            debuglog.send("http://127.0.0.1:4318/v1/logs", {})
        self.assertEqual(opened.call_args.kwargs["timeout"], 0.5)
        reply.read.assert_called_once_with(1)

    def test_an_event_is_sent_to_the_collector(self):
        with workspace() as root, collector() as url:
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": url}):
                debuglog.event("graph", "command", root, exit=0)
            ((path, kind, body),) = Collector.received
            self.assertEqual(len(logged(root)), 1)
        self.assertEqual((path, kind), ("/v1/logs", "application/json"))
        self.assertEqual(body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"], {"stringValue": "command"})

    def test_nothing_is_sent_while_debug_is_off(self):
        with workspace(on=False) as root, collector() as url:
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": url}):
                debuglog.event("graph", "command", root, exit=0)
            self.assertEqual(Collector.received, [])

    def test_a_collector_that_is_down_does_not_stop_the_log(self):
        with workspace() as root:
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": "http://127.0.0.1:1"}):
                debuglog.event("graph", "command", root, exit=0)
            self.assertEqual(len(logged(root)), 1)

    def test_a_redirect_is_not_followed(self):
        with workspace() as root, collector(status=307) as url:
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": url}):
                debuglog.event("graph", "command", root, exit=0)
            self.assertEqual(len(Collector.received), 1)
        with self.assertRaises(urllib.error.HTTPError):
            with collector(status=307) as url:
                debuglog.send(url + "/v1/logs", {})

    def test_a_failed_log_write_still_sends(self):
        with workspace() as root, collector() as url:
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": url}):
                with mock.patch.object(debuglog, "append", side_effect=OSError("disk full")):
                    debuglog.event("graph", "command", root, exit=0)
            self.assertEqual(len(Collector.received), 1)

    def test_a_sender_that_fails_in_http_is_ignored(self):
        with workspace() as root:
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": "http://localhost:4318"}):
                with mock.patch.object(debuglog, "send", side_effect=http.client.HTTPException("bad")):
                    debuglog.event("graph", "command", root, exit=0)


class Fetches(unittest.TestCase):
    def test_a_request_is_recorded_without_its_query(self):
        with workspace() as root:
            os.chdir(root)
            try:
                debuglog.fetched("arxiv", "https://export.arxiv.org/api/query?search_query=secret", 200)
            finally:
                os.chdir(Path(__file__).parent)
            (rec,) = logged(root)
        self.assertEqual((rec["source"], rec["event"]), ("arxiv", "http"))
        self.assertEqual((rec["host"], rec["path"], rec["status"]), ("export.arxiv.org", "/api/query", 200))
        self.assertNotIn("secret", json.dumps(rec))
        self.assertNotIn("duration_ms", rec)

    def test_a_url_without_a_host_records_an_empty_host(self):
        with workspace() as root:
            os.chdir(root)
            try:
                debuglog.fetched("arxiv", "/just/a/path", 200)
            finally:
                os.chdir(Path(__file__).parent)
            (rec,) = logged(root)
        self.assertEqual(rec["host"], "")

    def test_a_request_can_carry_its_duration(self):
        with workspace() as root:
            os.chdir(root)
            try:
                with mock.patch("time.monotonic", return_value=12.5):
                    debuglog.fetched("s2", "https://api.semanticscholar.org/graph/v1/paper/x", 200, 10.0)
            finally:
                os.chdir(Path(__file__).parent)
            self.assertEqual(logged(root)[0]["duration_ms"], 2500)

    def test_a_failure_records_the_status_or_a_network_error(self):
        with workspace() as root:
            os.chdir(root)
            try:
                debuglog.fetch_failed(
                    "s2", "https://api.semanticscholar.org/x", urllib.error.HTTPError("u", 429, "m", {}, None)
                )
                debuglog.fetch_failed("s2", "https://api.semanticscholar.org/x", urllib.error.URLError("down"))
                debuglog.fetch_failed("s2", "https://api.semanticscholar.org/x", TimeoutError())
            finally:
                os.chdir(Path(__file__).parent)
            self.assertEqual([rec["status"] for rec in logged(root)], [429, "network error", "network error"])


class Commands(unittest.TestCase):
    def test_a_command_records_its_exit_code_duration_and_notes(self):
        def main(argv):
            debuglog.note(command=argv[0])
            return 3

        with workspace() as root:
            os.chdir(root)
            try:
                with mock.patch("time.monotonic", side_effect=[2.0, 10.5]):
                    self.assertEqual(debuglog.run("graph", main, ["stats"]), 3)
            finally:
                os.chdir(Path(__file__).parent)
            (rec,) = logged(root)
        self.assertEqual(
            {key: rec[key] for key in rec if key != "time"},
            {"source": "graph", "event": "command", "exit": 3, "duration_ms": 8500, "command": "stats"},
        )

    def test_notes_do_not_carry_over_to_the_next_run(self):
        with workspace() as root:
            os.chdir(root)
            try:
                debuglog.run("a", lambda argv: debuglog.note(command="one") or 0, [])
                debuglog.run("b", lambda argv: 0, [])
            finally:
                os.chdir(Path(__file__).parent)
            self.assertEqual([rec.get("command") for rec in logged(root)], ["one", None])

    def test_a_crash_is_recorded_and_raised_again(self):
        def main(argv):
            raise KeyError("x")

        with workspace() as root:
            os.chdir(root)
            try:
                with self.assertRaises(KeyError):
                    debuglog.run("graph", main, [])
            finally:
                os.chdir(Path(__file__).parent)
            (rec,) = logged(root)
        self.assertEqual((rec["exit"], rec["error"]), ("error", "KeyError"))
        self.assertIn("duration_ms", rec)

    def recorded(self, *messages, code=1):
        """Run a main that prints messages to standard error and returns code; give back its event and what the real
        standard error received."""

        def main(argv):
            for message in messages:
                print(message, file=sys.stderr)
            return code

        with workspace() as root:
            os.chdir(root)
            try:
                with mock.patch.object(sys, "stderr", Out()) as err:
                    debuglog.run("graph", main, [])
                    self.assertIs(sys.stderr, err)
            finally:
                os.chdir(Path(__file__).parent)
            (rec,) = logged(root)
        return rec, err.getvalue()

    def test_a_failed_command_records_its_error_line_and_still_prints_it(self):
        message = "error: already in the graph: concept:attention"
        rec, printed = self.recorded("usage: graph.py add ...", message)
        self.assertEqual(rec["reason"], "error: already in the graph: …")
        self.assertEqual(printed, f"usage: graph.py add ...\n{message}\n")

    def test_without_an_error_line_the_first_line_is_the_reason(self):
        rec, _ = self.recorded("", "possible duplicates:", "  concept:attention", code=3)
        self.assertEqual(rec["reason"], "possible duplicates:")

    def test_the_reason_starts_at_error_after_a_program_name(self):
        rec, _ = self.recorded("graph.py: error: argument --type: invalid choice: 'x'", code=2)
        self.assertEqual(rec["reason"], "error: argument --type: invalid choice: '…'")

    def test_quoted_values_and_query_strings_are_left_out_of_the_reason(self):
        cases = {
            "no matches for 'secret search'": "no matches for '…'",
            'error: no entity matches "paper:1"; try search': "error: no entity matches '…'; try search",
            "error: can't read 'a b': it's gone": "error: can't read '…': it's gone",
            "error: HTTP 503 from https://export.arxiv.org/api/query?search_query=secret&max=5": (
                "error: HTTP 503 from https://export.arxiv.org/api/query?…"
            ),
            "error: no 'x?y' here?": "error: no '…' here?…",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(self.recorded(message)[0]["reason"], expected)

    def test_unquoted_ids_paths_and_extra_arguments_are_left_out_of_the_reason(self):
        cases = {
            "error: can't link insight:keep-the-review-agent-read-only supports paper:x: wrong ends": (
                "error: can't link … supports …: wrong ends"
            ),
            "error: no relation concept:my-idea uses tool:b.": "error: no relation … uses ….",
            "error: workspace not found: C:\\Users\\someone\\notes": "error: workspace not found: …",
            "error: research folder not found: /home/someone/my notes/research": (
                "error: research folder not found: … …"
            ),
            "error: HTTPS://Example.org/a/b failed": "error: HTTPS://Example.org/a/b failed",
            "error: http://127.0.0.1:4318/v1/logs refused": "error: http://127.0.0.1:4318/v1/logs refused",
            "graph.py: error: unrecognized arguments: --bogus private words": "error: unrecognized arguments: …",
            "graph.py: error: ambiguous option: --no=private words could match --note, --no-authors": (
                "error: ambiguous option: …"
            ),
            "error: the following arguments are required: query": "error: the following arguments are required: query",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(self.recorded(message)[0]["reason"], expected)

    def exited(self, stop):
        """Run a main that prints a usage error and raises stop; give back its event and what was printed."""

        def main(argv):
            print("usage: graph.py stats", file=sys.stderr)
            raise stop

        with workspace() as root, mock.patch.object(sys, "stderr", Out()) as err:
            os.chdir(root)
            try:
                with self.assertRaises(SystemExit) as raised:
                    debuglog.run("graph", main, [])
            finally:
                os.chdir(Path(__file__).parent)
            self.assertIs(raised.exception, stop)
            self.assertIs(sys.stderr, err)
            (rec,) = logged(root)
        return rec, err.getvalue()

    def test_a_usage_error_is_recorded_with_its_reason_and_raised_again(self):
        def main(argv):
            debuglog.note(command="search")
            return argparse.ArgumentParser(prog="graph.py").parse_args(argv) and 0  # exits on the wrong flag first

        with workspace() as root, mock.patch.object(sys, "stderr", Out()) as err:
            os.chdir(root)
            try:
                with self.assertRaises(SystemExit) as raised:
                    debuglog.run("graph", main, ["--bogus", "private words"])
            finally:
                os.chdir(Path(__file__).parent)
            (rec,) = logged(root)
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("private words", err.getvalue())  # the user still sees the whole message
        self.assertEqual(
            {key: rec[key] for key in ("command", "exit", "reason")},
            {"command": "search", "exit": 2, "reason": "error: unrecognized arguments: …"},
        )
        self.assertIn("duration_ms", rec)

    def test_an_exit_with_a_message_records_the_message_as_the_reason(self):
        rec, printed = self.exited(SystemExit("error: stopped at concept:my-idea"))
        self.assertEqual((rec["exit"], rec["reason"]), (1, "error: stopped at …"))
        self.assertEqual(printed, "usage: graph.py stats\n")

    def test_an_exit_without_a_code_is_a_success_with_no_reason(self):
        for stop in (SystemExit(), SystemExit(0)):
            with self.subTest(code=stop.code):
                rec, _ = self.exited(stop)
                self.assertEqual(rec["exit"], 0)
                self.assertNotIn("reason", rec)

    def test_a_success_or_a_silent_failure_has_no_reason(self):
        self.assertNotIn("reason", self.recorded("2 invisible characters removed", code=0)[0])
        self.assertNotIn("reason", self.recorded(code=1)[0])
        self.assertNotIn("reason", self.recorded("   ", code=1)[0])

    def test_only_the_start_of_standard_error_is_kept(self):
        self.assertEqual(debuglog.KEPT, 2000)  # enough for the error line after a long usage message
        kept = debuglog.Kept(Out())
        kept.write("x" * (debuglog.KEPT - 1))
        kept.write("yz")
        kept.write("more")
        self.assertEqual(kept.text, "x" * (debuglog.KEPT - 1) + "y")
        self.assertEqual(kept.stream.getvalue(), "x" * (debuglog.KEPT - 1) + "yzmore")

    def test_standard_error_is_restored_after_a_crash_and_keeps_its_methods(self):
        def main(argv):
            sys.stderr.reconfigure(encoding="utf-8")
            raise KeyError("x")

        with workspace() as root, mock.patch.object(sys, "stderr", Out()) as err:
            os.chdir(root)
            try:
                with self.assertRaises(KeyError):
                    debuglog.run("graph", main, [])
            finally:
                os.chdir(Path(__file__).parent)
            self.assertIs(sys.stderr, err)
            (rec,) = logged(root)
        self.assertNotIn("reason", rec)


class CommandLine(unittest.TestCase):
    def run_main(self, root, *args):
        out, err = Out(), Out()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            code = debuglog.main(["--workspace", str(root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_on_and_off_switch_recording(self):
        with workspace(on=False) as root:
            code, out, _ = self.run_main(root, "on")
            self.assertEqual(code, 0)
            self.assertTrue((root / "research" / ".debug").exists())
            self.assertRegex(out, r"debug is on since \d{4}-\d\d-\d\dT")
            self.assertIn(str(root / "research" / ".debug.log"), out)
            self.assertEqual(self.run_main(root, "off")[:2], (0, "debug is off\n"))
            self.assertFalse((root / "research" / ".debug").exists())
            self.assertEqual(self.run_main(root, "off")[0], 0)

    def test_on_says_where_events_are_also_sent(self):
        with workspace(on=False) as root:
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": "http://localhost:4318"}):
                out = self.run_main(root, "on")[1]
        self.assertIn(".debug.log and to http://127.0.0.1:4318/v1/logs", out)

    def test_status_says_what_is_on_and_how_big_the_log_is(self):
        with workspace(on=False) as root:
            out = self.run_main(root, "status")[1]
            self.assertIn("debug is off", out)
            self.assertIn("log: 0 bytes of at most 4000000", out)
            self.assertIn("export: none", out)
            debuglog.event("s", "e", root)
            (root / "research" / ".debug").write_text("on\n", encoding="utf-8")
            debuglog.event("s", "e", root)
            (root / "research" / ".debug.log.1").write_text("12345", encoding="utf-8")
            size = (root / "research" / ".debug.log").stat().st_size + 5
            with mock.patch.dict(os.environ, {"PAPER_RESEARCH_OTLP_ENDPOINT": "http://127.0.0.1:4318"}):
                out = self.run_main(root, "status")[1]
        self.assertIn("debug is on", out)
        self.assertIn(f"log: {size} bytes", out)
        self.assertIn("export: http://127.0.0.1:4318/v1/logs", out)

    def test_show_prints_the_latest_events_from_both_files(self):
        with workspace() as root:
            research = root / "research"
            (research / ".debug.log.1").write_text("old1\nold2\n", encoding="utf-8")
            (research / ".debug.log").write_text("new1\nnew2\n", encoding="utf-8")
            self.assertEqual(self.run_main(root, "show")[1], "old1\nold2\nnew1\nnew2\n")
            self.assertEqual(self.run_main(root, "show", "--lines", "3")[1], "old2\nnew1\nnew2\n")
            (research / ".debug.log.1").unlink()
            self.assertEqual(self.run_main(root, "show", "--lines", "1")[1], "new2\n")

    def test_show_prints_fifty_lines_by_default(self):
        with workspace() as root:
            lines = [f"line{n}" for n in range(60)]
            (root / "research" / ".debug.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
            shown = self.run_main(root, "show")[1].splitlines()
        self.assertEqual(shown, lines[-50:])

    def test_show_is_found_by_its_name_not_by_identity(self):
        with workspace() as root:
            (root / "research" / ".debug.log").write_text("a\nb\n", encoding="utf-8")
            self.assertEqual(self.run_main(root, "".join(["sh", "ow"]), "--lines", "1")[1], "b\n")

    def test_a_command_is_required(self):
        with workspace() as root, self.assertRaises(SystemExit) as stop:
            self.run_main(root)
        self.assertEqual(stop.exception.code, 2)

    def test_show_with_no_log_prints_nothing(self):
        with workspace() as root:
            self.assertEqual(self.run_main(root, "show")[:2], (0, ""))

    def test_clear_deletes_both_files(self):
        with workspace() as root:
            research = root / "research"
            (research / ".debug.log").write_text("a", encoding="utf-8")
            (research / ".debug.log.1").write_text("b", encoding="utf-8")
            self.assertEqual(self.run_main(root, "clear")[:2], (0, "log cleared\n"))
            self.assertFalse((research / ".debug.log").exists() or (research / ".debug.log.1").exists())
            self.assertTrue((research / ".debug").exists())
            self.assertEqual(self.run_main(root, "clear")[0], 0)

    def test_a_folder_without_research_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err = self.run_main(folder, "status")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("error: research folder not found:", err)

    def test_run_as_a_program(self):
        with workspace(on=False) as root:
            os.chdir(root)
            try:
                with (
                    mock.patch.object(sys, "argv", ["debuglog.py", "status"]),
                    contextlib.redirect_stdout(Out()) as out,
                ):
                    with self.assertRaises(SystemExit) as stop:
                        runpy.run_path(debuglog.__file__, run_name="__main__")
            finally:
                os.chdir(Path(__file__).parent)
        self.assertEqual(stop.exception.code, 0)
        self.assertIn("debug is off", out.getvalue())


class Flags(unittest.TestCase):
    def test_no_parser_accepts_a_shortened_flag(self):
        # A shortened flag would be guessed, and argparse's message for an ambiguous one repeats its value.
        parsers = [debuglog.build_parser()]
        for parser in parsers:
            self.assertFalse(parser.allow_abbrev, parser.prog)
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    parsers.extend(action.choices.values())
        self.assertEqual(len(parsers), 6)


if __name__ == "__main__":
    unittest.main()
