"""Offline checks of the Grafana dashboards in telemetry/dashboards. Run: python tools/test_dashboards.py

Grafana loads these files as they are, so a broken link, an overlapping panel, or a regex that flags harmless
commands would only show up in the browser. These tests catch them first.
"""

import contextlib
import importlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for folder in ("arxiv", "scholar"):
    sys.path.insert(0, str(ROOT / "skills" / folder / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "debug" / "scripts"))

FOLDER = ROOT / "telemetry" / "dashboards"
DATASOURCES = {"loki", "tempo", "prometheus", "pyroscope"}  # the uids the grafana/otel-lgtm image provisions
WIDTH = 24  # Grafana's grid columns


def load(name):
    return json.loads((FOLDER / name).read_text(encoding="utf-8"))


def dashboards():
    return {path.name: load(path.name) for path in sorted(FOLDER.glob("*.json"))}


def panels(dashboard):
    """Every panel, including those inside a collapsed row."""
    for panel in dashboard["panels"]:
        yield panel
        yield from panel.get("panels", [])


def by_title(dashboard, title, kind):
    return next(p for p in panels(dashboard) if p["title"] == title and p["type"] == kind)


def pattern_after(expr, label):
    """The regex a LogQL label filter such as full_command=~`...` matches, as Python can compile it."""
    found = re.search(label + r"=~`([^`]*)`", expr)
    assert found, f"no {label}=~ filter in {expr}"
    return re.compile(found.group(1))


# What Python's regex engine accepts and RE2 doesn't: lookahead and lookbehind, atomic groups, a named back-reference,
# and possessive quantifiers.
RE2_LACKS = re.compile(r"\(\?(?:=|!|<=|<!|>|P=)|[*+?]\+|\{\d+(?:,\d*)?\}\+")
FILTER_PART = re.compile(r'\(|\)|\band\b|\bor\b|\w+(?:=~|!~|!=|=)"(?:[^"\\]|\\.)*"')


def part_holds(part, labels):
    """One test of a label filter, such as a!="1" or b=~"x.*". A regex must match the whole value, as in Loki, and a
    label a line doesn't have is empty.

    A value is taken as written. Loki reads a backslash in a double-quoted value as an escape, such as \\" or \\\\,
    and this doesn't, so a value with one is refused rather than read wrongly.

    A regex is matched with Python's engine, and Loki uses RE2, which agrees on the patterns the dashboards use but not
    on everything. A pattern with a feature RE2 lacks is refused, as it could pass here and behave differently there."""
    found = re.fullmatch(r'(\w+)(=~|!~|!=|=)"(.*)"', part)
    assert found, part
    name, sign, value = found.groups()
    assert "\\" not in value, f"{part}: the reader doesn't unescape a value, so it can't check this filter"
    assert not ("~" in sign and RE2_LACKS.search(value)), f"{part}: RE2, Loki's engine, doesn't support this pattern"
    actual = labels.get(name, "")
    matched = re.fullmatch(value, actual) is not None if "~" in sign else actual == value
    return matched == (sign in ("=", "=~"))


class LabelFilter:
    """Reads a LogQL label filter such as a="1" or (b!="2" and c=~"x.*"): tests joined by and and or, and brackets.
    And binds tighter than or."""

    def __init__(self, stage, labels):
        self.parts = FILTER_PART.findall(stage)
        assert "".join(self.parts).replace(" ", "") == stage.replace(" ", ""), f"can't read all of {stage!r}"
        self.labels = labels
        self.at = 0

    def take(self):
        self.at += 1
        return self.parts[self.at - 1]

    def next_is(self, word):
        return self.at < len(self.parts) and self.parts[self.at] == word

    def holds(self):
        result = self.either()
        assert self.at == len(self.parts), f"left over: {self.parts[self.at :]}"
        return result

    def either(self):
        result = self.both()
        while self.next_is("or"):
            self.take()
            result = self.both() or result
        return result

    def both(self):
        result = self.one()
        while self.next_is("and"):
            self.take()
            result = self.one() and result
        return result

    def one(self):
        part = self.take()
        if part != "(":
            return part_holds(part, self.labels)
        result = self.either()
        assert self.take() == ")", "a bracket is not closed"
        return result


def keeps(expr, labels):
    """Whether a query's label filters, such as | a="1" | b!="2" or (c="3" and d=~"x.*"), keep a line with these
    labels."""
    stages = expr.split(" [", 1)[0].split(" | ")[1:]
    return all(LabelFilter(stage, labels).holds() for stage in stages)


def cells(panel):
    x, y, w, h = (panel["gridPos"][k] for k in ("x", "y", "w", "h"))
    return {(col, line) for col in range(x, x + w) for line in range(y, y + h)}


class Files(unittest.TestCase):
    def test_there_are_three_dashboards_with_their_own_uids(self):
        uids = [d["uid"] for d in dashboards().values()]
        self.assertEqual(len(uids), 3)
        self.assertEqual(len(set(uids)), 3)

    def test_each_links_to_the_two_others(self):
        found = dashboards().values()
        uids = {d["uid"] for d in found}
        for dashboard in found:
            targets = {link["url"].removeprefix("/d/") for link in dashboard["links"]}
            self.assertEqual(targets, uids - {dashboard["uid"]}, dashboard["title"])

    def test_compose_mounts_the_folder_that_grafana_reads(self):
        provider = (ROOT / "telemetry" / "dashboards.yaml").read_text(encoding="utf-8")
        compose = (ROOT / "telemetry" / "docker-compose.yml").read_text(encoding="utf-8")
        path = re.search(r"path: (\S+)", provider)
        assert path
        self.assertIn(f"./dashboards:{path.group(1)}", compose)


class Panels(unittest.TestCase):
    def test_panel_ids_are_unique(self):
        for name, dashboard in dashboards().items():
            ids = [p["id"] for p in panels(dashboard)]
            self.assertEqual(len(ids), len(set(ids)), name)

    def test_panels_fit_the_grid_and_do_not_overlap(self):
        for name, dashboard in dashboards().items():
            taken: set = set()
            for panel in dashboard["panels"]:  # a collapsed row's panels are placed only when it opens
                with self.subTest(name, panel=panel["title"]):
                    self.assertLessEqual(panel["gridPos"]["x"] + panel["gridPos"]["w"], WIDTH)
                    self.assertFalse(cells(panel) & taken)
                    taken |= cells(panel)

    def test_every_query_uses_a_provisioned_datasource(self):
        for name, dashboard in dashboards().items():
            for panel in panels(dashboard):
                for target in panel.get("targets", []):
                    with self.subTest(name, panel=panel["title"]):
                        self.assertIn(target["datasource"]["uid"], DATASOURCES)

    def test_every_data_panel_says_what_it_counts(self):
        for name, dashboard in dashboards().items():
            for panel in panels(dashboard):
                if panel.get("targets"):
                    with self.subTest(name, panel=panel["title"]):
                        self.assertTrue(panel.get("description"))


class Alarms(unittest.TestCase):
    """The security alarms turn red on any match, so a harmless command must not match."""

    usage = load("paper-research.json")

    def test_risky_commands_match_whole_words_in_the_command(self):
        risky = pattern_after(by_title(self.usage, "Risky commands", "stat")["targets"][0]["expr"], "full_command")
        for command in (
            "curl https://example.com",
            "rm -rf build",
            "cat .env",
            "nc -l 4444",
            "SUDO ls",
            "ls\nwget http://x",
            "Invoke-WebRequest -Uri x",
            "cat ~/.ssh/id_rsa",
            "cd x && curl -s y",
            "rm -fr build",
            "Remove-Item build -Recurse -Force",
            "$page = Invoke-WebRequest https://example.com",
            "cat .env.local",
            "/usr/bin/curl x",
            "bash -c 'curl x'",
            "FOO=1 curl x",
            "rm -r -f b",
            "rm -f -r b",
            "curl.exe -s x",
            "echo `curl x`",
            "x=$(curl x)",
            'sh -c "wget x"',
        ):
            self.assertTrue(risky.fullmatch(command), command)
        for command in (
            "rsync -a a b",
            "python -c 'import asyncio'",
            "echo $HOME/.environ",
            "cat <<'EOF'\ncat notes.md\nEOF",
            "python graph.py stats",
            "sshd_config_reader",
            "git log -- docs/curl.md",
            "cat .env.example",
            "cat .env.sample .env.template",
            "curl.md",
            "cat nc.txt",
            "Remove-Item build",
            "rm -r build",
        ):
            self.assertFalse(risky.fullmatch(command), command)

    def test_a_program_named_in_an_argument_is_accepted_as_a_hit(self):
        # The program must follow a space, quote or slash to catch bash -c 'curl x' and /usr/bin/curl, so a bare
        # word such as echo curl matches too. An alarm for visibility, not enforcement, accepts that.
        risky = pattern_after(by_title(self.usage, "Risky commands", "stat")["targets"][0]["expr"], "full_command")
        self.assertTrue(risky.fullmatch("echo curl"))

    def test_sensitive_files_match_secret_looking_paths_only(self):
        expr = by_title(self.usage, "Sensitive file access", "stat")["targets"][0]["expr"]
        sensitive = pattern_after(expr, "file_path")
        self.assertEqual(sensitive.pattern, pattern_after(expr, "notebook_path").pattern)
        for path in (
            "/home/u/.env",
            "C:\\Users\\u\\.ssh\\config",
            "secrets.yaml",
            "token.json",
            "a/.aws/credentials",
            "server.pem",
            "id_ed25519",
            "app/.env.production",
        ):
            self.assertTrue(sensitive.fullmatch(path), path)
        for path in (
            "skills/tokenizer.py",
            "src/environment.py",
            "docs/keys.md",
            "research/papers.md",
            "secretary.txt",
            "src/max_tokens.py",
            "tests/test_secrets.py",
            "docs/token-budget.md",
            "app/.env.example",
            "app/.env.sample",
            "app/.env.template",
            "keys/id_rsa.pub",
        ):
            self.assertFalse(sensitive.fullmatch(path), path)

    def test_the_log_panels_use_the_same_filter_as_their_alarm(self):
        pairs = (("Risky commands", "Risky shell commands"), ("Sensitive file access", "Sensitive file access"))
        for stat, log in pairs:
            count = by_title(self.usage, stat, "stat")["targets"][0]["expr"]
            lines = by_title(self.usage, log, "logs")["targets"][0]["expr"]
            selector = lines.rsplit(" | line_format", 1)[0]
            self.assertIn(selector, count, stat)


class Patterns(unittest.TestCase):
    def test_every_regex_stays_within_what_loki_understands(self):
        # The tests above use Python's re, but Loki uses Go's RE2, which has no lookarounds or backreferences. A
        # pattern with one compiles here and fails in Grafana, so none may be written.
        unsupported = re.compile(r"\(\?<?[=!]|\\[1-9]|\(\?P?=|\(\?>")
        for name, dashboard in dashboards().items():
            for panel in panels(dashboard):
                for target in panel.get("targets", []):
                    for pattern in re.findall(r"=~`([^`]*)`", target.get("expr", "")):
                        with self.subTest(name, panel=panel["title"]):
                            self.assertIsNone(unsupported.search(pattern), pattern)


class PluginVersions(unittest.TestCase):
    def test_only_sessions_that_ran_a_plugin_skill_are_compared(self):
        panel = by_title(load("paper-research.json"), "Plugin versions", "table")
        keeps = [
            step["options"]["filters"][0]["fieldName"]
            for step in panel["transformations"]
            if step["id"] == "filterByValue"
        ]
        self.assertEqual(keeps, ["plugin_version", "Value #C"])
        self.assertIn("skill_activated", panel["targets"][2]["expr"])


class Requests(unittest.TestCase):
    def test_rate_limits_are_not_counted_as_failed_requests(self):
        debug = load("paper-research-debug.json")
        failed = by_title(debug, "Failed requests", "stat")["targets"][0]["expr"]
        limited = by_title(debug, "Rate limited", "stat")["targets"][0]["expr"]
        self.assertIn('status!="429"', failed)
        self.assertIn('status="429"', limited)

    def test_only_a_request_that_got_no_answer_or_an_error_is_failed(self):
        failed = by_title(load("paper-research-debug.json"), "Failed requests", "stat")["targets"][0]["expr"]
        for status, expected in (
            ("200", False),
            ("429", False),
            ("400", True),
            ("403", True),
            ("500", True),
            ("503", True),
            ("network error", True),
        ):
            with self.subTest(status=status):
                self.assertEqual(keeps(failed, {"event_name": "http", "status": status, "path": "/x"}), expected)

    def test_only_the_two_not_founds_that_are_answers_are_left_out_of_failed_requests(self):
        failed = by_title(load("paper-research-debug.json"), "Failed requests", "stat")["targets"][0]["expr"]
        for path, expected in (
            ("/graph/v1/paper/search/match", False),  # s2.py match: no title is close enough
            ("/html/2401.00001", False),  # arxiv.py fetch: the paper has no HTML version
            ("/html/hep-th/9901001v2", False),
            ("/graph/v1/paper/x", True),  # s2.py paper: an id that is mistyped or misparsed
            ("/graph/v1/paper/search/match/extra", True),  # an address that has changed
            ("/graph/v2/paper/search/match", True),
            ("/pdf/2401.00001", True),  # a PDF that can't be found is not an answer
            ("/htmlx/2401.00001", True),  # only the folder /html/ is
            ("/api/query", True),
            ("", True),
        ):
            with self.subTest(path=path):
                self.assertEqual(keeps(failed, {"event_name": "http", "status": "404", "path": path}), expected)
        # A line with no path (an event from before it was recorded) is a failure too, not a pass.
        self.assertTrue(keeps(failed, {"event_name": "http", "status": "404"}))

    def test_the_filter_reader_follows_logql(self):
        # The reader the dashboard tests rely on: and before or, brackets, regexes that match the whole value, and a
        # label that a line doesn't have is empty.
        cases: tuple[tuple[str, dict[str, str], bool], ...] = (
            ('a="1" or b="2" and c="3"', {"a": "x", "b": "2", "c": "9"}, False),
            ('a="1" or b="2" and c="3"', {"a": "1", "b": "2", "c": "9"}, True),
            ('(a="1" or b="2") and c="3"', {"a": "1", "c": "9"}, False),
            ('(a="1" or b="2") and c="3"', {"b": "2", "c": "3"}, True),
            ('a=~"x.*"', {"a": "xyz"}, True),
            ('a=~"x"', {"a": "xyz"}, False),
            ('a!~"x.*"', {"a": "xyz"}, False),
            ('a!~"x.*"', {"a": "yz"}, True),
            ('a=""', {}, True),
            ('a!="1"', {}, True),
            ('a=~".+"', {}, False),
        )
        for stage, labels, expected in cases:
            with self.subTest(stage=stage, labels=labels):
                self.assertEqual(LabelFilter(stage, labels).holds(), expected)
        for broken in ('a="1" or', '(a="1"', 'a="1" b="2"', "garbage"):
            with self.subTest(broken=broken), self.assertRaises((AssertionError, IndexError)):
                LabelFilter(broken, {}).holds()

    def test_the_filter_reader_refuses_an_escape_instead_of_reading_it_wrongly(self):
        # Loki turns \" into a quote and \\ into a backslash. The reader doesn't, so it must say so: read as written,
        # a filter such as a="x\"y" would compare against the wrong text and pass or fail for the wrong reason.
        for stage in ('a="x\\"y"', 'a=~"\\\\d+"', 'a="C:\\\\"', 'a!="\\"" or b="1"'):
            with self.subTest(stage=stage), self.assertRaisesRegex(AssertionError, "doesn't unescape"):
                LabelFilter(stage, {"a": "x", "b": "1"}).holds()
        # The same shapes without an escape are read.
        for stage, labels, expected in (('a="xy"', {"a": "xy"}, True), ('a=~"x.+"', {"a": "xyz"}, True)):
            self.assertEqual(LabelFilter(stage, labels).holds(), expected)

    def test_the_filter_reader_refuses_a_regex_feature_that_re2_lacks(self):
        # Python's engine and Loki's RE2 agree on the patterns the dashboards use. A feature only Python has could pass
        # here and behave differently in Loki, so the reader says so instead.
        for pattern in (
            "a(?=b)",
            "(?!x).*",
            "(?<=a)b",
            "(?<!a)b",
            "(?>a+)b",
            "a*+",
            "a++b",
            "a?+",
            "(a)(?P=n)",
            "x{2}+",
            "x{2,}+",
        ):
            with self.subTest(pattern=pattern), self.assertRaisesRegex(AssertionError, "RE2"):
                LabelFilter(f'a=~"{pattern}"', {"a": "x"}).holds()
        # What both engines have is read: groups, classes, lazy and greedy repeats, alternation, anchors, and a flag.
        for pattern, text in (
            ("(?:a|b)+c", "abc"),
            ("(?i)ab", "AB"),
            ("[.]x.*?", ".x"),
            ("a+?b", "aab"),
            ("x{2,3}", "xxx"),
            ("(a|b)*", "abba"),
            ("^a.*z$", "abcz"),
            ("[^/]+/.*", "ab/cd"),
            ("x}+", "x}}"),  # a closing brace with no repeat before it is only text
        ):
            with self.subTest(pattern=pattern):
                self.assertTrue(LabelFilter(f'a=~"{pattern}"', {"a": text}).holds())
        # An equality isn't a regex: a value that looks like a refused pattern is only text there.
        self.assertTrue(LabelFilter('a="a(?=b)"', {"a": "a(?=b)"}).holds())
        self.assertTrue(LabelFilter('a!="a++"', {"a": "x"}).holds())

    def test_the_stats_the_tests_evaluate_use_no_escape_the_reader_would_refuse(self):
        debug = load("paper-research-debug.json")
        for title in ("Failed commands", "Possible duplicates", "Failed requests", "Rate limited"):
            with self.subTest(title):
                expr = by_title(debug, title, "stat")["targets"][0]["expr"]
                self.assertNotIn("\\", expr)
                self.assertIn(keeps(expr, {"event_name": "x"}), (True, False))  # it reads the whole filter

    def test_a_not_found_is_still_listed_by_status(self):
        hosts = by_title(load("paper-research-debug.json"), "Hosts the plugin contacted", "table")
        expr = hosts["targets"][0]["expr"]
        self.assertIn("sum by (host, status)", expr)
        self.assertNotIn("status!=", expr)


class Commands(unittest.TestCase):
    def test_possible_duplicates_are_not_counted_as_failed_commands(self):
        debug = load("paper-research-debug.json")
        failed = by_title(debug, "Failed commands", "stat")["targets"][0]["expr"]
        asked = by_title(debug, "Possible duplicates", "stat")["targets"][0]["expr"]
        self.assertIn('exit!="0" | source!="graph" or exit!="3"', failed)
        self.assertIn('source="graph" | exit="3"', asked)

    def test_every_failed_run_is_counted_in_one_of_the_two_stats(self):
        debug = load("paper-research-debug.json")
        failed = by_title(debug, "Failed commands", "stat")["targets"][0]["expr"]
        asked = by_title(debug, "Possible duplicates", "stat")["targets"][0]["expr"]
        for source, code, expected in (
            ("graph", "3", (False, True)),
            ("arxiv", "3", (True, False)),
            ("graph", "1", (True, False)),
            ("init", "2", (True, False)),
            ("graph", "0", (False, False)),
        ):
            with self.subTest(source=source, exit=code):
                run = {"event_name": "command", "source": source, "exit": code}
                self.assertEqual((keeps(failed, run), keeps(asked, run)), expected)

    def test_duplicate_decisions_list_the_adds_that_held_or_were_given_distinct(self):
        panel = by_title(load("paper-research-debug.json"), "Duplicate decisions by graph add", "logs")
        expr = panel["targets"][0]["expr"]
        self.assertIn('source="graph" | command="add"', expr)
        counts = re.compile(r"[1-9][0-9]*")
        self.assertEqual(pattern_after(expr, "candidates").pattern, counts.pattern)
        self.assertEqual(pattern_after(expr, "distinct").pattern, counts.pattern)
        # Counts of 0 and a missing count (an add from before the counts) are left out; any other count is kept.
        for value, kept in (("0", False), ("", False), ("1", True), ("13", True), ("10", True)):
            with self.subTest(value=value):
                self.assertEqual(bool(counts.fullmatch(value)), kept)

    def test_failures_are_listed_with_their_reason(self):
        panel = by_title(load("paper-research-debug.json"), "Failures by reason", "table")
        self.assertIn("sum by (source, command, exit, reason, error)", panel["targets"][0]["expr"])
        self.assertIn('exit!="0"', panel["targets"][0]["expr"])

    def test_the_debug_dashboard_says_where_model_use_is(self):
        text = next(p for p in panels(load("paper-research-debug.json")) if p["type"] == "text")
        content = text["options"]["content"]
        for title in ("paper-research: usage and security", "paper-research: service details"):
            self.assertIn(title, content)
            self.assertIn(title, [d["title"] for d in dashboards().values()])


def http_error(code):
    return urllib.error.HTTPError("https://example.org/x", code, "error", Message(), io.BytesIO(b"detail"))


class RecordedRequests(unittest.TestCase):
    """The scripts run with their requests answered, and the http events they really record go through the debug
    dashboard's own filters. The dashboard names two paths, so this is what stops them drifting from the scripts'
    addresses: a path that changes in a script would make an answer count as a failure here."""

    arxiv: ModuleType
    s2: ModuleType

    @classmethod
    def setUpClass(cls):
        # Imported here, so a script that fails to import fails these tests and not the dashboard tests above.
        cls.arxiv = importlib.import_module("arxiv")
        cls.s2 = importlib.import_module("s2")

    def setUp(self):
        s2, arxiv = self.s2, self.arxiv
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        (self.root / "research").mkdir()
        (self.root / "research" / ".debug").write_text("on", encoding="utf-8")
        before = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, before)
        # No collector and no API key, and no waiting between retries.
        names = ("PAPER_RESEARCH_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT", "SEMANTIC_SCHOLAR_API_KEY")
        clean_env = {key: value for key, value in os.environ.items() if key not in names}
        patches: list[Any] = [
            mock.patch.dict(os.environ, clean_env, clear=True),
            mock.patch.object(s2, "pace"),
            mock.patch.object(arxiv, "pace"),
            mock.patch("time.sleep"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        debug = load("paper-research-debug.json")
        self.failed = by_title(debug, "Failed requests", "stat")["targets"][0]["expr"]
        self.limited = by_title(debug, "Rate limited", "stat")["targets"][0]["expr"]

    def labels(self):
        """What Loki holds for each http event: its fields as labels, with the event's name as event_name."""
        lines = (self.root / "research" / ".debug.log").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines]
        return [
            {"event_name": event["event"], **{k: str(v) for k, v in event.items() if k not in ("event", "time")}}
            for event in events
            if event["event"] == "http"
        ]

    def run_script(self, module, argv, answers):
        (self.root / "research" / ".debug.log").unlink(missing_ok=True)  # only this run's events
        with mock.patch.object(module.OPENER, "open", side_effect=answers):
            out, err = (io.TextIOWrapper(io.BytesIO(), encoding="utf-8") for _ in range(2))
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                module.main(argv)
        return self.labels()

    def test_what_the_scripts_record_is_counted_as_the_dashboard_says(self):
        s2, arxiv = self.s2, self.arxiv
        too_many = s2.MAX_ATTEMPTS
        cases = (
            # name, script, command, answers, counted as failed, counted as rate limited
            ("match finds no close title", s2, ["match", "ReAct"], [http_error(404)], False, False),
            ("fetch finds no HTML version", arxiv, ["fetch", "2401.00001"], [http_error(404)], False, False),
            ("fetch of an old-style id with none", arxiv, ["fetch", "hep-th/9901001"], [http_error(404)], False, False),
            ("paper is given an unknown id", s2, ["paper", "ARXIV:2401.00001"], [http_error(404)], True, False),
            ("pdf finds no PDF", arxiv, ["pdf", "2401.00001"], [http_error(404)], True, False),
            ("match gets a server error", s2, ["match", "ReAct"], [http_error(500)] * too_many, True, False),
            ("match is refused", s2, ["match", "ReAct"], [http_error(403)], True, False),
            ("match gets no answer", s2, ["match", "ReAct"], [urllib.error.URLError("down")] * too_many, True, False),
            ("match is rate limited without a key", s2, ["match", "ReAct"], [http_error(429)], False, True),
            ("batch is answered", s2, ["batch", "ARXIV:2401.00001"], [io.BytesIO(b"[null]")], False, False),
        )
        for name, module, argv, answers, failed, limited in cases:
            with self.subTest(name):
                labels = self.run_script(module, argv, answers)
                self.assertTrue(labels, "the script recorded no http event")
                self.assertEqual(any(keeps(self.failed, line) for line in labels), failed, labels)
                self.assertEqual(any(keeps(self.limited, line) for line in labels), limited, labels)

    def test_the_two_paths_the_dashboard_names_are_the_addresses_the_scripts_ask_for(self):
        s2, arxiv = self.s2, self.arxiv
        match = self.run_script(s2, ["match", "ReAct"], [http_error(404)])
        html = self.run_script(arxiv, ["fetch", "2401.00001"], [http_error(404)])
        self.assertEqual([line["path"] for line in match], ["/graph/v1/paper/search/match"])
        self.assertEqual([line["path"] for line in html], ["/html/2401.00001"])
        expression = self.failed
        self.assertIn(match[0]["path"], expression)
        self.assertIn(html[0]["path"].rsplit("/", 1)[0] + "/", expression)


if __name__ == "__main__":
    unittest.main()
