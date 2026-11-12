"""Offline tests for graph.py. Run: python paper-research/graph/test_graph.py"""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import graph


def loaded(record):
    """The record as a graph file gives it back. Its strings are new objects, as in a real graph, so code that
    compares them with `is` instead of `==` fails the tests."""
    return json.loads(json.dumps(record))


def entity(entity_id, name=None, **extra):
    return loaded({"id": entity_id, "type": entity_id.split(":")[0], "name": name or entity_id, "aliases": [], **extra})


def relation(start, rel, end, **extra):
    return loaded(
        {"from": start, "rel": rel, "to": end, "source": "ARXIV:2401.00001, §1", "status": "verified", **extra}
    )


ENTITIES = [
    entity("paper:a", "Paper A", aliases=["Alpha"]),
    entity("tool:b", "Tool B"),
    entity("dataset:c", "Dataset C"),
    entity("concept:d", "Concept D"),
]
RELATIONS = [
    relation("paper:a", "uses", "tool:b"),
    relation("tool:b", "evaluates-on", "dataset:c"),
]


class Validate(unittest.TestCase):
    def test_valid_graph(self):
        self.assertEqual(graph.validate(ENTITIES, RELATIONS), [])

    def test_rejects_problems(self):
        cases = {
            "unknown type": ([{"id": "x:a", "type": "x", "name": "A"}], []),
            "must start with": ([{"id": "paper:a", "type": "tool", "name": "A"}], []),
            "duplicate entity id": ([entity("paper:a"), entity("paper:a")], []),
            "already used": ([entity("tool:a", "SWE Bench"), entity("tool:b", "swe-bench")], []),
            "url must start": ([entity("paper:a", url="javascript:alert(1)")], []),
            "unknown entity": ([entity("paper:a")], [relation("paper:a", "uses", "tool:z")]),
            "unknown relation": ([entity("paper:a"), entity("tool:b")], [relation("paper:a", "likes", "tool:b")]),
            "needs a source": (
                [entity("paper:a"), entity("tool:b")],
                [relation("paper:a", "uses", "tool:b", source="")],
            ),
            "status must": (
                [entity("paper:a"), entity("tool:b")],
                [relation("paper:a", "uses", "tool:b", status="maybe")],
            ),
            "duplicate relation": ([entity("paper:a"), entity("tool:b")], [relation("paper:a", "uses", "tool:b")] * 2),
        }
        for expected, (entities, relations) in cases.items():
            errors = graph.validate(entities, relations)
            self.assertTrue(any(expected in error for error in errors), f"{expected}: {errors}")


class Queries(unittest.TestCase):
    def test_search_and_resolve_use_aliases(self):
        self.assertEqual(graph.search(ENTITIES, "alph")[0]["id"], "paper:a")
        self.assertEqual(graph.resolve(ENTITIES, "alpha")["id"], "paper:a")
        with self.assertRaises(graph.GraphError):
            graph.resolve(ENTITIES, "missing")

    def test_search_shows_a_papers_saved_citation_count(self):
        counted = {"id": "paper:a", "standing": {"citations": 1, "checked": "2026-11-01"}}
        unknown = {"id": "paper:b", "standing": {"checked": "2026-11-02"}}
        self.assertEqual(graph.standing_note(counted), "  [1 citation, checked 2026-11-01]")
        self.assertEqual(graph.standing_note(unknown), "  [no citation data, checked 2026-11-02]")
        self.assertEqual(graph.standing_note({"id": "tool:b"}), "")

    def test_neighbours_respect_depth(self):
        one = graph.neighbours(RELATIONS, "paper:a", 1)
        two = graph.neighbours(RELATIONS, "paper:a", 2)
        self.assertEqual([item[3] for item in one], ["tool:b"])
        self.assertEqual([item[3] for item in two], ["tool:b", "dataset:c"])

    def test_path_ignores_direction_and_reports_no_path(self):
        steps = graph.shortest_path(RELATIONS, "dataset:c", "paper:a")
        self.assertEqual([step[2] for step in steps], ["tool:b", "paper:a"])
        self.assertEqual([step[0] for step in steps], ["in", "in"])
        self.assertIsNone(graph.shortest_path(RELATIONS, "paper:a", "concept:d"))


class Sources(unittest.TestCase):
    def test_a_source_names_a_document_by_id_link_or_data_source(self):
        for source in (
            "ARXIV:2401.00005, §3.1",
            "arxiv:2401.00005",
            "DOI:10.1145/3442188.3445922, Table 2",
            "https://github.com/example-org/example-repo, README",
            "paper:2401.00004, §5.1",
            "Semantic Scholar",
            "Semantic Scholar references",
        ):
            self.assertTrue(graph.names_document(source), source)
        for source in (
            "§3.2",
            "s",
            "test",
            "Same group (Author A). Inferred",
            "the arXiv paper",
            "ARXIV:",
            "paper: x",
            # An id inside a reason is still a reason: the document has to come first.
            "Same group as paper:2401.00004; inferred",
            "Inferred from ARXIV:2401.00003 and ARXIV:2401.00004 authors",
            # A paper id alone, or with a reason after it, checks nothing: it needs a place in that paper.
            "paper:2401.00004",
            "paper:2401.00004 same group",
        ):
            self.assertFalse(graph.names_document(source), source)

    def test_only_verified_links_need_a_document(self):
        verified = {"source": "same group", "status": "verified"}
        self.assertTrue(graph.unsourced(verified))
        self.assertFalse(graph.unsourced(dict(verified, status="inferred")))
        self.assertFalse(graph.unsourced(dict(verified, source="ARXIV:2401.00001")))


class Edges(unittest.TestCase):
    """Behaviour at the edges: exact thresholds, values on either side of a comparison, and counts."""

    CHAIN = [
        relation("paper:a", "uses", "tool:b"),
        relation("tool:b", "evaluates-on", "dataset:c"),
        relation("dataset:c", "related-to", "concept:d"),
    ]

    def test_neighbours_give_each_connection_its_distance(self):
        found = [(distance, other) for distance, _, _, other in graph.neighbours(self.CHAIN, "paper:a", 2)]
        self.assertEqual(found, [(1, "tool:b"), (2, "dataset:c")])
        found = [(distance, other) for distance, _, _, other in graph.neighbours(self.CHAIN, "paper:a", 3)]
        self.assertEqual(found, [(1, "tool:b"), (2, "dataset:c"), (3, "concept:d")])

    def test_neighbours_go_one_step_unless_asked_for_more(self):
        found = [other for _, _, _, other in graph.neighbours(self.CHAIN, "paper:a")]
        self.assertEqual(found, ["tool:b"])
        self.assertEqual(graph.neighbours(self.CHAIN, "paper:a", 0), [])

    def test_the_arrow_points_the_way_the_link_goes(self):
        link = relation("paper:a", "uses", "tool:b")
        self.assertTrue(graph.describe(link, "out", "Tool B").startswith("-> uses -> Tool B"))
        self.assertTrue(graph.describe(link, "in", "Paper A").startswith("<- uses <- Paper A"))

    def test_a_trigram_is_compared_only_while_few_enough_share_it(self):
        names = [entity(f"concept:{n}", name) for n, name in enumerate(("abcd", "abce", "abcf"))]
        with mock.patch.object(graph, "BLOCK_CAP", 3):
            self.assertEqual(len(graph.candidate_pairs(names)), 3)
        with mock.patch.object(graph, "BLOCK_CAP", 2):
            self.assertEqual(graph.candidate_pairs(names), set())

    def test_the_same_name_is_compared_however_many_share_it(self):
        same = [entity(f"concept:{n}", "Same") for n in range(3)]
        with mock.patch.object(graph, "BLOCK_CAP", 1):
            self.assertEqual(len(graph.candidate_pairs(same)), 3)

    def test_a_new_id_skips_every_number_already_taken(self):
        taken = [entity("tool:x"), entity("tool:x-2"), entity("tool:x-3")]
        self.assertEqual(graph.free_id(taken, "tool:x"), "tool:x-4")

    def test_only_a_paper_gets_an_arxiv_key_from_its_id(self):
        self.assertEqual(graph.external_keys(entity("paper:2401.00001")), {("arxiv", "2401.00001")})
        for kind in ("author", "tool"):
            self.assertEqual(graph.external_keys(entity(f"{kind}:2401.00001")), set(), kind)

    def test_a_name_exactly_at_the_similarity_threshold_is_held(self):
        self.assertEqual(graph.similarity("Bert", "Berk"), graph.SIMILARITY)
        self.assertIn("similar name (0.50)", graph.match_reasons(entity("tool:a", "Bert"), entity("tool:b", "Berk")))

    def test_ids_conflict_whichever_value_sorts_first_and_only_where_both_have_one(self):
        low, high = entity("author:a", ids={"s2": "1"}), entity("author:b", ids={"s2": "2"})
        self.assertEqual(graph.conflicting_ids(low, high), ["s2"])
        self.assertEqual(graph.conflicting_ids(high, low), ["s2"])
        more = entity("author:c", ids={"s2": "1", "github": "x"})
        self.assertEqual(graph.conflicting_ids(more, low), [])

    def test_a_conflicting_id_alone_is_no_reason_to_hold(self):
        ann, zed = entity("author:a", "Ann Lee", ids={"s2": "1"}), entity("author:b", "Zed Kim", ids={"s2": "2"})
        self.assertEqual(graph.judged(ann, zed), ([], False))


class Loading(unittest.TestCase):
    def test_load_reports_the_bad_line(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "entities.jsonl").write_text('{"id": "paper:a"}\nnot json\n', encoding="utf-8")
            (directory / "relations.jsonl").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(graph.GraphError, "entities.jsonl:2"):
                graph.load(directory)


class SeparateData(unittest.TestCase):
    def test_reads_the_given_data_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            lines = [json.dumps(item) for item in ENTITIES]
            (directory / "entities.jsonl").write_text("\n".join(lines), encoding="utf-8")
            (directory / "relations.jsonl").write_text("", encoding="utf-8")
            out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
            with contextlib.redirect_stdout(out):
                self.assertEqual(graph.main(["--data", folder, "stats"]), 0)
            out.seek(0)
            self.assertIn("paper: 1", out.read())


class MoreValidation(unittest.TestCase):
    def test_rejects_remaining_problems(self):
        cases = {
            "needs an id and a name": ([{"id": "paper:a", "type": "paper"}], []),
            "can't connect to itself": ([entity("paper:a")], [relation("paper:a", "cites", "paper:a")]),
            "unknown entity 'tool:z'": ([entity("paper:a")], [relation("tool:z", "uses", "paper:a")]),
        }
        for expected, (entities, relations) in cases.items():
            errors = graph.validate(entities, relations)
            self.assertTrue(any(expected in error for error in errors), f"{expected}: {errors}")

    def test_accepts_an_insight_derived_from_a_paper(self):
        entities = [entity("insight:a", "Keep it simple"), entity("paper:b", "Paper B")]
        relations = [relation("insight:a", "derived-from", "paper:b")]
        self.assertEqual(graph.validate(entities, relations), [])

    def test_a_name_may_repeat_across_types(self):
        same = [entity("paper:mamba", "Mamba"), entity("model:mamba", "Mamba")]
        self.assertEqual(graph.validate(same, []), [])

    def test_a_shared_name_needs_distinct(self):
        same = [entity("author:wei-zhang", "Wei Zhang"), entity("author:wei-zhang-2", "Wei Zhang")]
        self.assertIn("already used by author:wei-zhang", graph.validate(same, [])[0])
        same[1]["distinct_from"] = ["author:wei-zhang"]
        self.assertEqual(graph.validate(same, []), [])

    def test_an_alias_may_repeat_its_own_name(self):
        self.assertEqual(graph.validate([entity("paper:a", "Same", aliases=["same"])], []), [])


class MoreQueries(unittest.TestCase):
    DIAMOND = [
        relation("paper:a", "uses", "tool:b"),
        relation("paper:a", "uses", "dataset:c"),
        relation("tool:b", "evaluates-on", "concept:d"),
        relation("dataset:c", "related-to", "concept:d"),
    ]

    def test_resolve_finds_an_exact_id(self):
        self.assertEqual(graph.resolve(ENTITIES, "tool:b")["name"], "Tool B")

    def test_neighbours_list_each_connection_once(self):
        found = graph.neighbours(self.DIAMOND, "paper:a", 3)
        self.assertEqual(len(found), 4)
        self.assertEqual(graph.neighbours(self.DIAMOND, "missing", 1), [])

    def test_path_handles_cycles_and_the_same_entity(self):
        self.assertEqual(graph.shortest_path(self.DIAMOND, "paper:a", "paper:a"), [])
        steps = graph.shortest_path(self.DIAMOND, "paper:a", "concept:d")
        self.assertEqual(len(steps), 2)
        self.assertIsNone(graph.shortest_path(self.DIAMOND, "paper:a", "author:none"))


class FileProblems(unittest.TestCase):
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(graph.GraphError, "missing file"):
                graph.load(Path(folder))

    def test_blank_lines_are_skipped_and_non_objects_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "x.jsonl"
            path.write_text('{"a": 1}\n\n', encoding="utf-8")
            self.assertEqual(graph.read_jsonl(path), [{"a": 1}])
            path.write_text("[1]\n", encoding="utf-8")
            with self.assertRaisesRegex(graph.GraphError, "x.jsonl:1: expected a JSON object"):
                graph.read_jsonl(path)


class CommandLineBase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.write(ENTITIES, RELATIONS)

    def write(self, entities, relations):
        (self.folder / "entities.jsonl").write_text("\n".join(json.dumps(item) for item in entities), encoding="utf-8")
        (self.folder / "relations.jsonl").write_text(
            "\n".join(json.dumps(item) for item in relations), encoding="utf-8"
        )

    def run_main(self, *argv):
        out, err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8"), io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = graph.main(["--data", str(self.folder), *argv])
        out.seek(0)
        err.seek(0)
        return code, out.read(), err.read()


class CommandLine(CommandLineBase):
    def test_validate_and_stats(self):
        self.assertIn("OK: 4 entities, 2 relations", self.run_main("validate")[1])
        code, out, _ = self.run_main("stats")
        self.assertEqual(code, 0)
        self.assertIn("paper: 1", out)
        self.assertIn("uses: 1", out)

    def test_validate_lists_verified_links_that_name_no_document(self):
        unsourced = relation("paper:a", "related-to", "concept:d", source="same group")
        self.write(ENTITIES, [*RELATIONS, unsourced])
        code, out, _ = self.run_main("validate")
        self.assertEqual(code, 1)
        self.assertIn("found 1 verified link with no document it was checked against", out)
        self.assertNotIn("OK", out, "the first line must not say OK when the command fails")
        self.assertIn("checked: 4 entities, 3 relations", out)
        self.assertIn("paper:a related-to concept:d  [same group]", out)
        self.assertIn("unlink", out)
        self.assertEqual(self.run_main("stats")[0], 0, "an old link must not lock the user out of the graph")

    def test_invalid_graph_fails_every_command(self):
        self.write([entity("paper:a")], [relation("paper:a", "uses", "tool:z")])
        code, _, err = self.run_main("stats")
        self.assertEqual(code, 1)
        self.assertIn("invalid graph", err)

    def test_search(self):
        code, out, _ = self.run_main("search", "alpha")
        self.assertEqual(code, 0)
        self.assertIn("paper:a  Paper A", out)
        self.assertNotIn("checked", out)
        counted = [
            dict(e, standing={"citations": 7, "checked": "2026-11-01"}) if e["id"] == "paper:a" else e for e in ENTITIES
        ]
        self.write(counted, RELATIONS)
        self.assertIn("paper:a  Paper A  [7 citations, checked 2026-11-01]", self.run_main("search", "alpha")[1])
        code, _, err = self.run_main("search", "zzz")
        self.assertEqual(code, 1)
        self.assertIn("no matches", err)

    def test_neighbours_show_direction_and_source(self):
        code, out, _ = self.run_main("neighbours", "Tool B")
        self.assertEqual(code, 0)
        self.assertIn("<- uses <- Paper A", out)
        self.assertIn("-> evaluates-on -> Dataset C  [ARXIV:2401.00001, §1; verified]", out)

    def test_path(self):
        code, out, _ = self.run_main("path", "Paper A", "Dataset C")
        self.assertEqual(code, 0)
        self.assertIn("-> uses -> Tool B", out)
        code, _, err = self.run_main("path", "Paper A", "Concept D")
        self.assertEqual(code, 1)
        self.assertIn("no path", err)

    def test_runs_as_a_script(self):
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with mock.patch.object(sys, "argv", ["graph.py", "--data", str(self.folder), "validate"]):
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as stopped:
                    runpy.run_path(graph.__file__, run_name="__main__")
        self.assertEqual(stopped.exception.code, 0)


class Matching(unittest.TestCase):
    def test_name_key_removes_only_separators(self):
        # Whitespace, dashes, and connectors go; symbols and accents stay, so only a true respelling is refused.
        keys = [graph.name_key(text) for text in ("GPT-4", "gpt 4", "C++", "Jürgen", "SWE_bench\tX")]
        self.assertEqual(keys, ["gpt4", "gpt4", "c++", "jürgen", "swebenchx"])

    def test_name_key_composes_accents(self):
        # A decomposed 'Jürgen', as text copied from a PDF often is, is the same name as the composed one.
        composed, decomposed = "J\u00fcrgen", "Ju\u0308rgen"
        self.assertEqual(graph.name_key(composed), graph.name_key(decomposed))
        both = [entity("author:a", composed), entity("author:b", decomposed)]
        self.assertIn("already used by author:a", graph.validate(both, [])[0])

    def test_resolve_never_guesses_a_loose_match(self):
        # Commands that act must not take 'C++' for 'C'. A loose match is offered as a suggestion only.
        entities = [entity("tool:c", "C"), entity("tool:gpt", "GPT-4")]
        self.assertEqual(graph.resolve(entities, "gpt 4")["id"], "tool:gpt")
        for text in ("C++", "C#"):
            with self.assertRaises(graph.GraphError) as raised:
                graph.resolve(entities, text)
            self.assertIn("did you mean tool:c? Use its id", str(raised.exception))
        with self.assertRaises(graph.GraphError) as raised:
            graph.resolve(entities, "Rust")
        self.assertIn("no entity matches 'Rust'", str(raised.exception))

    def test_loose_form_and_similarity(self):
        # Marks go in every script, and other letters are spelled from their Unicode name: Đ is 'D WITH STROKE'.
        names = ("Łukasz Émile", "C++", "β-VAE", "Đorđe Đorđević", "ＧＰＴ－４", "μP", "Straße", "张伟")
        expected = ["lukasz emile", "c", "beta vae", "dorde dordevic", "gpt 4", "mup", "strasse", "u5f20 u4f1f"]
        self.assertEqual([graph.loose(name) for name in names], expected)
        self.assertEqual(sorted(graph.trigrams("C")), [" c "])
        self.assertEqual(graph.similarity("C", "C++"), 1.0)
        self.assertEqual(graph.similarity("x", "???"), 0.0)

    def test_ids_are_readable_and_never_decide(self):
        names = ("Terminal-Bench 2.1", "C++", "β-VAE", "Łukasz Kaiser", "Işık", "张伟", "Æsir")
        expected = ["terminal-bench-2-1", "c", "beta-vae", "lukasz-kaiser", "isik", "u5f20-u4f1f", "aesir"]
        self.assertEqual([graph.slugify(name) for name in names], expected)
        # A name with no letters or digits still gets an id, from its code points; only a blank name has none.
        self.assertEqual((graph.slugify("+"), graph.slugify("…")), ("u2b", "u2026"))
        with self.assertRaises(graph.GraphError):
            graph.slugify("   ")
        taken = [entity("tool:c", "C"), entity("tool:c-2", "C#")]
        self.assertEqual((graph.free_id(taken, "tool:c"), graph.free_id([], "tool:c")), ("tool:c-3", "tool:c"))

    def test_validation_keeps_names_apart_that_differ_beyond_separators(self):
        both = [entity("author:a", "Jürgen Schmidhuber"), entity("author:b", "Jurgen Schmidhuber")]
        self.assertEqual(graph.validate(both, []), [])
        self.assertEqual([reasons for _, _, reasons in graph.dupes(both)], [["similar name (1.00)"]])
        clash = [entity("tool:a", "SWE-bench"), entity("tool:b", "swe bench")]
        self.assertIn("already used by tool:a", graph.validate(clash, [])[0])

    def test_dupes_reports_a_conflicting_id_as_add_does(self):
        pair = [entity("author:a", "Wei Zhang", ids={"s2": "1"}), entity("author:b", "Wei Zhang", ids={"s2": "2"})]
        pair[1]["distinct_from"] = []  # validation needs the mark, dupes doesn't look at an empty one
        self.assertEqual([reasons for _, _, reasons in graph.dupes(pair)], [["same name", "but a different s2 id"]])

    def test_identifiers(self):
        paper = entity("paper:2401.00001", "P", aliases=["ARXIV:2401.00001", "DOI:10.1/X", "Short"], ids={"s2": "AbC"})
        self.assertEqual(graph.labels(paper), ["P", "Short"])
        self.assertEqual(graph.external_keys(paper), {("arxiv", "2401.00001"), ("doi", "10.1/x"), ("s2", "abc")})
        self.assertEqual(graph.external_keys(entity("tool:x", ids="bad")), set())

    def test_reasons(self):
        def reasons(a, b, kind="dataset"):
            return graph.match_reasons(entity(f"{kind}:a", a), entity(f"{kind}:b", b))

        self.assertEqual(
            graph.match_reasons(entity("author:a", "A", ids={"s2": "1"}), entity("author:b", "B", ids={"s2": "1"})),
            ["same id (s2)"],
        )
        self.assertEqual(reasons("SWE Bench", "swe-bench"), ["same name"])
        self.assertEqual(reasons("J. Smith", "John Smith", "author"), ["similar name (0.71)"])
        self.assertEqual(reasons("Ming-Wei Chang", "Chang Ming-Wei", "author"), ["similar name (0.92)"])
        self.assertEqual(reasons("Terminal-Bench 2.0", "Terminal-Bench 2.1"), ["similar name (0.89)"])
        self.assertEqual(reasons("Jane Doe", "John Smith", "author"), [])
        self.assertEqual(reasons("Tool Alpha", "Tool Beta"), [])
        self.assertEqual(reasons("???", "???"), ["same name"])
        self.assertEqual(reasons("--", "--"), [])  # nothing left of either name to compare
        # No string rule links an acronym to its expansion: an alias does, and only as a possible duplicate.
        self.assertEqual(reasons("RAG", "Retrieval-Augmented Generation"), [])
        expansion = entity("method:a", "Retrieval-Augmented Generation", aliases=["RAG"])
        self.assertEqual(graph.match_reasons(expansion, entity("method:b", "RAG")), ["same name as an alias"])
        # Similarity compares names only, so a short alias doesn't hold every name that starts like it.
        self.assertEqual(graph.match_reasons(expansion, entity("method:c", "RAGAS")), [])

    def test_candidates_skip_other_types_and_distinct(self):
        existing = [
            entity("dataset:a", "Bench 1"),
            entity("tool:b", "Bench 2"),
            entity("dataset:c", "Bench 3", distinct_from=["dataset:new"]),
        ]
        found = graph.candidates(existing, entity("dataset:new", "Bench 5"))
        self.assertEqual([(e["id"], strong) for e, _, strong in found], [("dataset:a", False)])
        self.assertTrue(graph.candidates(existing, entity("dataset:x", "bench-1"))[0][2])

    def test_dupes_and_islands(self):
        entities = [
            entity("concept:a", "Retrieval-Augmented Generation", aliases=["RAG"]),
            entity("concept:b", "RAG"),
            entity("concept:c", "Tool Alpha"),
            entity("concept:d", "Tool Beta"),
            entity("dataset:e", "Bench 1"),
            entity("dataset:f", "Bench 2", distinct_from=["dataset:e"]),
            entity("paper:p", "P"),
            entity("paper:q", "Q"),
        ]
        entities[1]["distinct_from"] = []
        self.assertEqual([(a["id"], b["id"]) for a, b, _ in graph.dupes(entities)], [("concept:a", "concept:b")])
        relations = [relation("paper:p", "uses", "concept:a"), relation("paper:q", "cites", "paper:p")]
        self.assertEqual([e["id"] for e in graph.islands(entities, relations)], ["paper:q"])

    def test_dupes_skips_crowded_trigrams(self):
        import hashlib

        crowd = [
            entity(f"concept:c{n}", f"Agent {hashlib.sha1(str(n).encode()).hexdigest()[:12]}")
            for n in range(graph.BLOCK_CAP + 5)
        ]
        twins = [entity("concept:t1", "Retrieval Generation"), entity("concept:t2", "Retrieval Generations")]
        same_id = [entity("tool:a", "Alpha", ids={"github": "o/r"}), entity("tool:b", "Beta", ids={"github": "o/r"})]
        found = [(a["id"], b["id"]) for a, b, _ in graph.dupes(crowd + twins + same_id)]
        self.assertIn(("concept:t1", "concept:t2"), found)
        self.assertIn(("tool:a", "tool:b"), found)
        # 'Agent' is shared by too many to say anything, and their random suffixes share too little.
        self.assertFalse(any(a.startswith("concept:c") for a, _ in found))

    def test_validate_checks_ids_and_distinct(self):
        cases = {
            "ids must map": [entity("tool:a", ids={"web": "x"})],
            "ids must map ": [entity("tool:a", ids={"s2": " "})],
            "ids must be an object": [entity("tool:a", ids=["s2"])],
            "already used by tool:a": [entity("tool:a", ids={"s2": "1"}), entity("tool:b", ids={"s2": "1"})],
            "distinct_from has an unknown entity 'tool:z'": [entity("tool:a", distinct_from=["tool:z"])],
            "distinct_from has an unknown entity 'tool:a'": [entity("tool:a", distinct_from=["tool:a"])],
        }
        for expected, entities in cases.items():
            errors = graph.validate(entities, [])
            self.assertTrue(any(expected.strip() in error for error in errors), f"{expected}: {errors}")
        self.assertIn("needs an id", graph.validate([{"name": "x", "distinct_from": ["y"]}], [])[0])

    def test_an_external_id_may_repeat_across_types(self):
        model = {"id": "model:x", "type": "model", "name": "X", "ids": {"hf": "org/x"}}
        dataset = {"id": "dataset:x", "type": "dataset", "name": "X", "ids": {"hf": "org/x"}}
        self.assertEqual(graph.validate([model, dataset], []), [])


class Writing(CommandLineBase):
    def entities(self):
        return {e["id"]: e for e in graph.read_jsonl(self.folder / "entities.jsonl")}

    def relations(self):
        return graph.read_jsonl(self.folder / "relations.jsonl")

    def test_add_with_every_field(self):
        code, out, _ = self.run_main(
            "add",
            "--type",
            "dataset",
            "--name",
            "Bench X",
            "--alias",
            "BX",
            "--alias",
            "bench-x",
            "--url",
            "https://example.com",
            "--note",
            "A note",
            "--id",
            "hf=org/bench-x",
        )
        self.assertEqual((code, out.strip()), (0, "added dataset:bench-x"))
        self.assertEqual(
            self.entities()["dataset:bench-x"],
            {
                "id": "dataset:bench-x",
                "type": "dataset",
                "name": "Bench X",
                "aliases": ["BX"],
                "url": "https://example.com",
                "note": "A note",
                "ids": {"hf": "org/bench-x"},
            },
        )

    def test_add_refuses_the_same_name_before_looking_at_ids(self):
        for name, slug in (("Tool B", "b"), ("Tool-B", "other"), ("tool b", None)):
            code, _, err = self.run_main("add", "--type", "tool", "--name", name, *(["--slug", slug] if slug else []))
            self.assertEqual(code, 1)
            self.assertIn("already in the graph", err)

    def test_add_asks_about_possible_duplicates(self):
        code, _, err = self.run_main("add", "--type", "dataset", "--name", "Dataset C2")
        self.assertEqual(code, 3)
        self.assertIn("dataset:c  Dataset C", err)
        code, _, _ = self.run_main("add", "--type", "dataset", "--name", "Dataset C2", "--distinct", "Dataset C")
        self.assertEqual(code, 0)
        self.assertEqual(self.entities()["dataset:dataset-c2"]["distinct_from"], ["dataset:c"])

    def test_bad_ids_and_invalid_results_are_refused(self):
        code, _, err = self.run_main("add", "--type", "tool", "--name", "New", "--id", "web=x")
        self.assertEqual(code, 1)
        self.assertIn("KIND=VALUE", err)
        code, _, err = self.run_main("add", "--type", "tool", "--name", "New", "--url", "ftp://x")
        self.assertEqual(code, 1)
        self.assertIn("change refused", err)
        self.assertNotIn("tool:new", self.entities())

    def test_remove_never_acts_on_a_loose_match(self):
        self.assertEqual(self.run_main("add", "--type", "tool", "--name", "C")[0], 0)
        code, _, err = self.run_main("remove", "C++")
        self.assertEqual(code, 1)
        self.assertIn("did you mean tool:c?", err)
        self.assertIn("tool:c", self.entities())

    def test_a_generated_id_is_made_free_and_an_explicit_one_must_be(self):
        code, _, err = self.run_main("add", "--type", "tool", "--name", "Hammer", "--slug", "b")
        self.assertEqual(code, 1)
        self.assertIn("tool:b is already used by 'Tool B'; pick another --slug", err)
        self.assertEqual(self.run_main("add", "--type", "tool", "--name", "C")[1].strip(), "added tool:c")
        code, out, _ = self.run_main("add", "--type", "tool", "--name", "C++", "--distinct", "tool:c")
        self.assertEqual((code, out.strip()), (0, "added tool:c-2"))

    def test_same_name_with_a_conflicting_id_is_held_not_refused(self):
        self.assertEqual(self.run_main("add", "--type", "author", "--name", "Wei Zhang", "--id", "s2=1")[0], 0)
        argv = ["add", "--type", "author", "--name", "Wei Zhang", "--slug", "wei-zhang-2", "--id", "s2=2"]
        code, _, err = self.run_main(*argv)
        self.assertEqual(code, 3)
        self.assertIn("same name, but a different s2 id", err)
        self.assertEqual(self.run_main(*argv, "--distinct", "author:wei-zhang")[0], 0)

    def test_a_shared_id_stays_strong_and_ids_compare_the_same_way_everywhere(self):
        def judge(ids_a, ids_b, name_b="Model A"):
            return graph.judged(entity("model:a", "Model A", ids=ids_a), entity("model:b", name_b, ids=ids_b))

        # A shared id wins over a conflicting one of another kind.
        self.assertEqual(judge({"s2": "1", "hf": "org/x"}, {"s2": "1", "hf": "org/y"}, "Other")[1], True)
        # Spaces and case don't make a conflict, so a same-name match stays strong.
        self.assertEqual(judge({"hf": " Org/X"}, {"hf": "org/x "}), (["same id (hf)", "same name"], True))
        self.assertEqual(graph.conflicting_ids({"ids": {"hf": " Org/X"}}, {"ids": {"hf": "org/x"}}), [])

    def test_update(self):
        self.run_main("update", "tool:b", "--id", "github=org/b")
        code, out, _ = self.run_main(
            "update",
            "Tool B",
            "--alias",
            "TB",
            "--id",
            "github=ORG/B",
            "--url",
            "https://b.example",
            "--note",
            "Note",
            "--distinct",
            "Dataset C",
            "--distinct",
            "Dataset C",
        )
        self.assertEqual((code, out.strip()), (0, "updated tool:b"))
        tool = self.entities()["tool:b"]
        self.assertEqual(
            (tool["aliases"], tool["ids"], tool["distinct_from"]), (["TB"], {"github": "ORG/B"}, ["dataset:c"])
        )
        code, _, err = self.run_main("update", "tool:b", "--id", "github=other/b")
        self.assertEqual(code, 1)
        self.assertIn("already has github id", err)

    def test_link(self):
        code, out, _ = self.run_main("link", "Alpha", "builds-on", "Concept D", "--source", "s", "--status", "inferred")
        self.assertEqual((code, out.strip()), (0, "linked paper:a builds-on concept:d"))
        code, out, _ = self.run_main(
            "link", "paper:a", "builds-on", "concept:d", "--source", "s", "--status", "inferred"
        )
        self.assertEqual((code, out.strip()), (0, "already linked: paper:a builds-on concept:d"))
        self.assertEqual(len(self.relations()), 3)

    def test_a_verified_link_must_name_the_document_it_was_checked_against(self):
        reason = "Same group (Author A); both study agent memory risk. Inferred"
        code, _, err = self.run_main(
            "link", "paper:a", "related-to", "concept:d", "--source", reason, "--status", "verified"
        )
        self.assertEqual(code, 1)
        self.assertIn("a verified link must name the document it was checked against", err)
        self.assertIn("--status inferred", err)
        self.assertEqual(len(self.relations()), 2)
        code, out, _ = self.run_main(
            "link", "paper:a", "related-to", "concept:d", "--source", reason, "--status", "inferred"
        )
        self.assertEqual((code, out.strip()), (0, "linked paper:a related-to concept:d"))

    def test_merge(self):
        entities = [
            entity("tool:keep", "Keep", ids={"s2": "1"}),
            entity("tool:drop", "Drop", aliases=["D"], url="https://d.example", note="n", ids={"github": "o/d"}),
            entity("tool:x", "X", distinct_from=["tool:drop"]),
            entity("tool:y", "Y", distinct_from=["tool:drop", "tool:keep"]),
            entity("paper:p", "P"),
        ]
        relations = [
            relation("paper:p", "uses", "tool:keep", status="inferred"),
            relation("paper:p", "uses", "tool:drop"),
            relation("tool:drop", "related-to", "tool:keep"),
            relation("tool:x", "related-to", "tool:drop"),
            relation("tool:x", "related-to", "tool:keep", status="inferred"),
        ]
        self.write(entities, relations)
        code, out, _ = self.run_main("merge", "Keep", "tool:drop")
        self.assertEqual((code, out.strip()), (0, "merged tool:drop into tool:keep"))
        merged = self.entities()
        self.assertNotIn("tool:drop", merged)
        self.assertEqual(merged["tool:keep"]["aliases"], ["Drop", "D"])
        self.assertEqual(merged["tool:keep"]["ids"], {"s2": "1", "github": "o/d"})
        self.assertEqual(merged["tool:keep"]["url"], "https://d.example")
        self.assertEqual(merged["tool:x"]["distinct_from"], ["tool:keep"])
        self.assertEqual(merged["tool:y"]["distinct_from"], ["tool:keep"])
        self.assertEqual(
            [(r["from"], r["to"], r["status"]) for r in self.relations()],
            [("paper:p", "tool:keep", "verified"), ("tool:x", "tool:keep", "verified")],
        )

    def test_unlink_and_remove(self):
        code, out, _ = self.run_main("unlink", "Paper A", "uses", "Tool B")
        self.assertEqual((code, out.strip()), (0, "unlinked paper:a uses tool:b"))
        code, _, err = self.run_main("unlink", "paper:a", "uses", "tool:b")
        self.assertEqual(code, 1)
        self.assertIn("no relation", err)
        self.write(
            [
                entity("tool:a", "A"),
                entity("tool:b", "B", distinct_from=["tool:a"]),
                entity("tool:c", "C", distinct_from=["tool:a", "tool:b"]),
                entity("tool:d", "D"),
            ],
            [relation("tool:a", "related-to", "tool:b"), relation("tool:b", "related-to", "tool:c")],
        )
        code, out, _ = self.run_main("remove", "A")
        self.assertEqual((code, out.strip()), (0, "removed tool:a and 1 relations"))
        left = self.entities()
        self.assertEqual(sorted(left), ["tool:b", "tool:c", "tool:d"])
        self.assertNotIn("distinct_from", left["tool:b"])
        self.assertEqual(left["tool:c"]["distinct_from"], ["tool:b"])
        self.assertEqual(len(self.relations()), 1)

    def test_merge_keeps_distinct_decisions(self):
        self.write(
            [
                entity("tool:a", "A", distinct_from=["tool:c"]),
                entity("tool:b", "B", distinct_from=["tool:c", "tool:d"]),
                entity("tool:c", "C"),
                entity("tool:d", "D"),
            ],
            [],
        )
        self.assertEqual(self.run_main("merge", "tool:a", "tool:b")[0], 0)
        self.assertEqual(self.entities()["tool:a"]["distinct_from"], ["tool:c", "tool:d"])
        self.write([entity("tool:a", "A"), entity("tool:b", "B")], [])
        self.assertEqual(self.run_main("merge", "tool:a", "tool:b")[0], 0)
        self.assertNotIn("distinct_from", self.entities()["tool:a"])

    def test_merge_refuses_entities_marked_distinct(self):
        self.write([entity("tool:a", "A", distinct_from=["tool:b"]), entity("tool:b", "B")], [])
        code, _, err = self.run_main("merge", "tool:a", "tool:b")
        self.assertEqual(code, 1)
        self.assertIn("marked as distinct, so they can't be merged", err)

    def test_merge_refuses_mismatches(self):
        for keep, drop in (("tool:b", "tool:b"), ("tool:b", "dataset:c")):
            code, _, err = self.run_main("merge", keep, drop)
            self.assertEqual(code, 1)
            self.assertIn("two different entities of the same type", err)

    def test_dupes_and_islands_commands(self):
        self.assertIn("no likely duplicates", self.run_main("dupes")[1])
        self.assertIn("every paper has extracted entities", self.run_main("islands")[1])
        self.write(ENTITIES + [entity("dataset:c2", "Dataset C 2"), entity("paper:e", "Paper E")], RELATIONS)
        self.assertIn("dataset:c  <->  dataset:c2", self.run_main("dupes")[1])
        self.assertIn("paper:e  Paper E", self.run_main("islands")[1])


class Safety(CommandLineBase):
    def test_types_are_checked_before_use(self):
        cases = {
            "aliases must be a list of text": entity("tool:x", "X", aliases="oops"),
            "url must be text": entity("tool:x", "X", url=5),
            "distinct_from must be a list of text": entity("tool:x", "X", distinct_from=[1]),
            "type must be text": {"id": "tool:x", "name": "X", "type": ["tool"]},
        }
        for expected, record in cases.items():
            self.assertTrue(any(expected in e for e in graph.validate([record], [])), expected)
        self.assertIn("entity needs an id", graph.validate([{"id": 5, "name": "X"}], [])[0])
        self.assertIn(
            "must be text", graph.validate(ENTITIES, [{"from": "paper:a", "rel": ["uses"], "to": "tool:b"}])[0]
        )
        self.write([entity("tool:x", "X", url=5)], [])
        code, _, err = self.run_main("validate")
        self.assertEqual(code, 1)
        self.assertIn("url must be text", err)

    def test_ambiguous_names_need_an_id(self):
        self.write(
            [
                entity("author:a", "Wei Zhang"),
                entity("author:b", "Wei Zhang", distinct_from=["author:a"]),
                entity("paper:p", "P"),
            ],
            [],
        )
        code, _, err = self.run_main(
            "link", "P", "authored-by", "Wei Zhang", "--source", "Semantic Scholar", "--status", "verified"
        )
        self.assertEqual(code, 1)
        self.assertIn("matches more than one entity, so use an id: author:a, author:b", err)
        code, _, _ = self.run_main(
            "link", "P", "authored-by", "author:b", "--source", "Semantic Scholar", "--status", "verified"
        )
        self.assertEqual(code, 0)

    def test_missing_folder(self):
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with (
            contextlib.redirect_stderr(out),
            contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")),
        ):
            code = graph.main(["--data", str(self.folder / "nope"), "validate"])
        out.seek(0)
        self.assertEqual(code, 1)
        self.assertIn("graph folder not found", out.read())

    def test_a_held_lock_makes_a_command_wait_and_then_give_up(self):
        lock = self.folder / graph.LOCK_FILE
        with open(lock, "a+b") as holder:
            self.assertTrue(graph.try_lock(holder))
            with mock.patch.object(graph, "LOCK_WAIT", 0.2):
                code, _, err = self.run_main("validate")
            graph.unlock(holder)
        self.assertEqual(code, 1)
        self.assertIn("another graph command is still running", err)
        self.assertEqual(self.run_main("validate")[0], 0)

    def test_a_leftover_lock_file_blocks_nobody(self):
        (self.folder / graph.LOCK_FILE).write_bytes(b"left by a process that died")
        self.assertEqual(self.run_main("validate")[0], 0)

    def test_a_command_waits_for_a_lock_that_is_released_meanwhile(self):
        holder = open(self.folder / graph.LOCK_FILE, "a+b")  # noqa: SIM115  closed by the cleanup
        self.addCleanup(holder.close)
        self.assertTrue(graph.try_lock(holder))
        released = []

        def release(seconds):
            if not released:
                released.append(1)
                graph.unlock(holder)

        with mock.patch.object(graph.time, "sleep", side_effect=release):
            self.assertEqual(self.run_main("validate")[0], 0)
        self.assertEqual(released, [1])

    def test_interrupted_saves_are_finished_or_discarded(self):
        new_entities = self.folder / "entities.jsonl.tmp"
        new_entities.write_text(json.dumps(entity("tool:z", "Z")) + "\n", encoding="utf-8")
        self.assertEqual(self.run_main("validate")[0], 0)
        self.assertFalse(new_entities.exists())
        self.assertNotIn("tool:z", self.entities())
        new_entities.write_text(json.dumps(entity("tool:z", "Z")) + "\n", encoding="utf-8")
        (self.folder / "relations.jsonl.tmp").write_text("", encoding="utf-8")
        (self.folder / graph.COMMIT_FILE).write_text("", encoding="utf-8")
        self.assertEqual(self.run_main("validate")[0], 0)
        self.assertEqual(list(self.entities()), ["tool:z"])
        self.assertFalse((self.folder / graph.COMMIT_FILE).exists())

    def test_concurrent_writes_keep_every_change(self):
        import subprocess

        names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    graph.__file__,
                    "--data",
                    str(self.folder),
                    "add",
                    "--type",
                    "method",
                    "--name",
                    f"Zq{name}",
                    "--slug",
                    name.lower(),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for name in names
        ]
        results = [(p.wait(timeout=60), p.stderr.read().decode()) for p in processes]
        for process in processes:
            process.stdout.close()
            process.stderr.close()
        added = sorted(e for e in self.entities() if e.startswith("method:"))
        self.assertEqual(added, sorted(f"method:{name.lower()}" for name in names), results)

    def entities(self):
        return {e["id"]: e for e in graph.read_jsonl(self.folder / "entities.jsonl")}


class Citations(CommandLineBase):
    def setUp(self):
        super().setUp()
        self.write(
            [
                entity("paper:2401.00001", "Main"),
                entity("paper:2401.00002", "Cited", aliases=["ARXIV:2401.00002"]),
                entity("paper:x", "Citing", ids={"doi": "10.1/C"}),
                entity("paper:y", "Known", ids={"s2": "known"}),
                entity("tool:t", "Tool"),
            ],
            [],
        )

    def record(self, data):
        path = self.folder / "s2.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_links_references_and_citations(self):
        path = self.record(
            {
                "paperId": "MAIN",
                "references": [
                    {"paperId": "r1", "externalIds": {"ArXiv": "2401.00002"}},
                    {"paperId": "known"},
                    {"paperId": "self", "externalIds": {"ArXiv": "2401.00001"}},
                    {"paperId": "r9", "externalIds": None},
                    {"paperId": None},
                ],
                "citations": [{"paperId": "c1", "externalIds": {"DOI": "10.1/c"}}],
            }
        )
        code, out, _ = self.run_main("cites", "Main", path)
        self.assertEqual(code, 0)
        self.assertIn("3 citation links added", out)
        links = [(r["from"], r["to"], r["source"]) for r in graph.read_jsonl(self.folder / "relations.jsonl")]
        self.assertEqual(
            links,
            [
                ("paper:2401.00001", "paper:2401.00002", "Semantic Scholar references"),
                ("paper:2401.00001", "paper:y", "Semantic Scholar references"),
                ("paper:x", "paper:2401.00001", "Semantic Scholar citations"),
            ],
        )
        main = {e["id"]: e for e in graph.read_jsonl(self.folder / "entities.jsonl")}["paper:2401.00001"]
        self.assertEqual(main["ids"], {"s2": "MAIN"})
        code, out, _ = self.run_main(
            "cites", "Main", self.record({"paperId": "OTHER", "references": [{"paperId": "known"}]})
        )
        self.assertIn("0 citation links added", out)

    # A paper that add failed to recognise as a duplicate surfaces when its Semantic Scholar id is filled in
    # later: the save is refused, so the missed duplicate can't stay hidden.
    def test_backfilled_id_used_by_another_paper_is_refused(self):
        code, _, err = self.run_main("update", "Main", "--id", "s2=known")
        self.assertEqual(code, 1)
        self.assertIn("change refused", err)
        self.assertIn("s2 id 'known' is already used by", err)
        main = {e["id"]: e for e in graph.read_jsonl(self.folder / "entities.jsonl")}["paper:2401.00001"]
        self.assertNotIn("ids", main)

    def test_cites_saves_nothing_when_the_adopted_id_is_used(self):
        # The whole import fails, not just the id adoption. This pins today's behaviour, not a desired one.
        path = self.record(
            {"paperId": "known", "references": [{"paperId": "r1", "externalIds": {"ArXiv": "2401.00002"}}]}
        )
        code, _, err = self.run_main("cites", "Main", path)
        self.assertEqual(code, 1)
        self.assertIn("s2 id 'known' is already used by", err)
        self.assertEqual(graph.read_jsonl(self.folder / "relations.jsonl"), [])

    def papers(self):
        return {e["id"]: e for e in graph.read_jsonl(self.folder / "entities.jsonl")}

    def test_cites_saves_the_papers_standing(self):
        record = {"paperId": "MAIN", "citationCount": 12, "influentialCitationCount": 3, "venue": "", "year": 2024}
        with mock.patch.object(graph, "today", return_value="2026-11-11"):
            code, out, _ = self.run_main("cites", "Main", self.record({**record, "references": []}))
        self.assertEqual(code, 0)
        self.assertIn("standing: paper:2401.00001: 12 citations, checked 2026-11-11", out)
        expected = {"citations": 12, "influential": 3, "year": 2024, "checked": "2026-11-11"}
        self.assertEqual(self.papers()["paper:2401.00001"]["standing"], expected)
        code, out, _ = self.run_main("cites", "Cited", self.record({"paperId": "C", "references": []}))
        self.assertNotIn("standing", out)
        self.assertNotIn("standing", self.papers()["paper:2401.00002"])

    def test_standing_updates_every_matched_paper_from_a_batch(self):
        batch = [
            {"requestedId": "ARXIV:2401.00002", "paperId": "C2", "externalIds": {"ArXiv": "2401.00002"},
             "citationCount": 5, "venue": "NeurIPS", "year": True},
            {"requestedId": "known", "paperId": "known", "citationCount": 0, "influentialCitationCount": None},
            {"requestedId": "ARXIV:2499.00001", "error": "not found"},
            {"paperId": "known", "citationCount": "many"},
        ]  # fmt: skip
        with mock.patch.object(graph, "today", return_value="2026-11-11"):
            code, out, _ = self.run_main("standing", self.record(batch))
        self.assertEqual(code, 0)
        self.assertEqual(
            out.strip(), "2 papers updated, 1 without citation data, 1 record matched no paper in the graph"
        )
        papers = self.papers()
        cited, known = papers["paper:2401.00002"], papers["paper:y"]
        self.assertEqual(cited["standing"], {"citations": 5, "venue": "NeurIPS", "checked": "2026-11-11"})
        self.assertEqual(cited["ids"], {"s2": "C2"})
        self.assertEqual(known["standing"], {"citations": 0, "checked": "2026-11-11"})
        code, out, _ = self.run_main("standing", self.record({"paperId": "known", "citationCount": 1}))
        self.assertEqual((code, out.strip()), (0, "1 paper updated, 0 records matched no paper in the graph"))
        self.assertEqual(self.papers()["paper:y"]["standing"]["citations"], 1)
        for bad in ([1], "text"):
            code, _, err = self.run_main("standing", self.record(bad))
            self.assertEqual(code, 1)
            self.assertIn("expected the output of: s2.py batch", err)
        code, _, err = self.run_main("standing", str(self.folder / "missing.json"))
        self.assertEqual(code, 1)
        self.assertIn("can't read", err)

    def test_standing_due_lists_papers_never_checked_or_checked_long_ago(self):
        def checked(day):
            return {"citations": 1, "checked": day}

        self.write(
            [
                entity("paper:2401.00001", "Arxiv slug"),
                entity("paper:s", "S2", ids={"s2": "S2ID", "doi": "10.1/x"}, standing=checked("2026-11-01")),
                entity("paper:d", "Doi", aliases=["DOI:10.1/D"], standing=checked("2026-01-01")),
                entity("paper:blog", "Blog"),
                entity("tool:t", "Tool"),
            ],
            [],
        )
        due = self.folder / "due.txt"
        with mock.patch.object(graph.datetime, "date", wraps=graph.datetime.date) as date:
            date.today.return_value = graph.datetime.date(2026, 11, 11)
            code, out, _ = self.run_main("standing-due", str(due))
            self.assertEqual((code, out.strip()), (0, "2 papers due"))
            self.assertEqual(due.read_text(encoding="utf-8"), "ARXIV:2401.00001\nDOI:10.1/d\n")
            self.assertEqual(self.run_main("standing-due", str(due), "--days", "5")[1].strip(), "3 papers due")
            self.assertEqual(due.read_text(encoding="utf-8").split(), ["ARXIV:2401.00001", "s2id", "DOI:10.1/d"])
            self.write([entity("paper:2401.00001", "Arxiv slug")], [])
            self.assertEqual(self.run_main("standing-due", str(due))[1].strip(), "1 paper due")
            self.write([entity("paper:blog", "Blog")], [])
            self.assertEqual(self.run_main("standing-due", str(due))[1].strip(), "no papers due")
            self.assertEqual(due.read_text(encoding="utf-8"), "")
        code, _, err = self.run_main("standing-due", str(self.folder / "no-such-folder" / "due.txt"))
        self.assertEqual(code, 1)
        self.assertIn("can't write", err)

    def test_merge_keeps_the_newer_standing(self):
        self.write(
            [
                entity("paper:a", "A", standing={"citations": 1, "checked": "2026-01-01"}),
                entity("paper:b", "B", standing={"citations": 9, "checked": "2026-06-01"}),
                entity("paper:c", "C"),
            ],
            [],
        )
        self.run_main("merge", "paper:a", "paper:b")
        self.assertEqual(self.papers()["paper:a"]["standing"]["citations"], 9)
        self.run_main("merge", "paper:a", "paper:c")
        self.assertEqual(self.papers()["paper:a"]["standing"]["citations"], 9)
        self.write(
            [entity("paper:c", "C"), entity("paper:a", "A", standing={"citations": 1, "checked": "2026-01-01"})], []
        )
        self.run_main("merge", "paper:c", "paper:a")
        self.assertEqual(self.papers()["paper:c"]["standing"]["citations"], 1)

    def test_a_bad_standing_is_invalid(self):
        good = {"citations": 1, "checked": "2026-01-01"}
        cases = [
            (entity("tool:t", standing=good), "only papers have a standing"),
            (entity("paper:p", standing={"citations": 1}), "standing has bad or missing checked"),
            (entity("paper:p", standing={**good, "citations": -1}), "standing has bad or missing citations"),
            (entity("paper:p", standing={**good, "citations": True}), "standing has bad or missing citations"),
            (entity("paper:p", standing={**good, "year": "2024"}), "standing has bad or missing year"),
            (entity("paper:p", standing={**good, "venue": 5}), "standing has bad or missing venue"),
            (entity("paper:p", standing={**good, "rank": 1}), "standing has bad or missing rank"),
            (entity("paper:p", standing={**good, "checked": "soon"}), "standing has bad or missing checked"),
            (entity("paper:p", standing={"citations": "x", "year": "y"}), "bad or missing checked, citations, year"),
            (entity("paper:p", standing=[1]), "standing must be an object"),
        ]
        for item, expected in cases:
            with self.subTest(item=item):
                self.assertTrue(any(expected in e for e in graph.validate([item], [])), graph.validate([item], []))
        self.assertEqual(graph.validate([entity("paper:p", standing={**good, "venue": "X", "year": 2024})], []), [])
        self.assertEqual(graph.validate([entity("paper:p", standing={"checked": "2026-01-01"})], []), [])

    def test_standing_also_links_papers_from_the_reference_lists_in_a_batch(self):
        batch = [
            {
                "requestedId": "ARXIV:2401.00001",
                "paperId": "MAIN",
                "citationCount": 4,
                "references": [
                    {"paperId": "r1", "externalIds": {"ArXiv": "2401.00002"}},
                    {"paperId": "known"},
                    {"paperId": "elsewhere", "externalIds": None},
                    {"paperId": "self", "externalIds": {"ArXiv": "2401.00001"}},
                ],
            },
            {"requestedId": "known", "paperId": "known", "citationCount": 1, "references": None},
            {"requestedId": "ARXIV:2499.00001", "error": "not found"},
        ]
        with mock.patch.object(graph, "today", return_value="2026-11-11"):
            code, out, _ = self.run_main("standing", self.record(batch))
        self.assertEqual(code, 0)
        self.assertEqual(
            out.strip(), "2 papers updated, 2 citation links added, 1 record matched no paper in the graph"
        )
        links = [(r["from"], r["rel"], r["to"], r["source"]) for r in graph.read_jsonl(self.folder / "relations.jsonl")]
        self.assertEqual(
            links,
            [
                ("paper:2401.00001", "cites", "paper:2401.00002", "Semantic Scholar references"),
                ("paper:2401.00001", "cites", "paper:y", "Semantic Scholar references"),
            ],
        )
        self.assertEqual(self.papers()["paper:2401.00001"]["standing"]["citations"], 4)
        code, out, _ = self.run_main("standing", self.record(batch))
        self.assertEqual(code, 0)
        self.assertIn("0 citation links added", out)

    def test_references_link_a_paper_even_when_semantic_scholar_has_no_counts_for_it(self):
        batch = [
            {
                "requestedId": "ARXIV:2401.00001",
                "paperId": "MAIN",
                "references": [{"paperId": "r1", "externalIds": {"ArXiv": "2401.00002"}}],
            }
        ]
        code, out, _ = self.run_main("standing", self.record(batch))
        self.assertEqual(code, 0)
        self.assertEqual(
            out.strip(),
            "0 papers updated, 1 without citation data, 1 citation link added, 0 records matched no paper in the graph",
        )
        self.assertEqual(len(graph.read_jsonl(self.folder / "relations.jsonl")), 1)

    def test_papers_semantic_scholar_does_not_know_are_marked_checked_not_asked_again(self):
        old = {"citations": 5, "checked": "2025-01-01"}
        self.write(
            [
                entity("paper:2401.00001", "New arXiv paper"),
                entity("paper:y", "Known before", ids={"s2": "known"}, standing=old),
                entity("paper:x", "No count", ids={"doi": "10.1/C"}),
                entity("paper:z", "Fine", ids={"s2": "fine"}),
            ],
            [],
        )
        batch = [
            {"requestedId": "ARXIV:2401.00001", "error": "not found"},
            {"requestedId": "known", "error": "not found"},
            {"requestedId": "DOI:10.1/c", "paperId": "X", "externalIds": {"DOI": "10.1/C"}},
            {"requestedId": "fine", "paperId": "fine", "citationCount": 2},
            {"requestedId": "ARXIV:2499.00001", "error": "not found"},
        ]
        with mock.patch.object(graph, "today", return_value="2026-11-11"):
            code, out, _ = self.run_main("standing", self.record(batch))
        self.assertEqual(code, 0)
        self.assertEqual(
            out.strip(), "1 paper updated, 3 without citation data, 1 record matched no paper in the graph"
        )
        papers = self.papers()
        self.assertEqual(papers["paper:2401.00001"]["standing"], {"checked": "2026-11-11"})
        self.assertEqual(papers["paper:x"]["standing"], {"checked": "2026-11-11"})
        self.assertEqual(papers["paper:y"]["standing"], old)
        self.assertEqual(self.run_main("validate")[0], 0)
        due = self.folder / "due.txt"
        with mock.patch.object(graph.datetime, "date", wraps=graph.datetime.date) as date:
            date.today.return_value = graph.datetime.date(2026, 11, 12)
            self.run_main("standing-due", str(due))
        self.assertEqual(due.read_text(encoding="utf-8").split(), ["known"])

    def test_refuses_bad_input(self):
        cases = [
            (("tool:t", self.record({"references": []})), "is not a paper"),
            (("Main", str(self.folder / "missing.json")), "can't read"),
            (("Main", self.record([1])), "expected the output"),
            (("Main", self.record({"paperId": "x"})), "expected the output"),
        ]
        for argv, expected in cases:
            code, _, err = self.run_main("cites", *argv)
            self.assertEqual(code, 1)
            self.assertIn(expected, err)


class CommandEdges(CommandLineBase):
    """Commands at their edges: links on both sides of the one asked for, counts, ranks, dates, and options."""

    def entities(self):
        return {e["id"]: e for e in graph.read_jsonl(self.folder / "entities.jsonl")}

    def relations(self):
        return [(r["from"], r["rel"], r["to"]) for r in graph.read_jsonl(self.folder / "relations.jsonl")]

    def test_unlink_removes_only_its_link_however_the_others_sort(self):
        others = [
            relation("paper:a", "builds-on", "tool:b"),
            relation("paper:a", "uses", "dataset:c"),
            relation("tool:b", "evaluates-on", "dataset:c"),
        ]
        self.write(ENTITIES, [relation("paper:a", "uses", "tool:b"), *others])
        code, _, err = self.run_main("unlink", "paper:a", "uses", "concept:d")
        self.assertEqual(code, 1)
        self.assertIn("no relation paper:a uses concept:d", err)
        self.assertEqual(self.run_main("unlink", "paper:a", "uses", "tool:b")[0], 0)
        self.assertEqual(self.relations(), [(r["from"], r["rel"], r["to"]) for r in others])

    def test_remove_counts_the_links_it_removed(self):
        self.write(ENTITIES, [*RELATIONS, relation("paper:a", "related-to", "concept:d")])
        self.assertEqual(self.run_main("remove", "tool:b")[1].strip(), "removed tool:b and 2 relations")

    def test_add_saves_a_url_and_a_note_and_keeps_text_unescaped(self):
        fields = ("--slug", "j", "--url", "https://j.example", "--note", "n")
        self.run_main("add", "--type", "tool", "--name", "Jürgen Kalb", *fields)
        added = self.entities()["tool:j"]
        self.assertEqual((added["url"], added["note"]), ("https://j.example", "n"))
        self.assertIn("Jürgen Kalb", (self.folder / "entities.jsonl").read_text(encoding="utf-8"))

    def test_update_saves_a_url_and_a_note(self):
        self.run_main("update", "tool:b", "--url", "https://b.example", "--note", "a note")
        updated = self.entities()["tool:b"]
        self.assertEqual((updated["url"], updated["note"]), ("https://b.example", "a note"))

    def test_update_refuses_a_different_id_whichever_sorts_first(self):
        for current, new in (("2", "1"), ("1", "2")):
            with self.subTest(current=current):
                self.write([entity("tool:a", ids={"s2": current})], [])
                code, _, err = self.run_main("update", "tool:a", "--id", f"s2={new}")
                self.assertEqual(code, 1)
                self.assertIn("already has s2 id", err)

    def test_merge_needs_the_same_type_in_either_order(self):
        for keep, drop in (("paper:a", "tool:b"), ("tool:b", "paper:a")):
            code, _, err = self.run_main("merge", keep, drop)
            self.assertEqual(code, 1, keep)
            self.assertIn("two different entities of the same type", err)

    def test_merge_keeps_the_newer_standing(self):
        for drop_checked, kept_checked in (
            ("2026-01-01", "2026-01-02"),
            ("2026-01-02", "2026-01-02"),
            ("2026-01-03", "2026-01-03"),
        ):
            with self.subTest(drop=drop_checked):
                keep = entity("paper:keep", "Keep", standing={"citations": 1, "checked": "2026-01-02"})
                drop = entity("paper:drop", "Drop", standing={"citations": 9, "checked": drop_checked})
                self.write([keep, drop], [])
                self.run_main("merge", "paper:keep", "paper:drop")
                self.assertEqual(self.entities()["paper:keep"]["standing"]["checked"], kept_checked)
                # On the same day the kept entity's own standing stays.
                self.assertEqual(
                    self.entities()["paper:keep"]["standing"]["citations"], 9 if drop_checked > "2026-01-02" else 1
                )

    def test_merge_repoints_distinct_marks_beside_others(self):
        entities = [
            entity("tool:keep", "Keep"),
            entity("tool:drop", "Drop"),
            entity("tool:a", "A"),
            entity("tool:x", "X", distinct_from=["tool:a", "tool:drop"]),
        ]
        self.write(entities, [])
        self.run_main("merge", "tool:keep", "tool:drop")
        self.assertEqual(self.entities()["tool:x"]["distinct_from"], ["tool:a", "tool:keep"])

    def test_merging_links_keeps_the_first_of_equal_rank_and_a_verified_one_over_an_inferred_one(self):
        entities = [entity("tool:keep", "Keep"), entity("tool:drop", "Drop"), entity("paper:p", "P")]
        cases = (
            (("verified", "s1"), ("verified", "s2"), ("verified", "s1")),
            (("verified", "s1"), ("inferred", "s2"), ("verified", "s1")),
            (("inferred", "s1"), ("verified", "s2"), ("verified", "s2")),
        )
        for first, second, kept in cases:
            with self.subTest(first=first, second=second):
                links = [
                    relation("paper:p", "uses", "tool:keep", status=first[0], source=f"ARXIV:2401.00001, {first[1]}"),
                    relation("paper:p", "uses", "tool:drop", status=second[0], source=f"ARXIV:2401.00001, {second[1]}"),
                ]
                self.write(entities, links)
                self.run_main("merge", "tool:keep", "tool:drop")
                (merged,) = graph.read_jsonl(self.folder / "relations.jsonl")
                self.assertEqual((merged["status"], merged["source"][-2:]), kept)

    def test_a_paper_cites_papers_on_either_side_of_its_id_but_never_itself(self):
        papers = [entity("paper:m", "Middle", ids={"s2": "m"}), entity("paper:a", "A", ids={"s2": "a"})]
        self.write([*papers, entity("paper:z", "Z", ids={"s2": "z"})], [])
        record = {"paperId": "m", "references": [{"paperId": "a"}, {"paperId": "m"}, {"paperId": "z"}], "citations": []}
        (self.folder / "s2.json").write_text(json.dumps(record), encoding="utf-8")
        code, out, _ = self.run_main("cites", "paper:m", str(self.folder / "s2.json"))
        self.assertEqual(code, 0)
        self.assertIn("linked paper:m cites paper:a", out)
        self.assertIn("linked paper:m cites paper:z", out)
        self.assertEqual(sorted(self.relations()), [("paper:m", "cites", "paper:a"), ("paper:m", "cites", "paper:z")])

    def test_a_requested_id_with_no_value_is_asked_about_as_written(self):
        self.assertEqual(graph.requested_keys({"requestedId": "ARXIV:"}), {("s2", "arxiv:")})

    def test_a_paper_checked_exactly_the_given_days_ago_is_due(self):
        import datetime

        cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        self.write([entity("paper:2401.00001", standing={"citations": 1, "checked": cutoff})], [])
        due = self.folder / "due.txt"
        self.assertEqual(self.run_main("standing-due", str(due))[1].strip(), "1 paper due")

    def test_the_records_that_came_with_reference_lists_are_counted(self):
        papers = [entity("paper:2401.00001"), entity("paper:2401.00002"), entity("paper:2401.00003")]
        records = [
            {"requestedId": f"ARXIV:2401.0000{n}", "paperId": f"s{n}", "citationCount": 1, "references": []}
            for n in (1, 2)
        ] + [{"requestedId": "ARXIV:2401.00003", "paperId": "s3", "citationCount": 1}]
        results = graph.apply_standing(papers, [], records)
        self.assertEqual((results["with references"], results["updated"], results["links"]), (2, 3, 0))
        records = [{"requestedId": "ARXIV:2401.00001", "paperId": "s1", "citationCount": 1, "references": []}]
        self.write(papers, [])
        (self.folder / "batch.json").write_text(json.dumps(records), encoding="utf-8")
        out = self.run_main("standing", str(self.folder / "batch.json"))[1]
        self.assertIn("0 citation links added", out)

    def test_a_blank_line_inside_a_graph_file_is_skipped(self):
        (self.folder / "entities.jsonl").write_text(
            "\n".join([json.dumps(ENTITIES[0]), "", json.dumps(ENTITIES[1])]), encoding="utf-8"
        )
        (self.folder / "relations.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(len(self.entities()), 2)

    def test_validation_goes_on_after_a_malformed_entity(self):
        errors = graph.validate([loaded({"name": "no id"}), entity("tool:a", "Same"), entity("tool:b", "Same")], [])
        self.assertTrue(any("needs an id" in error for error in errors), errors)
        self.assertTrue(any("already used by tool:a" in error for error in errors), errors)

    def test_a_name_or_id_already_used_is_reported_whichever_id_sorts_first(self):
        errors = graph.validate([entity("tool:b", "Same"), entity("tool:a", "Same")], [])
        self.assertTrue(any("'Same' is already used by tool:b" in error for error in errors), errors)
        errors = graph.validate([entity("tool:b", ids={"s2": "1"}), entity("tool:a", "Other", ids={"s2": "1"})], [])
        self.assertTrue(any("s2 id '1' is already used by tool:b" in error for error in errors), errors)

    def test_a_repeated_id_is_reported_once_as_a_duplicate(self):
        twins = [entity("tool:a", "Same", ids={"s2": "1"}), entity("tool:a", "Same", ids={"s2": "1"})]
        self.assertEqual(graph.validate(twins, []), ["duplicate entity id: tool:a"])

    def test_only_a_paper_has_a_standing_or_can_be_an_island(self):
        for kind in ("author", "tool"):
            other = entity(f"{kind}:x", standing={"citations": 1, "checked": "2026-01-01"})
            self.assertIn(f"{kind}:x: only papers have a standing", graph.validate([other], []), kind)
        alone = [entity("author:x"), entity("paper:p"), entity("tool:y")]
        self.assertEqual([e["id"] for e in graph.islands(alone, [])], ["paper:p"])

    def test_listing_commands_succeed_with_or_without_results(self):
        for command in ("dupes", "islands"):
            self.assertEqual(self.run_main(command)[0], 0, command)

    def test_required_options_and_documented_defaults(self):
        parser = graph.build_parser()
        for argv in (
            [],
            ["add", "--name", "X"],
            ["add", "--type", "tool"],
            ["link", "a", "uses", "b", "--status", "verified"],
            ["link", "a", "uses", "b", "--source", "s"],
        ):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit, msg=argv) as stopped:
                parser.parse_args(argv)
            self.assertEqual(stopped.exception.code, 2, argv)
        self.assertEqual(parser.parse_args(["neighbours", "x"]).depth, 1)
        self.assertEqual(parser.parse_args(["standing-due", "f"]).days, 30)

    def test_a_held_lock_is_tried_until_its_deadline_has_passed(self):
        clock = [100.0]

        def sleep(seconds):
            clock[0] += 0.25  # exact steps, so the deadline is hit exactly

        lock = self.folder / "held.lock"
        with (
            open(lock, "a+b") as holder,
            mock.patch.object(graph.time, "monotonic", lambda: clock[0]),
            mock.patch.object(graph.time, "sleep", side_effect=sleep) as slept,
        ):
            self.assertTrue(graph.try_lock(holder))
            with self.assertRaisesRegex(graph.GraphError, "busy"):
                with graph.file_lock(lock, 0.5, "busy"):
                    pass
            graph.unlock(holder)
        # Tried at 100.0, 100.25, 100.5 (the deadline itself), and 100.75, which is past it.
        self.assertEqual(slept.call_count, 3)


if __name__ == "__main__":
    unittest.main()
