"""Steps for the knowledge graph features. The graph is changed only through its CLI."""

import datetime
import json
import shlex

from behave import given, then, when

import graph


def graph_dir(context):
    return context.workspace / "research" / "graph"


def read_all(context):
    entities = graph.read_jsonl(graph_dir(context) / "entities.jsonl")
    relations = graph.read_jsonl(graph_dir(context) / "relations.jsonl")
    return {e["id"]: e for e in entities}, relations


def write_all(context, entities, relations):
    folder = graph_dir(context)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "entities.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entities), encoding="utf-8")
    (folder / "relations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in relations), encoding="utf-8")


def entity(kind, name, ident=None, **extra):
    return {"id": ident or f"{kind}:{graph.slugify(name)}", "type": kind, "name": name, "aliases": [], **extra}


@given("an empty graph")
def empty_graph(context):
    write_all(context, [], [])


@given('the graph has a {kind} "{name}"')
def graph_has(context, kind, name):
    entities, relations = read_all(context)
    entities[f"{kind}:{graph.slugify(name)}"] = entity(kind, name)
    write_all(context, list(entities.values()), relations)


@given('every paper in the graph has the author "{name}"')
def graph_papers_authored(context, name):
    entities, relations = read_all(context)
    author = entity("author", name)
    entities[author["id"]] = author
    papers = [ident for ident, found in entities.items() if found["type"] == "paper"]
    link = {"rel": "authored-by", "to": author["id"], "source": "Semantic Scholar", "status": "verified"}
    relations.extend({"from": paper, **link} for paper in papers)
    write_all(context, list(entities.values()), relations)


@given('the graph holds a {kind} "{name}" with id "{ident}"')
def graph_has_with_id(context, kind, name, ident):
    entities, relations = read_all(context)
    entities[ident] = entity(kind, name, ident)
    write_all(context, list(entities.values()), relations)


@given('a verified link "{start}" {rel} "{end}" has the source "{source}"')
def graph_verified_relation(context, start, rel, end, source):
    # Written straight to the files, as an older graph might hold it: link itself refuses such a source.
    entities, relations = read_all(context)
    relations.append({"from": start, "rel": rel, "to": end, "source": source, "status": "verified"})
    write_all(context, list(entities.values()), relations)


@given('Semantic Scholar\'s batch output in "{name}" gives ARXIV:{number} {count:d} citations')
def batch_output(context, name, number, count):
    record = {"requestedId": f"ARXIV:{number}", "paperId": "S2", "externalIds": {"ArXiv": number}}
    (context.workspace / name).write_text(json.dumps([{**record, "citationCount": count}]), encoding="utf-8")


@then('the paper "{ident}" has {count:d} citations checked today')
def has_standing(context, ident, count):
    standing = read_all(context)[0][ident]["standing"]
    assert standing == {"citations": count, "checked": datetime.date.today().isoformat()}, standing


@when("I run graph {command}")
def run_graph(context, command):
    context.entities_before = len(read_all(context)[0]) if (graph_dir(context) / "entities.jsonl").exists() else 0
    context.run_script("graph", shlex.split(command))


@then('the graph has the relation "{start}" {rel} "{end}"')
def graph_has_relation(context, start, rel, end):
    found = [r for r in read_all(context)[1] if (r["from"], r["rel"], r["to"]) == (start, rel, end)]
    assert len(found) == 1, read_all(context)[1]


@then("the graph has {count:d} relations")
def graph_relation_count(context, count):
    assert len(read_all(context)[1]) == count, read_all(context)[1]
