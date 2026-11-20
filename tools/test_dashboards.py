"""Offline checks of the Grafana dashboards in telemetry/dashboards. Run: python tools/test_dashboards.py

Grafana loads these files as they are, so a broken link, an overlapping panel, or a regex that flags harmless
commands would only show up in the browser. These tests catch them first.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


if __name__ == "__main__":
    unittest.main()
