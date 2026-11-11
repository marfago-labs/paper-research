"""Steps for the knowledge graph features. The graph is changed only through its CLI."""

import json
import shlex
import subprocess
import sys

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


@given('the graph holds a {kind} "{name}" with id "{ident}"')
def graph_has_with_id(context, kind, name, ident):
    entities, relations = read_all(context)
    entities[ident] = entity(kind, name, ident)
    write_all(context, list(entities.values()), relations)


@given('the {kind} "{name}" also goes by "{alias}"')
def graph_alias(context, kind, name, alias):
    entities, relations = read_all(context)
    entities[f"{kind}:{graph.slugify(name)}"]["aliases"].append(alias)
    write_all(context, list(entities.values()), relations)


@given('"{first}" is marked as distinct from "{second}"')
def graph_distinct(context, first, second):
    entities, relations = read_all(context)
    entities[first]["distinct_from"] = [second]
    write_all(context, list(entities.values()), relations)


@given('"{start}" {rel} "{end}" is recorded as {status}')
def graph_relation(context, start, rel, end, status):
    entities, relations = read_all(context)
    relations.append({"from": start, "rel": rel, "to": end, "source": "test", "status": status})
    write_all(context, list(entities.values()), relations)


@given("the graph files contain an invalid entity")
def graph_invalid(context):
    write_all(context, [{"id": "tool:x", "type": "tool", "name": "X", "url": 5}], [])


@when("I run graph {command}")
def run_graph(context, command):
    context.entities_before = len(read_all(context)[0]) if (graph_dir(context) / "entities.jsonl").exists() else 0
    context.run_script("graph", shlex.split(command))


@when("{count:d} processes each add a different method at the same moment")
def concurrent_adds(context, count):
    context.entities_before = len(read_all(context)[0])
    script = str(context.repo / "skills" / "graph" / "scripts" / "graph.py")
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet"][:count]
    processes = [
        subprocess.Popen(
            [sys.executable, script, "add", "--type", "method", "--name", f"Zq{name}", "--slug", name.lower()],
            cwd=context.workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for name in names
    ]
    context.exit_codes = [p.wait(timeout=120) for p in processes]
    for process in processes:
        process.stdout.close()
        process.stderr.close()


@then("every process succeeds")
def every_process_succeeds(context):
    assert context.exit_codes == [0] * len(context.exit_codes), context.exit_codes


@then("the graph has {count:d} entit{plural}")
def graph_count(context, count, plural):
    assert len(read_all(context)[0]) == count, list(read_all(context)[0])


@then("the graph has {count:d} more entities than before")
def graph_grew(context, count):
    assert len(read_all(context)[0]) == context.entities_before + count


@then('the graph has an entity "{ident}"')
def graph_has_entity(context, ident):
    assert ident in read_all(context)[0], list(read_all(context)[0])


@then('the graph has no entity "{ident}"')
def graph_lacks_entity(context, ident):
    assert ident not in read_all(context)[0]


@then('the entity "{ident}" is named "{name}"')
def entity_named(context, ident, name):
    assert read_all(context)[0][ident]["name"] == name


@then('the entity "{ident}" has alias "{alias}"')
def entity_has_alias(context, ident, alias):
    assert alias in read_all(context)[0][ident]["aliases"], read_all(context)[0][ident]


@then('the entity "{ident}" is marked distinct from "{other}"')
def entity_distinct(context, ident, other):
    assert other in read_all(context)[0][ident].get("distinct_from", [])


@then('the graph has the relation "{start}" {rel} "{end}"')
def graph_has_relation(context, start, rel, end):
    found = [r for r in read_all(context)[1] if (r["from"], r["rel"], r["to"]) == (start, rel, end)]
    assert len(found) == 1, read_all(context)[1]


@then("the graph has {count:d} relations")
def graph_relation_count(context, count):
    assert len(read_all(context)[1]) == count, read_all(context)[1]


@then('the relation "{start}" {rel} "{end}" is {status}')
def relation_status(context, start, rel, end, status):
    found = [r for r in read_all(context)[1] if (r["from"], r["rel"], r["to"]) == (start, rel, end)]
    assert found and found[0]["status"] == status, found


@then("no temporary files are left behind")
def no_leftovers(context):
    left = sorted(p.name for p in graph_dir(context).iterdir() if p.name != ".lock")
    assert left == ["entities.jsonl", "relations.jsonl"], left
