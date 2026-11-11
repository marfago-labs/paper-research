"""Tests for the pair builder, with the network mocked. Run: python evals/dedup/test_build_dataset.py"""

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import random
import runpy
import sys
import tempfile
import unittest
import urllib.error
from collections import Counter
from pathlib import Path
from unittest import mock

import build_dataset as build

AUTHOR_ROWS = [
    {"item": "17/1", "label": "Lei Li", "alias": "L. Li", "orcid": "0000-0001"},
    {"item": "17/1", "label": "Lei Li", "alias": "Lei Li"},  # the label again: not an extra name
    {"item": "17/1", "label": "Lei Li", "alias": "L. Li"},  # repeated: kept once
    {"item": "17/1", "label": "Lei Li", "alias": "LEI-LI"},  # the label in other case and separators: the same name
    {"item": "17/2", "label": "Lin Li"},
    {"item": "17/3", "label": "Wei Zhang"},
]
HOMONYM_ROWS = [{"item": "17/3", "other": "10/9"}, {"item": "17/3", "other": "17/2"}]
OTHER_PEOPLE = [{"item": "10/9", "label": "Wei Zhang", "orcid": "0000-0009"}]
TOOL_ROWS = [
    {"item": "Q1", "label": "Apache Subversion", "alias": "SVN", "repo": "https://github.com/apache/subversion.git"},
    {"item": "Q2", "label": "Apache Spark"},
]
MODEL_ROWS = [{"item": "Q5", "label": "GPT-4"}]
PWC = "https://paperswithcode.com/method/"
METHODS = [
    {"url": PWC + "ewc", "name": "EWC", "full_name": "Elastic Weight Consolidation", "num_papers": 9},
    {"url": PWC + "x", "name": "How to Contact Support", "full_name": "", "num_papers": 1},
    {"url": PWC + "y", "name": "Refund?", "full_name": "", "num_papers": 5},
    {"url": PWC + "net", "name": "Elastic Net", "full_name": "elastic net", "num_papers": 3},
]


def group(gold, name, kind="tool", names=None, source="wikidata", ids=None):
    return {"gold": gold, "type": kind, "names": names or [name], "ids": ids or {}, "source": source}


def first_choice():
    """A random source whose choices are the first option and whose shuffles keep the order."""
    rng = mock.MagicMock()
    rng.choice = lambda options: options[0]
    rng.shuffle = lambda items: None
    rng.sample = lambda items, k: list(items)[:k]
    rng.randint = lambda low, high: low
    return rng


def response_of(body, link=None):
    response = mock.MagicMock()
    stream = io.BytesIO(json.dumps(body).encode())
    response.__enter__.return_value = response
    response.read = stream.read
    response.headers = {"Link": link} if link else {}
    return response


class Fetching(unittest.TestCase):
    def test_sparql_shortens_entity_uris(self):
        body = {
            "results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q5"}, "x": {"value": "y"}}]}
        }
        with mock.patch("urllib.request.urlopen", return_value=response_of(body)) as opened, mock.patch("time.sleep"):
            self.assertEqual(build.sparql("SELECT"), [{"item": "Q5", "x": "y"}])
        request = opened.call_args[0][0]
        self.assertIn("paper-research-eval", request.headers["User-agent"])
        self.assertEqual(request.headers["Accept"], "application/sparql-results+json")
        self.assertTrue(request.full_url.startswith(build.WIKIDATA))

    def test_sparql_retries_a_busy_endpoint_only(self):
        def failure(code):
            return urllib.error.HTTPError("u", code, "busy", {}, None)  # type: ignore[arg-type]

        empty = {"results": {"bindings": []}}
        with mock.patch("time.sleep"):
            with mock.patch("urllib.request.urlopen", side_effect=[failure(502), response_of(empty)]) as opened:
                self.assertEqual(build.sparql("SELECT"), [])
            self.assertEqual(opened.call_count, 2)
            with mock.patch("urllib.request.urlopen", side_effect=[failure(400)]):
                with self.assertRaises(urllib.error.HTTPError):
                    build.sparql("SELECT")
            with mock.patch("urllib.request.urlopen", side_effect=[failure(503)] * build.RETRIES):
                with self.assertRaises(urllib.error.HTTPError):
                    build.sparql("SELECT")

    def test_pwc_records_are_downloaded_once(self):
        folder = Path(tempfile.mkdtemp()) / "cache"

        def download(url, path):
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                json.dump(METHODS, handle)

        with mock.patch("urllib.request.urlretrieve", side_effect=download) as fetched:
            self.assertEqual(len(build.pwc_records("m.json.gz", folder)), 4)
            build.pwc_records("m.json.gz", folder)
        self.assertEqual(fetched.call_count, 1)

    def test_hub_pages_follow_the_next_link(self):
        link = '<https://huggingface.co/api/models?cursor=abc>; rel="next"'
        with mock.patch("urllib.request.urlopen", return_value=response_of([{"id": "a/b"}], link)):
            self.assertEqual(
                build.hub_page(build.HUB), ([{"id": "a/b"}], "https://huggingface.co/api/models?cursor=abc")
            )
        with mock.patch("urllib.request.urlopen", return_value=response_of([{"id": "a/c"}])):
            self.assertEqual(build.hub_page(build.HUB), ([{"id": "a/c"}], None))
        pages = [([{"id": "a/1"}], "next"), ([{"id": "a/2"}], "more")]
        with mock.patch.object(build, "hub_page", side_effect=pages) as fetched:
            self.assertEqual(build.hub_models(2), [{"id": "a/1"}, {"id": "a/2"}])  # stops at the number of pages
        self.assertEqual([call.args[0] for call in fetched.call_args_list], [build.HUB, "next"])
        with mock.patch.object(build, "hub_page", side_effect=[([{"id": "a/1"}], None)]):
            self.assertEqual(build.hub_models(5), [{"id": "a/1"}])  # or when there is no next page

    def test_cached_reads_what_it_wrote_and_calls_the_source_once(self):
        cache = Path(tempfile.mkdtemp()) / "new"
        calls = []

        def produce():
            calls.append(1)
            return [{"a": "é"}]

        self.assertEqual(build.cached(cache, "key", produce), [{"a": "é"}])
        self.assertEqual(build.cached(cache, "key", produce), [{"a": "é"}])
        self.assertEqual(len(calls), 1)
        self.assertEqual(build.cached(cache, "other", lambda: []), [])  # another key, another file
        self.assertEqual(len(list(cache.iterdir())), 2)
        with mock.patch.object(build, "sparql", return_value=[{"x": "1"}]) as asked:
            self.assertEqual(build.rows_of("SELECT 1", cache, build.DBLP), [{"x": "1"}])
            self.assertEqual(build.rows_of("SELECT 1", cache, build.DBLP), [{"x": "1"}])
        asked.assert_called_once_with("SELECT 1", build.DBLP)

    def test_fetch_groups(self):
        def answer(query, endpoint=build.WIKIDATA):
            if "dblp:" not in query:
                self.assertEqual(endpoint, build.WIKIDATA)
                return TOOL_ROWS if "P277" in query else MODEL_ROWS
            self.assertEqual(endpoint, build.DBLP)
            if "VALUES ?item" in query:
                self.assertIn("<https://dblp.org/pid/10/9>", query)
                self.assertNotIn("17/2", query)  # already fetched with its slice
                return OTHER_PEOPLE
            return HOMONYM_ROWS if "?namesake" in query else AUTHOR_ROWS

        with (
            mock.patch.object(build, "sparql", side_effect=answer),
            mock.patch.object(build, "pwc_records", return_value=METHODS),
            mock.patch.object(build, "hub_models", return_value=[{"id": "meta-llama/Llama-2-7b-hf"}]),
        ):
            pools = build.fetch_groups(tempfile.mkdtemp())
        self.assertEqual(sorted(pools), sorted(build.TYPES))
        self.assertIn("dblp:10/9", pools["author"])  # the namesake joins the authors
        self.assertEqual(pools["tool"]["wd:Q1"]["ids"], {"github": "apache/subversion"})
        self.assertEqual(sorted(pools["model"]), ["hf:meta-llama/Llama-2-7b-hf", "wd:Q5"])
        hub = pools["model"]["hf:meta-llama/Llama-2-7b-hf"]
        self.assertEqual((hub["names"], hub["ids"], hub["source"]), (["Llama-2-7b-hf"], {"hf": hub["gold"][3:]}, "hf"))


class Groups(unittest.TestCase):
    def test_an_item_that_is_a_tool_and_a_model_stays_a_model_only(self):
        tools = {"wd:Q1": {"gold": "wd:Q1"}, "wd:Q9": {"gold": "wd:Q9"}}
        models = {"wd:Q9": {"gold": "wd:Q9"}, "hf:a/b": {"gold": "hf:a/b"}}
        self.assertEqual(build.without(tools, models), {"wd:Q1": {"gold": "wd:Q1"}})

    def test_github_and_row_ids(self):
        self.assertEqual(build.github_id("https://github.com/org/repo.git"), "org/repo")
        self.assertEqual(build.github_id("https://www.github.com/org/repo/tree/main"), "org/repo")
        for url in (None, "https://gitlab.com/org/repo", "https://github.com/org"):
            self.assertIsNone(build.github_id(url))
        self.assertEqual(
            build.row_ids({"orcid": "2", "repo": "https://github.com/a/b"}), {"orcid": "2", "github": "a/b"}
        )
        self.assertEqual(build.row_ids({}), {})

    def test_sparql_groups(self):
        groups = build.sparql_groups(AUTHOR_ROWS, "author", "dblp")
        self.assertEqual(groups["dblp:17/1"]["names"], ["Lei Li", "L. Li"])
        self.assertEqual(groups["dblp:17/1"]["ids"], {"orcid": "0000-0001"})
        self.assertEqual(groups["dblp:17/2"]["source"], "dblp")
        self.assertEqual(sorted(build.sparql_groups(TOOL_ROWS, "tool")), ["wd:Q1", "wd:Q2"])

    def test_pwc_groups_keep_real_names_only(self):
        groups = build.pwc_groups(METHODS, "method")
        self.assertEqual(sorted(groups), ["pwc:method/ewc", "pwc:method/net"])
        self.assertEqual(groups["pwc:method/ewc"]["names"], ["EWC", "Elastic Weight Consolidation"])
        self.assertEqual(groups["pwc:method/net"]["names"], ["Elastic Net"])  # the full name is the same name
        self.assertFalse(build.looks_like_a_name({"name": "x" * 41, "num_papers": 9}))
        self.assertFalse(build.looks_like_a_name({"name": "ok", "full_name": "y" * 121, "num_papers": 9}))
        self.assertFalse(build.looks_like_a_name({"name": "ok"}))  # no papers

    def test_add_alias_ignores_a_name_that_differs_only_in_case_or_separators(self):
        entity = group("g", "Bokeh")
        for alias in ["BOKEH", "Bokeh Library", "Bo-keh", "  ", "Bokeh Library"]:
            build.add_alias(entity, alias)
        self.assertEqual(entity["names"], ["Bokeh", "Bokeh Library"])

    def test_shorten(self):
        self.assertEqual(build.shorten("http://www.wikidata.org/entity/Q5"), "Q5")
        self.assertEqual(build.shorten("https://dblp.org/pid/17/10073"), "17/10073")
        self.assertEqual(build.shorten("https://orcid.org/0000-0002-7622-6714"), "0000-0002-7622-6714")
        self.assertEqual(build.shorten("Lei Li"), "Lei Li")


class Audit(unittest.TestCase):
    def pools(self):
        return {
            "tool": {
                "a": group("a", "OpenAI o1", names=["OpenAI o1", "o1-preview", "o1", "Acme"]),
                "b": group("b", "TGIF", source="pwc"),
            },
            "author": {"c": group("c", "P", "author", ["P", "P Q"], "dblp")},
        }

    def test_every_second_name_but_dblp_is_judged(self):
        self.assertEqual(
            build.second_name_pairs(self.pools()),
            [("tool", "OpenAI o1", "o1-preview"), ("tool", "OpenAI o1", "o1"), ("tool", "OpenAI o1", "Acme")],
        )

    def test_similar_names_share_a_word_or_are_close_in_spelling(self):
        for first, second in [
            ("LilyPond", "GNU LilyPond"),  # a shared word
            ("GPT-3", "GPT3"),  # no shared word, but one spelling
            ("Jürgen Schmidhuber", "Jurgen Schmidhuber"),
            ("Zorbit", "Zorbyt"),
        ]:
            self.assertTrue(build.similar_names(first, second), (first, second))
        for first, second in [("Emotional Speech Database", "ESD"), ("Open PC Server Integration", "Opsi")]:
            self.assertFalse(build.similar_names(first, second), (first, second))

    def test_apply_audit_removes_confident_rejections_and_counts_the_unaudited(self):
        def row(first, second, same):
            return {"type": "tool", "first": first, "second": second, "probabilities": {"same_thing": same}}

        pools = self.pools()
        verdicts = {
            ("tool", "OpenAI o1", "o1-preview"): row("OpenAI o1", "o1-preview", 0.05),  # confident: removed
            ("tool", "OpenAI o1", "o1"): row("OpenAI o1", "o1", 0.6),  # unsure: kept, for a person to decide
        }
        report = build.apply_audit(pools, verdicts)
        self.assertEqual(pools["tool"]["a"]["names"], ["OpenAI o1", "o1", "Acme"])  # Acme not judged yet: kept
        self.assertEqual(pools["author"]["c"]["names"], ["P", "P Q"])  # DBLP is not audited
        self.assertEqual(report["wikidata tool"], {"removed": 1, "unaudited": 1, "kept": 2})
        self.assertEqual(report["pwc tool"], {"removed": 0, "unaudited": 0, "kept": 0})
        self.assertEqual(report["dblp author"], {"removed": 0, "unaudited": 0, "kept": 1})

    def test_audit_estimates_without_asking_and_asks_only_when_told_to(self):
        out = Path(tempfile.mkdtemp())
        seen = {"type": "tool", "first": "X", "second": "X Y", "probabilities": {"same_thing": 0.9}, "cost": 0.002}
        (out / "audit.jsonl").write_text(json.dumps(seen) + "\n", encoding="utf-8")
        pools = {"tool": {"b": group("b", "X", source="pwc", names=["X", "X Y", "X Z"])}}
        with (
            mock.patch.object(build.audit_labels, "judge") as judged,
            contextlib.redirect_stdout(io.StringIO()) as shown,
        ):
            report = build.audit(argparse.Namespace(out=str(out), audit=False), pools)
        judged.assert_not_called()
        self.assertIn("1 of 2 second names unjudged, about $0.0020 to ask", shown.getvalue())
        self.assertEqual(report["pwc tool"], {"removed": 0, "unaudited": 1, "kept": 2})
        spent = {"asked": 1, "skipped": 0, "not asked": 0, "input_tokens": 9, "output_tokens": 3, "cost": 0.0004}
        args = argparse.Namespace(out=str(out), audit=True, audit_budget=0.5)
        with (
            mock.patch.object(build.audit_labels, "judge", return_value=spent) as judged,
            mock.patch.object(build.audit_labels, "api_key", return_value="k"),
            contextlib.redirect_stdout(io.StringIO()) as shown,
        ):
            build.audit(args, pools)
            build.audit(args, {"tool": {"c": group("c", "X", source="pwc", names=["X", "X Y"])}})  # nothing to ask
        self.assertEqual(judged.call_count, 1)
        self.assertEqual(judged.call_args[1]["max_cost"], 0.5)
        self.assertIn("asked 1, skipped 0, not asked 0; 9 input and 3 output tokens, $0.0004", shown.getvalue())
        self.assertEqual(build.cost_text(None), "")


class LookAlikes(unittest.TestCase):
    def test_look_alike_keys(self):
        self.assertEqual(build.look_alike_keys(group("a", "Lei Li", "author")), {("person", "li", "l")})
        self.assertEqual(build.look_alike_keys(group("a", "Plato", "author")), set())
        healy = {("person", "healy", "d")}  # a generational suffix is not the surname
        self.assertEqual(build.look_alike_keys(group("a", "Dennis M. Healy Jr.", "author")), healy)
        self.assertEqual(build.look_alike_keys(group("a", "Pedro Silva Filho", "author")), {("person", "silva", "p")})
        self.assertEqual(build.look_alike_keys(group("a", "Healy Jr.", "author")), set())  # only a suffix left
        self.assertEqual(build.surname_words(["a", "b", "jr", "iii"]), ["a", "b"])
        self.assertEqual(build.look_alike_keys(group("a", "???")), set())
        keys = build.look_alike_keys(group("a", "Terminal-Bench 2.0"))
        self.assertEqual(keys, {("word", "terminal"), ("word", "bench"), ("family", "terminal bench")})

    def test_crowded_keys_are_dropped(self):
        pool = {"a": group("a", "Lei Li", "author"), "b": group("b", "Lin Li", "author")}
        self.assertEqual(build.look_alike_index(pool), {("person", "li", "l"): ["a", "b"]})
        with mock.patch.object(build, "CROWDED_KEY", 1):
            self.assertEqual(build.look_alike_index(pool), {})


class Pairs(unittest.TestCase):
    def test_name_pairs(self):
        pool = {
            "a": group("a", "LoRA", names=["Low-Rank Adaptation", "Low Rank Adaptation Method", "LoRA"]),
            "b": group("b", "Bokeh", names=["Bokeh", "Bokeh Library"]),
            "c": group("c", "Flax"),
        }
        found = build.name_pairs(pool, first_choice())
        self.assertEqual(sorted(found), ["dissimilar name", "known alias", "similar name"])
        similar = [(row["existing"]["name"], row["new"]["name"]) for row in found["similar name"]]
        self.assertEqual(similar, [("Low-Rank Adaptation", "Low Rank Adaptation Method"), ("Bokeh", "Bokeh Library")])
        self.assertEqual([row["new"]["name"] for row in found["dissimilar name"]], ["LoRA"])
        alias = found["known alias"][0]
        self.assertEqual(alias["existing"]["aliases"], ["Low Rank Adaptation Method", "LoRA"])
        self.assertEqual((alias["label"], alias["new"]["name"]), ("same", "Low Rank Adaptation Method"))
        self.assertNotIn("aliases", alias["new"])

    def test_look_alikes_differ_in_name_stay_in_one_source_and_are_used_once(self):
        pool = {
            "a": group("a", "Lei Li", "author", source="dblp"),
            "b": group("b", "Lin Li", "author", source="dblp"),
            "c": group("c", "Lei Li", "author", source="dblp"),  # the same name as a: a same-name pair, not this
            "d": group("d", "Lu Li", "author", source="dblp"),
            "e": group("e", "Lars Li", "author", source="orcid"),  # another source: never paired with these
        }
        found = build.look_alike_pairs(pool, first_choice())
        pairs = sorted((row["existing"]["gold"], row["new"]["gold"]) for row in found)
        self.assertEqual(pairs, [("a", "b"), ("c", "d")])
        self.assertEqual({row["label"] for row in found}, {"different"})

    def test_two_records_with_one_id_are_one_thing_and_never_a_look_alike_pair(self):
        pool = {
            "a": group("a", "Cirq", "tool", source="wikidata", ids={"github": "quantumlib/Cirq"}),
            "b": group("b", "Cirq package", "tool", source="wikidata", ids={"github": "quantumlib/cirq"}),
            "c": group("c", "Cirq stack", "tool", source="wikidata", ids={"github": "other/repo"}),
        }
        self.assertTrue(build.shares_id(pool["a"], pool["b"]))  # ids compare without case
        self.assertFalse(build.shares_id(pool["a"], pool["c"]))
        found = build.look_alike_pairs(pool, first_choice())
        self.assertEqual([(row["existing"]["gold"], row["new"]["gold"]) for row in found], [("a", "c")])

    def test_same_name_pairs_come_from_distinct_sources_one_per_name(self):
        pool = {
            "a": group("a", "Jing Chen", "author", source="dblp", ids={"orcid": "1"}),
            "b": group("b", "Jing Chen", "author", source="dblp"),
            "c": group("c", "JING-CHEN", "author", source="dblp"),  # a third Jing Chen: correlated, left out
            "d": group("d", "Amazon Sports", "dataset", source="pwc"),
            "e": group("e", "Amazon Sports", "dataset", source="pwc"),  # Papers with Code: mostly one dataset twice
        }
        found = build.same_name_pairs(pool)
        self.assertEqual([(row["existing"]["gold"], row["new"]["gold"]) for row in found], [("a", "b")])
        self.assertEqual(found[0]["existing"]["ids"], {"orcid": "1"})

    def test_alias_collisions(self):
        pool = {
            "attic": group("attic", "Attic", names=["Attic", "Borg"]),
            "borg": group("borg", "Borg"),
            "borg2": group("borg2", "Borg"),  # another Borg: Attic is used, so it pairs with twin
            "self": group("self", "Storm", names=["Storm", "STORM framework"]),
            "twin": group("twin", "Storm", names=["Storm", "Borg"]),  # holds 'Borg' too
            "pwc": group("pwc", "Borg", source="pwc"),  # Papers with Code: not a distinct source
            "pwc2": group("pwc2", "X", source="pwc", names=["X", "Borg"]),
        }
        found = build.alias_collision_pairs(pool)
        self.assertEqual(
            [(row["existing"]["gold"], row["new"]["gold"]) for row in found], [("attic", "borg"), ("twin", "borg2")]
        )
        self.assertEqual(found[0]["existing"]["aliases"], ["Borg"])
        holders = {"storm": [pool["self"]], "borg": [pool["attic"]]}
        self.assertEqual(build.collision(pool["self"], holders, set()), [])  # its own alias is not a collision
        self.assertEqual(build.collision(pool["borg"], holders, {"borg"}), [])  # an entity used already

    def test_messy_pairs_stop_at_the_limit_and_skip_changes_that_dont_fit(self):
        pool = {f"g{n}": group(f"g{n}", "Efficient Low-Rank Adaptation") for n in range(3)}
        found = build.messy_pairs(pool, random.Random(1), 2)
        self.assertEqual({len(rows) for rows in found.values()}, {2})
        self.assertNotIn("parenthetical", found)  # one name: nothing to put in brackets
        self.assertNotIn("decomposed", found)  # nothing to decompose
        row = found["ligature"][0]
        self.assertEqual(
            (row["kind"], row["messy"], row["new"]["name"]), ("messy", "ligature", "Eﬃcient Low-Rank Adaptation")
        )

    def test_balanced_lets_types_take_turns(self):
        rng = first_choice()
        by_type = {"author": [1, 2, 3, 4], "model": [9]}
        self.assertEqual(sorted(build.balanced(by_type, 3, rng)), [3, 4, 9])  # the model's only pair, then authors
        self.assertEqual(len(build.balanced(by_type, 10, rng)), 5)  # all there are
        self.assertEqual(build.target("similar name", 1.0), 1000)
        self.assertEqual(build.target("messy: dash", 0.5), build.MESSY_PER_KIND)

    def test_choose_fills_every_stratum(self):
        pools = {
            "tool": {
                "a": group("a", "Apache Spark", names=["Apache Spark", "Spark", "PySpark Engine"]),
                "b": group("b", "Apache Beam"),
                "c": group("c", "Borg"),
                "d": group("d", "Attic", names=["Attic", "Borg"]),
                "e": group("e", "Apache Beam"),
            }
        }
        rows = build.choose(pools, random.Random(3), scale=0.05)
        kinds = Counter(row["kind"] for row in rows)
        self.assertEqual(
            set(kinds),
            {"similar name", "dissimilar name", "known alias", "look-alike", "same name", "alias collision", "messy"},
        )


class Splitting(unittest.TestCase):
    def row(self, kind, a, b):
        return {"kind": kind, "type": "tool", "existing": {"gold": a}, "new": {"gold": b}}

    def test_rows_that_share_an_entity_go_to_one_split(self):
        rows = [self.row("look-alike", "a", "b"), self.row("look-alike", "c", "b"), self.row("similar name", "c", "c")]
        rows.append(self.row("same name", "x", "y"))
        self.assertEqual(sorted(len(group) for group in build.components(rows)), [1, 3])
        build.assign_splits(rows, random.Random(0))
        self.assertEqual(len({row["split"] for row in rows[:3]}), 1)

    def test_every_stratum_is_shared_about_evenly(self):
        rows = [self.row("alias collision", f"a{n}", f"b{n}") for n in range(4)]
        rows += [{**self.row("messy", f"m{n}", f"m{n}"), "messy": "dash"} for n in range(6)]
        build.assign_splits(rows, random.Random(0))
        found = Counter((build.stratum_of(row), row["split"]) for row in rows)
        self.assertEqual(found, Counter({("alias collision", "dev"): 2, ("alias collision", "test"): 2,
                                         ("messy: dash", "dev"): 3, ("messy: dash", "test"): 3}))  # fmt: skip


class Messes(unittest.TestCase):
    def test_messes(self):
        rng, none = random.Random(4), ()
        self.assertEqual(build.mess_case("Ab c", rng, none), "aB  C")
        self.assertIsNone(build.mess_case("  ", rng, none))
        self.assertEqual(build.mess_dash("Low-Rank", rng, none), "Low–Rank")
        self.assertIsNone(build.mess_dash("LoRA", rng, none))
        self.assertEqual(build.mess_decomposed("Jürgen", rng, none), "Jürgen")
        self.assertIsNone(build.mess_decomposed("Jurgen", rng, none))
        self.assertRegex(build.mess_citation("GPT-4", rng, none), r"^GPT-4 \[\d+\]$")
        self.assertEqual(build.mess_line_break("Low Adaptation", rng, none), "Low Adapt- ation")
        self.assertIsNone(build.line_break("LoRA v2"))
        self.assertEqual(build.mess_punctuation("LoRA", rng, none), "LoRA.")

    def test_more_messes(self):
        rng, none = random.Random(4), ()
        self.assertEqual(build.mess_ligature("Efficient fine-tuning", rng, none), "Eﬃcient fine-tuning")
        self.assertEqual(build.mess_ligature("Reflexion", rng, none), "Reﬂexion")
        self.assertIsNone(build.mess_ligature("LoRA", rng, none))
        self.assertIn(build.mess_footnote("GPT-4", rng, none)[5:], "*†‡¹²³")
        self.assertIn(build.mess_possessive("BERT", rng, none), ("BERT's", "BERT’s"))
        self.assertRegex(build.mess_quotes("LoRA", rng, none), r"^[“‘\"]LoRA[”’\"]$")
        invisible = build.mess_invisible("Low Adaptation", rng, none)
        self.assertIn(invisible, ("Low Adapt­ation", "Low Adapt​ation"))
        self.assertIsNone(build.mess_invisible("RAG", rng, none))
        self.assertEqual(build.mess_parenthetical("Deep Graph Infomax", rng, ["DGI"]), "Deep Graph Infomax (DGI)")
        self.assertEqual(build.mess_parenthetical("DGI", rng, ["Deep Graph Infomax"]), "DGI (Deep Graph Infomax)")
        self.assertIsNone(build.mess_parenthetical("Andrew Livingstone", rng, ["Andy Livingstone"]))  # people: no
        self.assertIsNone(build.mess_parenthetical("LoRA", rng, []))


class Writing(unittest.TestCase):
    def pools(self):
        names = ("Apache Spark", "Apache Beam", "Borg", "Low-Rank Adaptation", "Efficient Net", "Jürgen Schmidhuber")
        pool = {f"g{n}": group(f"g{n}", name, names=[name, f"{name} toolkit"]) for n, name in enumerate(names)}
        pool["dup"] = group("dup", "Borg")
        return {"tool": pool, "model": {}}

    def test_build_writes_the_files(self):
        out = Path(tempfile.mkdtemp())
        cache = Path(tempfile.mkdtemp())
        (cache / "source.json").write_text("[1]", encoding="utf-8")
        (cache / "folder").mkdir()  # only files are part of the snapshot
        args = argparse.Namespace(seed=1, scale=0.01, out=str(out), cache=str(cache))
        with contextlib.redirect_stdout(io.StringIO()):
            summary = build.build(args, self.pools(), {"wikidata tool": {"kept": 6}})
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["manifest.json", "pairs.jsonl"])
        self.assertEqual(list(summary["sources snapshot"]), ["source.json"])
        digest = hashlib.sha256((out / "pairs.jsonl").read_bytes()).hexdigest()
        self.assertEqual(summary["pairs file sha256"], digest)
        self.assertEqual(build.snapshot(out / "none"), {})  # no cache, no snapshot
        rows = [json.loads(line) for line in (out / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(summary["pairs"].values()), len(rows))
        self.assertEqual({row["split"] for row in rows}, {"dev", "test"})
        self.assertEqual(summary["pool"]["tool"], {"wikidata": 7, "several names": 0.857})
        self.assertEqual(summary["pool"]["model"], {"several names": 0.0})
        self.assertEqual(summary["second names by the audit"]["by source and type"], {"wikidata tool": {"kept": 6}})
        by_stratum = summary["pairs by stratum and type"]
        self.assertEqual(
            sum(n for split in by_stratum.values() for types in split.values() for n in types.values()), len(rows)
        )

    def test_main_and_script(self):
        out = Path(tempfile.mkdtemp())
        with (
            mock.patch.object(build, "fetch_groups", return_value=Writing.pools(self)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(build.main(["--scale", "0.01", "--out", str(out)]), 0)
        self.assertTrue((out / "manifest.json").exists())
        with mock.patch.object(sys, "argv", ["build_dataset.py", "--help"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(build.HERE / "build_dataset.py"), run_name="__main__")
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
