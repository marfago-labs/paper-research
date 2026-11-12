"""Offline tests for init.py. Run: python skills/init/scripts/test_init.py"""

import contextlib
import io
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import init


class Workspace(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def run_main(self, *argv):
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = init.main(["--workspace", str(self.root), *argv])
        out.seek(0)
        return code, out.read(), err.getvalue()

    def read(self, name):
        return (self.root / name).read_text(encoding="utf-8")


class FreshWorkspace(Workspace):
    def test_dry_run_writes_nothing(self):
        code, out, _ = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("create research/papers.md", out)
        self.assertIn("create CLAUDE.md", out)
        self.assertIn("nothing written (dry run)", out)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_sets_up_everything_then_is_idempotent(self):
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        for name in (
            "papers.md",
            "user-facts.md",
            "profile.md",
            "pins.md",
            "lessons.md",
            "insights.md",
            "graph/entities.jsonl",
            "graph/relations.jsonl",
        ):
            self.assertTrue((self.root / "research" / name).exists(), name)
        claude = self.read("CLAUDE.md")
        self.assertTrue(claude.startswith("# Paper research workspace"))
        self.assertIn(init.BEGIN, claude)
        self.assertIn("@research/lessons.md", claude)
        self.assertIn("`Published | Title | ID | Citations | Topic | Note`", claude)
        settings = json.loads(self.read(".claude/settings.json"))
        self.assertIn("WebFetch(domain:arxiv.org)", settings["permissions"]["ask"])
        self.assertNotIn("allow", settings["permissions"])
        self.assertEqual(settings["autoMode"]["soft_deny"][0], "$defaults")
        self.assertIn(".claude/settings.local.json", self.read(".gitignore").splitlines())
        self.assertEqual(self.run_main()[1].strip(), "workspace is up to date")


class ExistingWorkspace(Workspace):
    def test_keeps_instance_files_and_other_content(self):
        (self.root / "research").mkdir()
        (self.root / "research" / "papers.md").write_text("my papers\n", encoding="utf-8")
        (self.root / "CLAUDE.md").write_text("# Mine\n\nMy topics.\n", encoding="utf-8")
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["Bash(git *)", "WebFetch(domain:arxiv.org)"]}, "model": "x"}),
            encoding="utf-8",
        )
        (self.root / ".gitignore").write_text("node_modules/\n.cache/\n", encoding="utf-8")
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.read("research/papers.md"), "my papers\n")
        self.assertIn("update CLAUDE.md", out)
        self.assertTrue(self.read("CLAUDE.md").startswith("# Mine\n\nMy topics.\n\n" + init.BEGIN))
        settings = json.loads(self.read(".claude/settings.json"))
        self.assertEqual(settings["model"], "x")
        self.assertEqual(settings["permissions"]["allow"], ["Bash(git *)", "WebFetch(domain:arxiv.org)"])
        self.assertEqual(settings["permissions"]["ask"].count("WebFetch(domain:arxiv.org)"), 1)
        self.assertEqual(self.read(".gitignore").splitlines()[:2], ["node_modules/", ".cache/"])
        self.assertEqual(self.read(".gitignore").count(".cache/"), 1)

    def test_replaces_only_the_block(self):
        old = f"# Mine\n\nbefore\n\n{init.BEGIN}\nold rules\n{init.END}\n\nafter\n"
        (self.root / "CLAUDE.md").write_text(old, encoding="utf-8")
        (self.root / ".gitignore").write_text("", encoding="utf-8")
        code, out, _ = self.run_main("--dry-run")
        self.assertIn("-old rules", out)
        self.run_main()
        claude = self.read("CLAUDE.md")
        self.assertTrue(claude.startswith("# Mine\n\nbefore\n\n" + init.BEGIN))
        self.assertTrue(claude.endswith(init.END + "\nafter\n"))
        self.assertNotIn("old rules", claude)
        self.assertEqual(self.read(".gitignore").splitlines(), init.GITIGNORE)

    def test_keeps_existing_auto_mode_rules(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.json").write_text(
            json.dumps({"autoMode": {"soft_deny": ["$defaults", "Mine"]}}), encoding="utf-8"
        )
        self.run_main()
        soft = json.loads(self.read(".claude/settings.json"))["autoMode"]["soft_deny"]
        self.assertEqual(soft[:2], ["$defaults", "Mine"])
        self.assertEqual(soft.count("$defaults"), 1)

    def test_refuses_unsafe_files(self):
        shapes = [
            ["not an object"],
            {"permissions": []},
            {"permissions": {"allow": "all"}},
            {"autoMode": "on"},
            {"autoMode": {"soft_deny": "x"}},
        ]
        cases = [
            ("only one of the paper-research markers", "CLAUDE.md", f"text\n{init.END}\n{init.BEGIN}\n"),
            ("only one of the paper-research markers", "CLAUDE.md", f"text\n{init.BEGIN}\nno end\n"),
            ("only one of the paper-research markers", "CLAUDE.md", f"text\n{init.END}\nno begin\n"),
            ("not valid JSON", ".claude/settings.json", "{not json"),
            *[("unexpected shape", ".claude/settings.json", json.dumps(shape)) for shape in shapes],
        ]
        for expected, name, text in cases:
            with self.subTest(expected, name=name, text=text[:40]):
                for leftover in ("CLAUDE.md", ".claude/settings.json"):
                    (self.root / leftover).unlink(missing_ok=True)
                (self.root / name).parent.mkdir(exist_ok=True)
                (self.root / name).write_text(text, encoding="utf-8")
                code, out, err = self.run_main()
                self.assertEqual(code, 1)
                self.assertIn(expected, err)
                self.assertEqual(out, "")
                self.assertFalse((self.root / "research").exists())


class Hardening(Workspace):
    def write_settings(self, text):
        (self.root / ".claude").mkdir(exist_ok=True)
        (self.root / ".claude" / "settings.json").write_text(text, encoding="utf-8")

    def settings(self):
        return json.loads(self.read(".claude/settings.json"))

    def test_denies_no_tool_and_keeps_the_rule_against_sending_content_out(self):
        self.run_main()
        self.assertNotIn("deny", self.settings()["permissions"])
        self.assertIn("Sending workspace content", self.read(".claude/settings.json"))

    def test_the_template_allows_and_denies_nothing(self):
        template = init.load_template("settings.json")
        self.assertNotIn("deny", template["permissions"])
        self.assertNotIn("allow", template["permissions"])

    def test_existing_deny_rules_are_kept_once(self):
        self.write_settings(json.dumps({"permissions": {"deny": ["Mine", "Bash(rm -rf *)"]}}))
        self.run_main()
        deny = self.settings()["permissions"]["deny"]
        self.assertEqual(deny, ["Mine", "Bash(rm -rf *)"])

    def test_the_sandbox_is_opt_in(self):
        self.run_main()
        self.assertNotIn("sandbox", self.settings())

    def test_sandbox_flag_turns_it_on_for_the_fetch_hosts(self):
        self.write_settings(json.dumps({"sandbox": {"network": {"allowedDomains": ["example.org"]}}}))
        code, out, _ = self.run_main("--sandbox")
        self.assertEqual(code, 0)
        box = self.settings()["sandbox"]
        self.assertTrue(box["enabled"])
        self.assertFalse(box["allowUnsandboxedCommands"])
        self.assertEqual(box["network"]["allowedDomains"][0], "example.org")
        self.assertIn("arxiv.org", box["network"]["allowedDomains"])
        self.assertEqual(self.run_main("--sandbox")[1].strip(), "workspace is up to date")

    def test_the_sandbox_reaches_only_the_scripts_hosts(self):
        self.run_main("--sandbox")
        domains = self.settings()["sandbox"]["network"]["allowedDomains"]
        self.assertEqual(domains, ["arxiv.org", "export.arxiv.org", "api.semanticscholar.org"])

    def test_the_sandbox_denies_the_hosts_that_fetch_rules_would_open(self):
        # Claude Code opens the hosts of WebFetch(domain:...) allow rules to sandboxed commands too.
        self.write_settings(json.dumps({"sandbox": {"network": {"deniedDomains": ["example.org"]}}}))
        self.run_main("--sandbox")
        settings = self.settings()
        denied = settings["sandbox"]["network"]["deniedDomains"]
        self.assertEqual(denied[0], "example.org")
        for host in ("github.com", "*.github.com", "huggingface.co", "*.huggingface.co", "hf.co", "*.hf.co"):
            self.assertIn(host, denied)
        fetches = [rule for rule in settings["permissions"]["ask"] if rule.startswith("WebFetch(")]
        fetch_hosts = {rule[len("WebFetch(domain:") : -1] for rule in fetches}
        self.assertEqual(fetch_hosts - set(settings["sandbox"]["network"]["allowedDomains"]) - set(denied), set())
        self.assertEqual(self.run_main("--sandbox")[1].strip(), "workspace is up to date")

    def test_the_sandbox_cannot_write_the_files_that_become_instructions(self):
        self.write_settings(json.dumps({"sandbox": {"filesystem": {"denyWrite": ["/etc"]}}}))
        self.run_main("--sandbox")
        denied = self.settings()["sandbox"]["filesystem"]["denyWrite"]
        self.assertEqual(denied[0], "/etc")
        for path in ("./research/lessons.md", "./research/profile.md", "./CLAUDE.md"):
            self.assertEqual(denied.count(path), 1, path)
        self.assertEqual(self.run_main("--sandbox")[1].strip(), "workspace is up to date")

    def test_every_protected_path_is_one_init_creates(self):
        # A rule naming a path init doesn't create, such as a renamed folder, would protect nothing.
        self.run_main("--sandbox")
        settings = self.settings()
        edits = [re.fullmatch(r"Edit\(/(.+)\)", rule) for rule in settings["permissions"]["ask"]]
        protected = [m.group(1).removesuffix("/**") for m in edits if m]
        protected += [path.removeprefix("./") for path in settings["sandbox"]["filesystem"]["denyWrite"]]
        for rule in settings["autoMode"]["soft_deny"]:
            protected += re.findall(r"[\w./-]+\.md\b", rule)
        self.assertGreaterEqual(len(protected), 8)
        for path in protected:
            self.assertTrue((self.root / path).exists(), path)

    def test_an_existing_sandbox_gets_the_denied_hosts_without_the_flag(self):
        self.write_settings(json.dumps({"sandbox": {"enabled": True}}))
        self.run_main()
        network = self.settings()["sandbox"]["network"]
        self.assertIn("github.com", network["deniedDomains"])
        self.assertNotIn("allowedDomains", network)

    def test_edits_to_files_that_steer_claude_need_approval(self):
        self.write_settings(json.dumps({"permissions": {"ask": ["Mine"]}}))
        self.run_main()
        ask = self.settings()["permissions"]["ask"]
        self.assertEqual(ask[0], "Mine")
        steering = ("Edit(/research/lessons.md)", "Edit(/research/profile.md)", "Edit(/CLAUDE.md)", "Edit(/.claude/**)")
        for rule in steering:
            self.assertIn(rule, ask)
        self.assertEqual(self.run_main()[1].strip(), "workspace is up to date")

    def test_a_template_may_only_ask_before_file_edits(self):
        good = {"permissions": {"ask": ["Edit(/research/lessons.md)"]}}
        self.assertEqual(init.check_template(good), good)
        for bad in ("Bash(*)", "Edit(research/lessons.md)", "Edit(/a b)", "Edit", 5):
            with self.subTest(rule=bad), self.assertRaisesRegex(init.InitError, "ask rule init won't write"):
                init.check_template({"permissions": {"ask": [bad]}})

    def test_a_template_may_not_allow_anything(self):
        self.assertEqual(init.check_template({}), {})
        for bad in ("WebFetch(domain:arxiv.org)", "Bash(*)", "Read", 5):
            with self.subTest(rule=bad), self.assertRaisesRegex(init.InitError, "allow rule init won't write"):
                init.check_template({"permissions": {"allow": [bad]}})

    def test_a_template_may_ask_before_fetching_from_named_hosts(self):
        good = {"permissions": {"ask": ["WebFetch(domain:arxiv.org)", "Edit(/CLAUDE.md)"]}}
        self.assertEqual(init.check_template(good), good)
        for bad in ("WebFetch(domain:*)", "WebFetch(domain:localhost)", "WebFetch"):
            with self.subTest(rule=bad), self.assertRaisesRegex(init.InitError, "ask rule init won't write"):
                init.check_template({"permissions": {"ask": [bad]}})

    def test_a_widened_template_stops_everything(self):
        template = {"permissions": {"allow": ["Bash(*)"], "deny": []}, "autoMode": {"soft_deny": []}}
        with mock.patch.object(init, "load_template", return_value=template):
            code, out, err = self.run_main()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("allow rule init won't write", err)
        self.assertFalse((self.root / "research").exists())

    def test_the_dry_run_diff_is_against_the_real_file(self):
        self.write_settings('{\n    "model": "x"\n}\n')
        code, out, _ = self.run_main("--dry-run")
        # The removed line is the file's own text, with its own four-space indentation.
        self.assertIn('-    "model": "x"\n+    "model": "x",\n', out)
        self.assertIn('+        "ask": [', out)

    def test_the_files_own_indentation_is_kept(self):
        # The last sample has eight spaces before short content: an indent longer than what follows it.
        samples = ((4, '{\n    "model": "x"\n}\n'), ("\t", '{\n\t"model": "x"\n}\n'), (8, '{\n        "a": 1\n}\n'))
        for indent, sample in samples:
            with self.subTest(indent=indent):
                self.write_settings(sample)
                self.run_main()
                self.assertEqual(
                    self.read(".claude/settings.json").splitlines()[1],
                    f"{indent if indent == chr(9) else ' ' * indent}{sample.splitlines()[1].strip()},",
                )

    def test_a_new_settings_file_gets_two_spaces(self):
        self.run_main()
        self.assertEqual(self.read(".claude/settings.json").splitlines()[1], '  "permissions": {')

    def test_a_flat_file_gets_two_spaces_and_unicode_survives(self):
        self.write_settings('{"note": "café"}')
        self.run_main()
        text = self.read(".claude/settings.json")
        self.assertEqual(text.splitlines()[1], '  "note": "café",')

    def test_formatting_alone_does_not_cause_a_rewrite(self):
        self.run_main()
        compact = json.dumps(self.settings())
        self.write_settings(compact)
        code, out, _ = self.run_main()
        self.assertEqual(out.strip(), "workspace is up to date")
        self.assertEqual(self.read(".claude/settings.json"), compact)

    def test_more_than_one_block_is_refused_rather_than_half_fixed(self):
        one = f"{init.BEGIN}\nold\n{init.END}\n"
        twice = (
            one + "\n" + one,
            f"{init.BEGIN}\n{init.END}\n{init.END}\n",
            f"{init.BEGIN}\n{init.BEGIN}\n{init.END}\n",
        )
        for text in twice:
            with self.subTest(text=text[:30]):
                (self.root / "CLAUDE.md").write_text(text, encoding="utf-8")
                code, out, err = self.run_main()
                self.assertEqual((code, out), (1, ""))
                self.assertIn("more than one paper-research block", err)

    def test_every_settings_shape_that_would_break_a_merge_is_refused(self):
        shapes = [
            {"permissions": {"deny": "all"}},
            {"permissions": {"allow": None}},
            {"permissions": {"ask": "Edit"}},
            {"sandbox": []},
            {"sandbox": {"network": []}},
            {"sandbox": {"filesystem": []}},
            {"sandbox": {"filesystem": {"denyWrite": "x"}}},
            {"sandbox": {"network": {"allowedDomains": "x"}}},
            {"sandbox": {"network": {"deniedDomains": "x"}}},
        ]
        for shape in shapes:
            with self.subTest(shape=shape):
                self.write_settings(json.dumps(shape))
                code, _, err = self.run_main()
                self.assertEqual(code, 1)
                self.assertIn("unexpected shape", err)

    def test_the_graph_lock_file_is_ignored_by_git(self):
        self.run_main()
        self.assertIn("research/graph/.lock", self.read(".gitignore").splitlines())


class WriteCommand(Workspace):
    """The dry run prints the command the user runs to write the changes, so Claude never has to build it."""

    def printed(self, *argv):
        lines = [line for line in self.run_main("--dry-run", *argv)[1].splitlines() if line.startswith("! ")]
        self.assertEqual(len(lines), 1, lines)
        return lines[0][2:]

    def test_the_dry_run_prints_a_command_for_the_real_script_and_this_workspace(self):
        script = Path(init.__file__).resolve().as_posix()
        self.assertTrue(Path(script).is_file())
        self.assertEqual(self.printed(), f'python "{script}" --workspace "{self.root.resolve().as_posix()}"')

    def test_the_command_writes_and_never_repeats_the_dry_run(self):
        self.assertNotIn("--dry-run", self.printed())

    def test_the_sandbox_option_is_carried_into_the_command(self):
        self.assertTrue(self.printed("--sandbox").endswith(" --sandbox"))
        self.assertNotIn("--sandbox", self.printed())

    def test_no_command_when_nothing_would_change_or_when_writing(self):
        self.assertNotIn("\n! ", "\n" + self.run_main()[1])
        self.assertNotIn("\n! ", "\n" + self.run_main("--dry-run")[1])

    def test_a_path_that_needs_quoting_gets_no_command(self):
        for bad in ('/a/b"c', "/a/b$c", "/a/b`c", "/a/b;c", "/a/b%c", "/a/b'c", "/a/b\nc"):
            self.assertIsNone(init.write_command(Path(bad), False), bad)
        self.assertEqual(
            init.write_command(Path("/a/b c/(d)"), True),
            f'python "{Path(init.__file__).resolve().as_posix()}" --workspace "/a/b c/(d)" --sandbox',
        )

    def test_the_dry_run_says_so_when_it_cannot_print_a_command(self):
        with mock.patch.object(init, "write_command", return_value=None):
            out = self.run_main("--dry-run")[1]
        self.assertNotIn("\n! ", "\n" + out)
        self.assertIn("run init.py from a terminal", out)
        self.assertIn("in the workspace folder", out)

    def test_running_the_printed_command_from_another_folder_sets_up_the_workspace(self):
        command = self.printed()
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        env = {**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")}
        done = subprocess.run(command, shell=True, cwd=elsewhere.name, env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.root / "CLAUDE.md").exists())
        self.assertTrue((self.root / ".claude" / "settings.json").exists())
        self.assertEqual(list(Path(elsewhere.name).iterdir()), [])


class Details(unittest.TestCase):
    def test_version_falls_back(self):
        manifest = Path(init.__file__).resolve().parents[3] / ".claude-plugin" / "plugin.json"
        self.assertEqual(init.version(), json.loads(manifest.read_text(encoding="utf-8"))["version"])
        self.assertIn(f"<!-- plugin version {init.version()} -->", init.block())
        with mock.patch.object(init, "PLUGIN_JSON", Path(tempfile.gettempdir()) / "missing-plugin.json"):
            self.assertEqual(init.version(), "unknown")

    def test_missing_workspace_and_script_entry(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "missing")
            with contextlib.redirect_stderr(err):
                self.assertEqual(init.main(["--workspace", missing]), 2)
            self.assertFalse(Path(missing).exists())
        self.assertIn("workspace not found", err.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["init.py", "--workspace", tmp, "--dry-run"]
            with (
                mock.patch.object(sys, "argv", argv),
                contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")),
            ):
                with self.assertRaises(SystemExit) as stopped:
                    runpy.run_path(init.__file__, run_name="__main__")
        self.assertEqual(stopped.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
