"""Offline checks that the plugin's files agree with each other. Run: python tools/test_plugin_contract.py

The skills, rules, manifests, docs, and scripts are written apart but promise things about each other: a skill
names a script that must exist, the docs describe the relation rules the graph enforces, the README promises
which hosts the scripts talk to. These tests catch a change to one side that leaves the other behind.
"""

import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
sys.path.insert(0, str(SKILLS / "graph" / "scripts"))

import graph  # noqa: E402

SKILL_FOLDERS = sorted(path for path in SKILLS.iterdir() if path.is_dir())
SCRIPTS = [path for path in SKILLS.glob("*/scripts/*.py") if not path.name.startswith("test_")]
RULES = (SKILLS / "init" / "templates" / "rules.md").read_text(encoding="utf-8")
PAPER_RULE_LEAD = "- **Paper lists:** whenever you list papers to the user, "
# The hosts the README promises the scripts talk to, and the XML namespaces the arXiv feed declares.
HOSTS = {
    "arxiv.org",
    "export.arxiv.org",
    "www.arxiv.org",
    "api.semanticscholar.org",
    "www.semanticscholar.org",
    "huggingface.co",
    "doi.org",
    "dx.doi.org",
    "www.w3.org",
    "purl.org",
    "a9.com",
}


def read(path):
    return path.read_text(encoding="utf-8")


def front_matter(path):
    match = re.match(r"---\n(.*?)\n---\n", read(path), re.S)
    assert match, f"{path} has no front matter"
    return dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)


def imported_modules(path):
    """The top-level name of every module a file imports absolutely."""
    for node in ast.walk(ast.parse(read(path))):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module.split(".")[0]


def heading_slugs(path):
    """The anchors GitHub makes for a file's headings."""
    slugs = set()
    for heading in re.findall(r"^#{1,6} (.+)$", read(path), re.M):
        text = re.sub(r"[`*_]", "", heading).strip().lower()
        slugs.add(re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text)))
    return slugs


def local_links(doc):
    """Each link in a document that points inside the repository."""
    for target in re.findall(r"\]\(([^)\s]+)\)", read(doc)):
        if not re.match(r"[a-z]+://|mailto:", target):
            yield target


def documented_types(cell):
    """The entity types a docs cell names: a list of types, "a work", or "any type"."""
    if cell.startswith("a work"):
        return graph.WORKS
    if cell.startswith("any type"):
        return graph.ENTITY_TYPES
    return {name.strip() for name in cell.split(",")}


def help_text(script):
    done = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=True)
    return done.stdout


class Skills(unittest.TestCase):
    def test_every_skill_is_named_after_its_folder_and_says_when_to_use_it(self):
        for folder in SKILL_FOLDERS:
            with self.subTest(folder.name):
                meta = front_matter(folder / "SKILL.md")
                self.assertEqual(meta.get("name"), folder.name)
                description = meta.get("description", "")
                self.assertTrue("Use when" in description or "Use after" in description, description)
                self.assertTrue(20 < len(description) <= 1024, len(description))

    def test_every_script_a_skill_refers_to_exists(self):
        seen = 0
        for folder in SKILL_FOLDERS:
            for skill, script in re.findall(r"<skills>/(\w+)/scripts/([\w.]+)", read(folder / "SKILL.md")):
                seen += 1
                self.assertTrue((SKILLS / skill / "scripts" / script).is_file(), f"{folder.name}: {skill}/{script}")
        self.assertGreaterEqual(seen, 5)

    def test_every_skill_that_lists_papers_carries_the_paper_list_rule_word_for_word(self):
        # The rules may not be loaded yet, so each skill that shows papers carries the whole rule, not just the
        # column names: with only the names, Claude filled in the ID, Citations, and Note columns its own way.
        lines = [line for line in RULES.splitlines() if line.startswith(PAPER_RULE_LEAD)]
        self.assertEqual(len(lines), 1, "the rules must state the paper-list rule once, on one line")
        rule = lines[0][len(PAPER_RULE_LEAD) :]
        self.assertIn("`Published | Title | ID | Citations | Topic | Note`", rule)
        # A skill that shows the table carries the rule, so a new skill that lists papers is checked too.
        listing = [folder.name for folder in SKILL_FOLDERS if "Published | Title | ID" in read(folder / "SKILL.md")]
        self.assertGreaterEqual(len(listing), 4, listing)
        for skill in listing:
            self.assertIn(rule, read(SKILLS / skill / "SKILL.md"), skill)


class Manifests(unittest.TestCase):
    def test_the_manifests_are_valid_and_agree_on_the_plugin_name(self):
        plugin = json.loads(read(ROOT / ".claude-plugin" / "plugin.json"))
        market = json.loads(read(ROOT / ".claude-plugin" / "marketplace.json"))
        self.assertEqual(plugin["name"], "paper-research")
        self.assertEqual(market["plugins"][0]["name"], plugin["name"])
        self.assertRegex(plugin["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(plugin["license"], "Apache-2.0")


class Scripts(unittest.TestCase):
    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10 or later")
    def test_the_scripts_import_only_the_standard_library(self):
        siblings = {path.stem for path in SKILLS.glob("*/scripts/*.py")}
        for path in SCRIPTS:
            for top in imported_modules(path):
                self.assertTrue(top in sys.stdlib_module_names or top in siblings, f"{path.name} imports {top}")

    def test_the_scripts_name_only_the_hosts_the_readme_promises(self):
        for path in SCRIPTS:
            for host in re.findall(r"https?://([A-Za-z0-9.-]+)", read(path)):
                self.assertIn(host, HOSTS, path.name)

    def test_the_recap_page_loads_only_files_shipped_next_to_it(self):
        folder = SKILLS / "recap" / "page"
        sources = re.findall(r'<script src="([^"]+)"', read(folder / "recap.html"))
        self.assertTrue(sources)
        for source in sources:
            self.assertNotRegex(source, r"^(https?:)?//")
            self.assertTrue((folder / source).is_file() or source == "recap-data.js", source)


class Docs(unittest.TestCase):
    def test_every_link_in_the_docs_points_to_a_file_and_heading_that_exist(self):
        checked = 0
        for doc in [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]:
            for target in local_links(doc):
                path, _, anchor = target.partition("#")
                destination = (doc.parent / path).resolve() if path else doc
                self.assertTrue(destination.exists(), f"{doc.name} links to {target}, which does not exist")
                if anchor:
                    self.assertIn(anchor, heading_slugs(destination), f"{doc.name} links to {target}")
                checked += 1
        self.assertGreaterEqual(checked, 30)

    def test_the_docs_describe_every_skill(self):
        text = read(ROOT / "docs" / "skills.md")
        for folder in SKILL_FOLDERS:
            pattern = rf"^## .*(?<![A-Za-z0-9_]){folder.name}(?![A-Za-z0-9_])"
            self.assertRegex(text, re.compile(pattern, re.M), folder.name)

    def test_the_documented_relation_table_matches_the_rules_the_graph_enforces(self):
        text = read(ROOT / "docs" / "knowledge-graph.md")
        start = text.index("| Relation | From | To |")
        table = text[start : text.index("\n\n", start)]
        documented = {}
        for row in table.splitlines()[2:]:
            relations, source, target = [cell.strip() for cell in row.strip("|").split("|")]
            for rel in re.findall(r"`([a-z-]+)`", relations):
                documented[rel] = (documented_types(source), documented_types(target))
        self.assertEqual(documented, dict(graph.RELATION_ENDS))

    def test_the_command_reference_lists_every_command_and_option(self):
        reference = read(ROOT / "docs" / "reference.md")
        for script in ("graph/scripts/graph.py", "arxiv/scripts/arxiv.py", "scholar/scripts/s2.py"):
            listed = re.search(r"\{([a-z,-]+)\}", help_text(SKILLS / script))
            assert listed, f"{script} --help lists no commands"
            commands = listed.group(1).split(",")
            for command in commands:
                self.assertTrue(f"`{command} " in reference or f"`{command}`" in reference, f"{script}: {command}")
        for option in re.findall(r"(--[a-z-]+)", help_text(SKILLS / "init" / "scripts" / "init.py")):
            if option != "--help":
                self.assertIn(option, reference, f"init {option}")


if __name__ == "__main__":
    unittest.main()
