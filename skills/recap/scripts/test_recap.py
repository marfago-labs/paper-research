"""Offline tests for recap.py. Run: python paper-research/recap/test_recap.py

They cover turning the research files into page data and copying the page next to it.
The page's rendering is tested with Node; its DOM wiring is checked by hand in a browser.
"""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import recap

PAPERS = """# Papers

Intro text with a | pipe that is not a table row.

| Added | Title | ID | Status | Rating | Tags | Summary |
|---|---|---|---|---|---|---|
| 2026-01-02 | A \\| B paper | ARXIV:2601.00001 | read | 4 | agents | Uses `code`. |
| 2026-01-01 | Old one | DOI:10.1234/xyz | archive | - | rag | Older. |
| 2026-01-03 | A blog | <https://example.com/post> | skim | - | blog | A post. |
| 2026-01-03 | Note | local-note | weird | - | misc | Not a link. |
"""

PINS = """# Pins

`- **[type] Title:** format line that should not match.`

- **[dataset] Set A:** A dataset. Source: ARXIV:2601.00001, §2. Added: 2026-01-02.
- **[tool] Tool B:** A tool, no date.
Not a pin.
"""

INSIGHTS = """# Insights

## First insight

- **ID:** `insight:first`
- **Kind:** `practice`
- **Insight:** Do the thing.
- **Sources:** `ARXIV:2601.00001`, §3; DOI:10.1234/xyz. Also ARXIV:2601.00001.
- **User's view:** Agrees.
- **Added:** 2026-01-02

## Second insight

- **Insight:** Only some fields.
"""

FACTS = """# User facts

Format: `YYYY-MM-DD | type | basis | fact`

2026-01-02 | question | observed | Asked about A | B
2026-01-02 | interest | stated | Likes agents
"""

ENTITIES = [
    {"id": "paper:2601.00001", "type": "paper", "name": "Paper A", "aliases": []},
    {"id": "paper:old", "type": "paper", "name": "Old one", "aliases": ["DOI:10.1234/XYZ"]},
    {"id": "paper:blog", "type": "paper", "name": "A blog", "aliases": [], "url": "https://example.com/post"},
    {"id": "tool:b", "type": "tool", "name": "Tool B", "aliases": []},
]
RELATION = {"from": "paper:2601.00001", "rel": "uses", "to": "tool:b", "source": "test", "status": "verified"}


def write_research(root, entities=ENTITIES):
    (root / "graph").mkdir(parents=True)
    (root / "papers.md").write_text(PAPERS, encoding="utf-8")
    (root / "pins.md").write_text(PINS, encoding="utf-8")
    (root / "insights.md").write_text(INSIGHTS, encoding="utf-8")
    (root / "user-facts.md").write_text(FACTS, encoding="utf-8")
    (root / "graph" / "entities.jsonl").write_text("\n".join(json.dumps(e) for e in entities), encoding="utf-8")
    (root / "graph" / "relations.jsonl").write_text(json.dumps(RELATION), encoding="utf-8")


class Parse(unittest.TestCase):
    def test_papers(self):
        papers = recap.parse_papers(PAPERS)
        self.assertEqual(len(papers), 4)
        self.assertEqual(papers[0]["title"], "A | B paper")
        self.assertEqual(
            [p["url"] for p in papers],
            [
                "https://arxiv.org/abs/2601.00001",
                "https://doi.org/10.1234/xyz",
                "https://example.com/post",
                "",
            ],
        )
        self.assertEqual(papers[2]["id"], "https://example.com/post")

    def test_pins(self):
        pins = recap.parse_pins(PINS)
        self.assertEqual([p["title"] for p in pins], ["Set A", "Tool B"])
        self.assertEqual([p["added"] for p in pins], ["2026-01-02", ""])

    def test_insights(self):
        first, second = recap.parse_insights(INSIGHTS)
        self.assertEqual(first["id"], "insight:first")
        self.assertEqual(first["kind"], "practice")
        self.assertEqual(first["users_view"], "Agrees.")
        self.assertEqual(first["papers"], ["ARXIV:2601.00001", "DOI:10.1234/xyz"])
        self.assertEqual((second["id"], second["kind"], second["papers"]), ("", "", []))

    def test_questions(self):
        self.assertEqual(recap.parse_questions(FACTS), [{"added": "2026-01-02", "text": "Asked about A | B"}])


class Data(unittest.TestCase):
    def test_full_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_research(Path(tmp))
            data = recap.build_data(Path(tmp), now="2026-01-04 10:00")
        self.assertEqual(data["generated"], "2026-01-04 10:00")
        self.assertEqual(len(data["papers"]), 4)
        self.assertEqual(data["graph"]["error"], "")
        self.assertEqual(len(data["graph"]["entities"]), 4)
        self.assertEqual([p["graph"] for p in data["papers"]], ["extracted", "unextracted", "unextracted", "missing"])

    def test_a_saved_full_text_missing_from_papers_md_is_flagged_as_not_in_the_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            research = Path(tmp)
            (research / "fulltext").mkdir()
            (research / "fulltext" / "2404.16130.md").write_text("text", encoding="utf-8")
            (research / "fulltext" / "notes.md").write_text("not a paper id", encoding="utf-8")
            data = recap.build_data(research)
        self.assertEqual([(p["id"], p["graph"]) for p in data["papers"]], [("ARXIV:2404.16130", "missing")])
        self.assertEqual(data["papers"][0]["url"], "https://arxiv.org/abs/2404.16130")

    def test_a_full_text_already_in_papers_md_is_not_listed_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            research = Path(tmp)
            (research / "fulltext").mkdir()
            (research / "fulltext" / "2601.00001.md").write_text("text", encoding="utf-8")
            (research / "papers.md").write_text(
                "| Added | ID | Title | Status |\n|---|---|---|---|\n| 2026-01-01 | ARXIV:2601.00001 | A | read |\n",
                encoding="utf-8",
            )
            data = recap.build_data(research)
        self.assertEqual([p["title"] for p in data["papers"]], ["A"])

    def test_a_full_text_listed_under_another_form_of_its_id_is_not_listed_twice(self):
        forms = (
            "ARXIV:2601.00001v2",
            "arXiv:2601.00001",
            "https://arxiv.org/abs/2601.00001v3",
            "https://arxiv.org/pdf/2601.00001.pdf",
        )
        for listed in forms:
            with self.subTest(listed=listed), tempfile.TemporaryDirectory() as tmp:
                research = Path(tmp)
                (research / "fulltext").mkdir()
                (research / "fulltext" / "2601.00001.md").write_text("text", encoding="utf-8")
                (research / "papers.md").write_text(
                    f"| Added | ID | Title | Status |\n|---|---|---|---|\n| 2026-01-01 | {listed} | A | read |\n",
                    encoding="utf-8",
                )
                data = recap.build_data(research)
                self.assertEqual([p["title"] for p in data["papers"]], ["A"])

    def test_a_different_paper_with_a_similar_id_does_not_hide_the_full_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            research = Path(tmp)
            (research / "fulltext").mkdir()
            (research / "fulltext" / "2601.00001.md").write_text("text", encoding="utf-8")
            (research / "papers.md").write_text(
                "| Added | ID | Title | Status |\n|---|---|---|---|\n| 2026-01-01 | ARXIV:2601.000012 | B | read |\n",
                encoding="utf-8",
            )
            data = recap.build_data(research)
        self.assertEqual([p["id"] for p in data["papers"]], ["ARXIV:2601.000012", "ARXIV:2601.00001"])

    def test_empty_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = recap.build_data(Path(tmp))
        self.assertEqual((data["papers"], data["pins"], data["insights"], data["questions"]), ([], [], [], []))
        self.assertEqual(data["graph"], {"entities": [], "relations": [], "error": ""})
        self.assertRegex(data["generated"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_invalid_graph_is_reported_not_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_research(Path(tmp), entities=[ENTITIES[0]])
            data = recap.build_data(Path(tmp))
        self.assertIn("invalid graph", data["graph"]["error"])
        self.assertEqual(data["graph"]["entities"], [])
        self.assertNotIn("graph", data["papers"][0])

    def test_script_keeps_text_as_data(self):
        script = recap.to_script({"title": "</script> ü"})
        self.assertTrue(script.startswith("// Generated"))
        payload = script.split("window.RECAP_DATA = ", 1)[1].rstrip().rstrip(";")
        self.assertEqual(json.loads(payload), {"title": "</script> ü"})


class Cli(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = recap.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_writes_data_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_research(Path(tmp) / "research")
            code, out, err = self.run_main(["--workspace", tmp])
            self.assertEqual(code, 0)
            folder = Path(tmp) / "research" / "recap"
            self.assertIn("Paper A", (folder / "recap-data.js").read_text(encoding="utf-8"))
            self.assertEqual(sorted(f.name for f in folder.iterdir()), sorted([*recap.PAGE_FILES, "recap-data.js"]))
            self.assertIn('<script src="recap-data.js">', (folder / "recap.html").read_text(encoding="utf-8"))
            self.assertEqual(self.run_main(["--workspace", tmp])[0], 0)
        self.assertIn("recap.html", out)
        self.assertEqual(err, "")

    def test_warns_about_invalid_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_research(Path(tmp) / "research", entities=[ENTITIES[0]])
            code, _, err = self.run_main(["--workspace", tmp])
        self.assertEqual(code, 0)
        self.assertIn("graph not shown", err)

    def test_a_workspace_without_a_research_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_main(["--workspace", tmp])
            self.assertFalse((Path(tmp) / "research").exists())
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_script_entry_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "research").mkdir()
            argv = ["recap.py", "--workspace", tmp]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    runpy.run_path(recap.__file__, run_name="__main__")
        self.assertEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
