"""Offline tests on real replies from arXiv and Semantic Scholar. Run: python tools/test_recorded_responses.py

The scripts' own tests use replies written by hand. These use replies recorded from the services by
tools/record_responses.py, so a change in what the services send shows up here when the replies are recorded again.
They also run the citation refresh the recap skill does, across the scripts: graph.py standing-due writes the ids,
s2.py batch reads them and asks Semantic Scholar, and graph.py standing saves what came back.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools" / "fixtures"
GRAPH = ROOT / "skills" / "graph" / "scripts" / "graph.py"
for folder in ("arxiv", "scholar"):
    sys.path.insert(0, str(ROOT / "skills" / folder / "scripts"))

import arxiv  # noqa: E402
import s2  # noqa: E402

PAPER, CITED, UNKNOWN = "2303.11366", "2107.03374", "2611.99999"
TITLE = "Reflexion: Language Agents with Verbal Reinforcement Learning"
BATCH = [record for record in json.loads((FIXTURES / "s2-batch.json").read_text(encoding="utf-8")) if record]
RECORDED = {record["externalIds"]["ArXiv"]: record for record in BATCH}


def run(main, argv):
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    out.seek(0)
    err.seek(0)
    return code, out.read(), err.read()


class Workspace(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        (self.root / "research" / "graph").mkdir(parents=True)
        for name in ("entities.jsonl", "relations.jsonl"):
            (self.root / "research" / "graph" / name).write_text("", encoding="utf-8")
        here = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, here)

    def graph(self, *argv):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        done = subprocess.run(
            [sys.executable, str(GRAPH), *argv], cwd=self.root, capture_output=True, text=True, env=env, check=False
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout


class Arxiv(Workspace):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(arxiv, "pace"), mock.patch.object(arxiv.time, "sleep")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_real_feed_gives_each_paper_its_date_and_link(self):
        feed = (FIXTURES / "arxiv-feed.xml").read_bytes()
        with mock.patch.object(arxiv, "get", return_value=feed):
            code, out, _ = run(arxiv.main, ["paper", PAPER, CITED])
        self.assertEqual(code, 0)
        papers = {paper["id"]: paper for paper in json.loads(out)["papers"]}
        self.assertEqual(set(papers), {PAPER, CITED})
        self.assertEqual(papers[PAPER]["title"], TITLE)
        self.assertEqual(papers[PAPER]["link"], f"[ARXIV:{PAPER}](https://arxiv.org/abs/{PAPER})")
        for paper in papers.values():
            self.assertRegex(paper["published"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(paper["abstract"] and paper["authors"], paper["id"])

    def test_a_real_page_keeps_its_title_and_sections_and_raises_no_false_alarm(self):
        page = (FIXTURES / f"arxiv-{PAPER}.html").read_bytes()
        with mock.patch.object(arxiv, "get", return_value=page):
            code, out, _ = run(arxiv.main, ["fetch", PAPER, "--dir", str(self.root / "fulltext")])
        self.assertEqual(code, 0)
        result = json.loads(out)
        headings = [section["heading"] for section in result["sections"]]
        self.assertEqual(headings[:2], [TITLE, "Abstract"])
        self.assertIn("1 Introduction", headings)
        self.assertIn("2 Related work", headings)
        self.assertNotIn("hiddenTextRemoved", result, "a real paper that hides nothing must not be flagged")
        self.assertGreater(len(Path(result["path"]).read_text(encoding="utf-8").split()), 1000)


class CitationRefresh(Workspace):
    def setUp(self):
        super().setUp()
        self.asked = []
        for patcher in (
            mock.patch.object(s2, "CACHE_DIR", self.root / ".cache"),
            mock.patch.object(s2, "pace"),
            mock.patch.object(s2.time, "sleep"),
            mock.patch.object(s2.OPENER, "open", self.semantic_scholar),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def semantic_scholar(self, request, timeout=None):
        """The batch endpoint, answering from the recorded records: null for a paper it doesn't know."""
        ids = json.loads(request.data)["ids"]
        self.asked.append(ids)
        return io.BytesIO(json.dumps([RECORDED.get(i.removeprefix("ARXIV:")) for i in ids]).encode("utf-8"))

    def test_the_ids_graph_writes_reach_semantic_scholar_and_what_comes_back_is_saved(self):
        for paper_id in (PAPER, CITED, UNKNOWN):
            self.graph("add", "--type", "paper", "--name", f"Paper {paper_id}", "--slug", paper_id)
        self.assertIn("3 papers due", self.graph("standing-due", "research/ids.txt"))

        code, out, err = run(
            s2.main, ["batch", "--ids-file", "research/ids.txt", "--with-references", "--out", "research/counts.json"]
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(self.asked[0]), sorted(f"ARXIV:{i}" for i in (PAPER, CITED, UNKNOWN)))

        saved = self.graph("standing", "research/counts.json")
        self.assertIn("2 papers updated", saved)
        self.assertIn("1 without citation data", saved)
        self.assertIn("1 citation link added", saved)
        entities = self.entities()
        for paper_id in (PAPER, CITED):
            standing = entities[f"paper:{paper_id}"]["standing"]
            self.assertEqual(standing["citations"], RECORDED[paper_id]["citationCount"], paper_id)
        self.assertNotIn("citations", entities[f"paper:{UNKNOWN}"]["standing"])
        relations = (self.root / "research" / "graph" / "relations.jsonl").read_text(encoding="utf-8")
        cites = [json.loads(line) for line in relations.splitlines() if line.strip()]
        self.assertIn((f"paper:{PAPER}", "cites", f"paper:{CITED}"), [(r["from"], r["rel"], r["to"]) for r in cites])
        self.assertIn("no papers due", self.graph("standing-due", "research/ids.txt"))

    def entities(self):
        text = (self.root / "research" / "graph" / "entities.jsonl").read_text(encoding="utf-8")
        return {entity["id"]: entity for entity in (json.loads(line) for line in text.splitlines() if line.strip())}


if __name__ == "__main__":
    unittest.main()
