#!/usr/bin/env python3
"""Query and change the workspace knowledge graph. Standard library only.

Read: validate, stats, search, neighbours, path, dupes, islands.
standing-due writes the ids of the papers whose citation counts need checking again to a file.
Write: add, update, link, unlink, merge, remove, cites, standing. Every write checks for duplicates and
validates the whole graph before saving, so never edit the JSONL files by hand.
Run from the workspace root. The graph is drawn by the recap skill's page.
Exit codes: 0 success, 1 error or nothing found, 2 usage error,
3 possible duplicates found (add refused until you decide).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import itertools
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict, deque
from pathlib import Path

DEFAULT_DATA_DIR = Path("research") / "graph"

ENTITY_TYPES = {
    "paper",
    "author",
    "concept",
    "method",
    "model",
    "dataset",
    "tool",
    "organisation",
    "insight",
}
RELATION_TYPES = {
    "uses",
    "evaluates-on",
    "builds-on",
    "proposes",
    "cites",
    "authored-by",
    "contradicts",
    "related-to",
    "derived-from",
}
STATUSES = {"verified", "inferred"}
STRENGTH = ["inferred", "verified"]  # weakest first: when two links merge into one, the stronger stays
VERIFIED = {"verified"}
EXTERNAL_ID_KINDS = {"s2", "arxiv", "doi", "hf", "github", "orcid"}
# Relations that come from reading a paper, as opposed to authors, citations, or insights.
EXTRACTED_RELATIONS = {"uses", "evaluates-on", "builds-on", "proposes", "related-to", "contradicts"}
# The source recorded on cites relations, by the list of the Semantic Scholar record they come from.
CITATION_SOURCES = {"references": "Semantic Scholar references", "citations": "Semantic Scholar citations"}
OUTGOING = {"references"}  # a paper cites its references; its citations cite it
FILES = ("entities.jsonl", "relations.jsonl")
LOCK_FILE, COMMIT_FILE = ".lock", ".commit"
LOCK_WAIT = 15  # seconds; pragma: no mutate (a tuning value: tests use the name)
FIELD_TYPES = {
    "id": str,
    "type": str,
    "name": str,
    "aliases": list,
    "url": str,
    "note": str,
    "ids": dict,
    "distinct_from": list,
    "standing": dict,
}
# A paper's standing in the research community, copied from Semantic Scholar with the date it was checked,
# because citation counts change. Only checked is required: a record may lack the venue or year.
STANDING_FIELDS = {"citations": int, "influential": int, "venue": str, "year": int, "checked": str}
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_FIELDS = {"checked"}  # standing fields that hold a date
RELATION_FIELDS = ("from", "rel", "to", "source", "status")
TYPE_NAMES = {str: "text", list: "a list of text", dict: "an object"}
# dupes compares only entities that share a key. A character trigram shared by more than this many entities of
# one type is too common to say anything, so it is skipped. Names and external ids are always compared.
BLOCK_CAP = 50  # pragma: no mutate (a tuning value: tests use the name)
UNCAPPED_KEYS = {"ext", "name"}  # block key kinds always compared, however many share them
# How much of the shorter name's character trigrams the other name must share to be a possible duplicate. This is
# the one setting of the detector: raise it if add holds too often, lower it if duplicates get through. It can't
# remove holds where one name contains the other ('MoE' and 'MoE-LLaVA'), which always score 1.0. If those become
# a problem, weight each trigram by how rare it is in the graph (IDF) rather than adding rules: still one score.
SIMILARITY = 0.5
ID_ALIAS = re.compile(r"(ARXIV|DOI):(.+)", re.I)
# Verified means checked against a source, so the source must start with a document someone can look up: an arXiv or
# DOI id, a link, a place in a paper of the graph (paper:<id>, <section>), or Semantic Scholar's data. Only the start
# counts, because a reason that merely mentions an id ("same group as paper:x") is an inference, not a source.
DOCUMENT = re.compile(r"^\s*(?:(?:ARXIV|DOI):\S|paper:[^\s,]+,\s*\S|https?://\S|Semantic Scholar\b)", re.I)
SOURCE_FIX = (
    "mark it --status inferred, or give a source that names the document, such as 'ARXIV:2401.00001, §3.2',"
    " a DOI, a link, or 'Semantic Scholar'"
)


class GraphError(Exception):
    pass


def read_jsonl(path):
    records = []
    if not path.exists():
        raise GraphError(f"missing file: {path}")
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as err:
            raise GraphError(f"{path.name}:{number}: invalid JSON: {err}") from None
        if not isinstance(record, dict):
            raise GraphError(f"{path.name}:{number}: expected a JSON object")
        records.append(record)
    return records


def load(directory):
    return read_jsonl(directory / "entities.jsonl"), read_jsonl(directory / "relations.jsonl")


def is_paper(entity):
    return entity.get("type") == "paper"


def is_separator(char):
    """Whitespace, which takes in all of Unicode category Z, dashes (Pd), and connectors such as '_' (Pc)."""
    return char.isspace() or unicodedata.category(char) in ("Pd", "Pc")


def name_key(text):
    """The key that must be unique within a type, and the only match on name strong enough to refuse.

    Canonically composed (NFC), so a decomposed 'Jürgen' copied from a PDF is the same name; case folded; without
    separators. Nothing else is removed, so 'GPT-4' is 'gpt 4', but 'C++' is not 'C' and 'Jürgen' is not 'Jurgen':
    those are left to the similarity score, which only ever holds for a decision.
    """
    text = unicodedata.normalize("NFC", str(text)).casefold()
    return "".join(char for char in text if not is_separator(char))


def ascii_spelling(char):
    """ASCII as itself, other letters from their Unicode name without its marks ('đ', D WITH STROKE, as 'd'; 'μ'
    as 'mu'), and any other letter or digit by its code point ('张' as 'u5f20')."""
    if char.isascii():
        return char
    words = unicodedata.name(char, "").split(" WITH ")[0].split()
    if char.isalpha() and words and words[-1].isalpha():  # character names are always ASCII
        return words[-1].lower()
    return f" u{ord(char):x} "


def loose(text):
    """The form names are compared in for similarity, and ids are made from: case folded, decomposed, without
    marks, letters and digits only and spelled in ASCII, with words separated by single spaces. It is generous on
    purpose, since a similar name is only ever held for a decision."""
    chars = (
        ascii_spelling(char) if unicodedata.category(char)[0] in "LN" else " "
        for char in unicodedata.normalize("NFKD", str(text).casefold())
        if not unicodedata.category(char).startswith("M")
    )
    return " ".join("".join(chars).split())


def trigrams(text):
    padded = f" {loose(text)} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def similarity(x, y):
    """The share of the shorter name's character trigrams that the other name has too, from 0 to 1."""
    grams_x, grams_y = trigrams(x), trigrams(y)
    return len(grams_x & grams_y) / min(len(grams_x), len(grams_y)) if grams_x and grams_y else 0.0


def slugify(text):
    """A readable id from a name. An id only has to be unique, and add finds a free one, so it decides nothing.
    A name with no letters or digits, such as '+', gets the code points of its characters: 'u2b'."""
    slug = re.sub(r"[^a-z0-9]+", "-", loose(text)).strip("-")
    slug = slug or "-".join(f"u{ord(char):x}" for char in str(text) if not char.isspace())
    if not slug:
        raise GraphError(f"can't make an id from {text!r}; give one with --slug")
    return slug


def free_id(entities, entity_id):
    """entity_id, or entity_id-2, -3, and so on, whichever no entity has yet."""
    taken = {entity["id"] for entity in entities}
    candidate, number = entity_id, 2
    while candidate in taken:
        candidate, number = f"{entity_id}-{number}", number + 1
    return candidate


def labels(entity):
    """The entity's name and aliases, leaving out aliases that are identifiers."""
    return [entity["name"], *(a for a in entity.get("aliases", []) if not ID_ALIAS.fullmatch(a.strip()))]


def id_key(value):
    """How external id values compare: without surrounding spaces or case. Every comparison of ids uses it."""
    return str(value).strip().casefold()


def external_keys(entity):
    """Stable identifiers as (kind, value) pairs, from ids, ID aliases, and arXiv paper ids."""
    keys: set[tuple[str, ...]] = set()
    ids = entity.get("ids")
    if isinstance(ids, dict):
        keys.update((kind, id_key(value)) for kind, value in ids.items())
    for alias in entity.get("aliases", []):
        match = ID_ALIAS.fullmatch(alias.strip())
        if match:
            keys.add((match.group(1).lower(), id_key(match.group(2))))
    slug = str(entity.get("id", "")).partition(":")[2]
    if is_paper(entity) and re.fullmatch(r"\d{4}\.\d{4,5}", slug):
        keys.add(("arxiv", slug))
    return keys


def match_reasons(a, b):
    """Why two entities of the same type might be the same thing. Empty if no reason.

    A shared external id or the same name is strong. A name equal to the other's alias, or a similar name, is weak:
    an alias such as an acronym can stand for more than one thing. Similarity compares the two names only, not
    aliases: a short alias such as 'RAG' would score high against any name that starts the same way ('RAGAS').
    """
    reasons = [f"same id ({kind})" for kind, _ in sorted(external_keys(a) & external_keys(b))]
    if name_key(a["name"]) and name_key(a["name"]) == name_key(b["name"]):
        return reasons + ["same name"]
    if {name_key(x) for x in labels(a)} & {name_key(y) for y in labels(b)} - {""}:
        return reasons + ["same name as an alias"]
    score = similarity(a["name"], b["name"])
    return reasons + [f"similar name ({score:.2f})"] if score >= SIMILARITY else reasons


def marked_distinct(a, b):
    return b["id"] in a.get("distinct_from", []) or a["id"] in b.get("distinct_from", [])


def conflicting_ids(a, b):
    """Kinds of external id that both entities have, with different values: evidence they are different things."""
    ids_a, ids_b = a.get("ids"), b.get("ids")
    if not (isinstance(ids_a, dict) and isinstance(ids_b, dict)):
        return []
    return sorted(kind for kind in ids_a.keys() & ids_b.keys() if id_key(ids_a[kind]) != id_key(ids_b[kind]))


def judged(entity, new):
    """(reasons, strong) for a possible duplicate.

    A shared external id is the strongest evidence there is, so it is always strong. A conflicting id only weakens
    a match on the name, so two people named 'Wei Zhang' with different Semantic Scholar ids are held for a
    decision, not refused.
    """
    reasons = match_reasons(new, entity)
    conflicts = conflicting_ids(entity, new)
    strong = any(r.startswith("same id") for r in reasons) or ("same name" in reasons and not conflicts)
    if reasons and conflicts:
        reasons = reasons + [f"but a different {kind} id" for kind in conflicts]
    return reasons, strong


def candidates(entities, new):
    """Existing entities that might be the same as new: (entity, reasons, strong)."""
    found = []
    for entity in entities:
        if entity["type"] != new["type"] or marked_distinct(entity, new):
            continue
        reasons, strong = judged(entity, new)
        if reasons:
            found.append((entity, reasons, strong))
    return found


def block_keys(entity):
    """Cheap keys that likely duplicates share, so dupes doesn't compare every pair."""
    keys = {("ext",) + key for key in external_keys(entity)}
    keys.update(("name", name_key(label)) for label in labels(entity))
    keys.update(("gram", gram) for gram in trigrams(entity["name"]))  # similarity compares names, not aliases
    return keys


def block_index(entities):
    """Positions of the entities that share each (type, block key)."""
    index = defaultdict(list)
    for position, entity in enumerate(entities):
        for key in block_keys(entity):
            index[(entity["type"], key)].append(position)
    return index


def candidate_pairs(entities):
    """Pairs of positions worth comparing: those sharing a name, an id, or a trigram that few entities share."""
    pairs: set[tuple[int, int]] = set()
    for (_, key), positions in block_index(entities).items():
        if len(positions) <= BLOCK_CAP or key[0] in UNCAPPED_KEYS:
            pairs.update(itertools.combinations(positions, 2))  # positions ascend, so i < j
    return pairs


def dupes(entities):
    """Pairs of entities that might be duplicates: (a, b, reasons)."""
    found = []
    for i, j in sorted(candidate_pairs(entities)):
        a, b = entities[i], entities[j]
        reasons = [] if marked_distinct(a, b) else judged(a, b)[0]
        if reasons:
            found.append((a, b, reasons))
    return found


def islands(entities, relations):
    """Papers with nothing extracted from them yet: only author, citation, or insight links."""
    extracted: set[str] = set()
    for relation in relations:
        if relation["rel"] in EXTRACTED_RELATIONS:
            extracted.update((relation["from"], relation["to"]))
    return [entity for entity in entities if is_paper(entity) and entity["id"] not in extracted]


def type_errors(entity):
    """Problems with the types of an entity's fields, checked before anything else uses them."""
    errors = []
    for field, kind in FIELD_TYPES.items():
        value = entity.get(field)
        if field in entity and (
            # pragma: no mutate below: types are unique objects, so `==` agrees with `is`.
            not isinstance(value, kind)
            or (kind is list and not all(isinstance(item, str) for item in value))  # pragma: no mutate
        ):
            errors.append(f"{entity['id']}: {field} must be {TYPE_NAMES[kind]}")
    return errors


def shape_errors(entity):
    """Problems that stop an entity from being checked further: no id or name, or fields of the wrong type."""
    entity_id, name = entity.get("id"), entity.get("name")
    if not (isinstance(entity_id, str) and entity_id and isinstance(name, str) and name):
        return [f"entity needs an id and a name: {entity}"]
    return type_errors(entity)


def field_errors(entity):
    """Problems with an entity's type, id prefix, and url."""
    entity_id, entity_type, url = entity["id"], entity.get("type"), entity.get("url")
    errors = []
    if entity_type not in ENTITY_TYPES:
        errors.append(f"{entity_id}: unknown type {entity_type!r}")
    if not entity_id.startswith(f"{entity_type}:"):
        errors.append(f"{entity_id}: id must start with '{entity_type}:'")
    if url and not re.match(r"https?://", url):
        errors.append(f"{entity_id}: url must start with http:// or https://")
    return errors + standing_errors(entity)


def valid_standing_field(field, value):
    """Whether one field of a standing is known and of the right type: a count is a whole number, not negative,
    and checked is a date."""
    kind = STANDING_FIELDS.get(field)
    # pragma: no mutate on this line and the `is int` below: types and None are unique objects, so `==` agrees.
    right_type = kind is not None and type(value) is kind  # pragma: no mutate
    if not right_type:
        return False
    if kind is int:  # pragma: no mutate
        return value >= 0
    return field not in DATE_FIELDS or bool(DATE.fullmatch(value))


def standing_errors(entity):
    """Problems with a paper's standing: only papers have one, and it names the fields that are wrong."""
    if "standing" not in entity:
        return []
    standing, entity_id = entity["standing"], entity["id"]
    if not is_paper(entity):
        return [f"{entity_id}: only papers have a standing"]
    bad = [field for field, value in standing.items() if not valid_standing_field(field, value)]
    if "checked" not in standing:
        bad.append("checked")
    if not bad:
        return []
    return [
        f"{entity_id}: standing has bad or missing {', '.join(sorted(bad))}"
        " (counts are whole numbers, venue is text, checked is a date like 2026-01-31)"
    ]


def name_errors(entity, names):
    """Names and aliases already used by another entity of the same type. Records this entity's names."""
    errors = []
    for label in [entity["name"], *entity.get("aliases", [])]:
        other = names.setdefault((entity.get("type"), name_key(label)), entity)
        if other["id"] != entity["id"] and not marked_distinct(entity, other):
            errors.append(f"{entity['id']}: {label!r} is already used by {other['id']}")
    return errors


def valid_ids(ids):
    return isinstance(ids, dict) and all(
        kind in EXTERNAL_ID_KINDS and isinstance(value, str) and value.strip() for kind, value in ids.items()
    )


def external_errors(entity, external):
    """Bad external ids, or ones already used by another entity of the same type. Records this entity's ids."""
    if not valid_ids(entity.get("ids", {})):
        return [f"{entity['id']}: ids must map {sorted(EXTERNAL_ID_KINDS)} to non-empty text"]
    errors = []
    for kind, value in external_keys(entity):
        key = (entity.get("type"), kind, value)
        if external.setdefault(key, entity["id"]) != entity["id"]:
            errors.append(f"{entity['id']}: {kind} id {value!r} is already used by {external[key]}")
    return errors


def distinct_errors(entities, ids):
    return [
        f"{entity['id']}: distinct_from has an unknown entity {other!r}"
        for entity in entities
        for other in entity.get("distinct_from", [])
        if other not in ids or other == entity["id"]
    ]


def entity_errors(entities):
    """Every problem with the entities, and the set of their ids."""
    errors, ids, checked = [], set(), []
    names: dict[tuple[str, str], dict] = {}  # names are unique within a type, not across types
    external: dict[tuple[str, ...], str] = {}  # like names, external ids are unique within a type
    for entity in entities:
        problems = shape_errors(entity)
        if problems:
            errors.extend(problems)
            continue
        checked.append(entity)
        if entity["id"] in ids:
            errors.append(f"duplicate entity id: {entity['id']}")
        ids.add(entity["id"])
        errors += field_errors(entity) + name_errors(entity, names) + external_errors(entity, external)
    return errors + distinct_errors(checked, ids), ids


def relation_problems(relation, ids, seen):
    """Every problem with one relation. Records it in seen, to catch the same relation twice."""
    bad = [field for field in RELATION_FIELDS if not isinstance(relation.get(field, ""), str)]
    if bad:
        return [f"relation fields must be text: {', '.join(bad)} in {relation}"]
    start, rel, end = relation.get("from"), relation.get("rel"), relation.get("to")
    label = f"{start} {rel} {end}"
    checks = [
        (start not in ids, f"{label}: unknown entity {start!r}"),
        (end not in ids, f"{label}: unknown entity {end!r}"),
        (start == end, f"{label}: an entity can't connect to itself"),
        (rel not in RELATION_TYPES, f"{label}: unknown relation {rel!r}"),
        (not relation.get("source"), f"{label}: needs a source"),
        (relation.get("status") not in STATUSES, f"{label}: status must be verified or inferred"),
        ((start, rel, end) in seen, f"{label}: duplicate relation"),
    ]
    seen.add((start, rel, end))
    return [message for failed, message in checks if failed]


def validate(entities, relations):
    errors, ids = entity_errors(entities)
    seen: set[tuple] = set()
    for relation in relations:
        errors += relation_problems(relation, ids, seen)
    return errors


def search(entities, text):
    """Entities whose id, name, note, or alias contains text, compared loosely."""
    key = loose(text)

    def texts(entity):
        return [entity["id"], entity["name"], entity.get("note", ""), *entity.get("aliases", [])]

    return [entity for entity in entities if key and any(key in loose(value) for value in texts(entity))]


def named(entities, text, key):
    """Entities with a name or alias equal to text under key."""
    wanted = key(text)
    return [e for e in entities if wanted and wanted in {key(value) for value in [e["name"], *e.get("aliases", [])]}]


def resolve(entities, text):
    """Find one entity by exact id, or by name or alias under name_key.

    Commands that act, such as remove or link, must never guess: the loose form would turn 'C++' into 'C'. A loose
    match is only offered as a suggestion, for the caller to confirm with an id.
    """
    for entity in entities:
        if entity["id"] == text:
            return entity
    found = named(entities, text, name_key)
    if len(found) > 1:
        raise GraphError(f"{text!r} matches more than one entity, so use an id: {', '.join(e['id'] for e in found)}")
    if found:
        return found[0]  # pragma: no mutate (one entity is left after the check above, so any index agrees)
    near = named(entities, text, loose)
    if near:
        raise GraphError(f"no entity is named {text!r}; did you mean {', '.join(e['id'] for e in near)}? Use its id")
    raise GraphError(f"no entity matches {text!r}; try the search command")


def adjacency(relations):
    links: dict[str, list] = {}
    for relation in relations:
        links.setdefault(relation["from"], []).append(("out", relation, relation["to"]))
        links.setdefault(relation["to"], []).append(("in", relation, relation["from"]))
    return links


def neighbours(relations, start, depth=1):
    """Return (distance, direction, relation, other id) for connections within depth."""
    links = adjacency(relations)
    reached = {start}
    level = [start]
    found = []
    for distance in range(1, depth + 1):
        following = []
        for current in level:
            for direction, relation, other in links.get(current, []):
                found.append((distance, direction, relation, other))
                if other not in reached:
                    reached.add(other)
                    following.append(other)
        level = following
    return first_per_relation(found)


def first_per_relation(found):
    """Keep the first, and so nearest, of each relation, which a search reaches from both ends."""
    seen = set()
    kept = []
    for item in found:
        relation = item[2]
        key = (relation["from"], relation["rel"], relation["to"])
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return kept


def search_tree(links, start, end):
    """Breadth-first search from start until end is reached: each node's (parent, direction, relation)."""
    previous: dict = {start: None}  # each node's (parent, direction, relation); None for start
    queue = deque([start])
    while queue and end not in previous:
        current = queue.popleft()
        for direction, relation, other in links.get(current, []):
            if other not in previous:
                previous[other] = (current, direction, relation)
                queue.append(other)
    return previous


def shortest_path(relations, start, end):
    """Return the shortest list of (direction, relation, other id), ignoring direction."""
    previous = search_tree(adjacency(relations), start, end)
    if end not in previous:
        return None
    steps: list[tuple] = []
    node = end
    while (step := previous[node]) is not None:
        parent, direction, relation = step
        steps.append((direction, relation, node))
        node = parent
    return steps[::-1]


ARROWS = {"out": "->", "in": "<-"}


def describe(relation, direction, other_name):
    arrow = ARROWS[direction]
    return f"{arrow} {relation['rel']} {arrow} {other_name}  [{relation['source']}; {relation['status']}]"


def names_document(source):
    return bool(DOCUMENT.search(source))


def unsourced(relation):
    """A relation marked verified whose source names no document it could have been checked against."""
    return relation["status"] in VERIFIED and not names_document(relation["source"])


def checked_load(directory):
    entities, relations = load(directory)
    errors = validate(entities, relations)
    if errors:
        raise GraphError("invalid graph:\n" + "\n".join(f"  {error}" for error in errors))
    return entities, relations


def cmd_validate(args):
    entities, relations = checked_load(args.data)
    # Not a load error: an old link must not lock the user out of the graph, so it is listed here to be fixed.
    found = [relation for relation in relations if unsourced(relation)]
    if not found:
        print(f"OK: {len(entities)} entities, {len(relations)} relations")
        return 0
    print(f"checked: {len(entities)} entities, {len(relations)} relations")
    print(f"found {count(len(found), 'verified link')} with no document it was checked against:")
    for relation in found:
        print(f"  {relation['from']} {relation['rel']} {relation['to']}  [{relation['source']}]")
    print(f"For each, unlink it and link it again: {SOURCE_FIX}.")
    return 1


def cmd_stats(args):
    entities, relations = checked_load(args.data)
    print(f"{len(entities)} entities, {len(relations)} relations")
    for name, count in sorted(Counter(entity["type"] for entity in entities).items()):
        print(f"  {name}: {count}")
    print("relations:")
    for name, count in sorted(Counter(relation["rel"] for relation in relations).items()):
        print(f"  {name}: {count}")
    return 0


def standing_note(entity):
    """A paper's saved citation count and when it was checked, so a paper list can reuse it without a request."""
    standing = entity.get("standing")
    if not standing:
        return ""
    counts = f"{count(standing['citations'], 'citation')}" if "citations" in standing else "no citation data"
    return f"  [{counts}, checked {standing['checked']}]"


def cmd_search(args):
    entities, _ = checked_load(args.data)
    matches = search(entities, args.text)
    for entity in matches:
        print(f"{entity['id']}  {entity['name']}{standing_note(entity)}")
    if not matches:
        print(f"no matches for {args.text!r}", file=sys.stderr)
        return 1
    return 0


def cmd_neighbours(args):
    entities, relations = checked_load(args.data)
    names = {entity["id"]: entity["name"] for entity in entities}
    start = resolve(entities, args.entity)
    print(f"{start['name']} ({start['id']})")
    for distance, direction, relation, other in neighbours(relations, start["id"], args.depth):
        print(f"  {distance}: {describe(relation, direction, names[other])}")
    return 0


def cmd_path(args):
    entities, relations = checked_load(args.data)
    names = {entity["id"]: entity["name"] for entity in entities}
    start, end = resolve(entities, args.start), resolve(entities, args.end)
    steps = shortest_path(relations, start["id"], end["id"])
    if steps is None:
        print(f"no path between {start['name']} and {end['name']}", file=sys.stderr)
        return 1
    print(start["name"])
    for direction, relation, other in steps:
        print(f"  {describe(relation, direction, names[other])}")
    return 0


def save(directory, entities, relations):
    """Validate the whole graph, then replace both files. Nothing is written if it's invalid."""
    errors = validate(entities, relations)
    if errors:
        raise GraphError("change refused, the graph would be invalid:\n" + "\n".join(f"  {e}" for e in errors))
    # Write both new files in full, then mark the change as complete, then swap them in. If this is
    # interrupted, recover() either finishes the swap (marker present) or discards the new files.
    for name, records in zip(FILES, (entities, relations)):
        with open(directory / f"{name}.tmp", "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
            handle.flush()
            os.fsync(handle.fileno())
    (directory / COMMIT_FILE).write_text("", encoding="utf-8")
    for name in FILES:
        os.replace(directory / f"{name}.tmp", directory / name)
    (directory / COMMIT_FILE).unlink()


def recover(directory):
    """Finish a save that was interrupted after it was marked complete, or discard one that wasn't."""
    marker = directory / COMMIT_FILE
    for name in FILES:
        temporary = directory / f"{name}.tmp"
        if temporary.exists():
            if marker.exists():
                os.replace(temporary, directory / name)
            else:
                temporary.unlink()
    marker.unlink(missing_ok=True)


# Written inline because mypy only understands platform checks in this form. On the system that runs it, a changed
# comparison mostly picks the same branch, so the line is marked.
if sys.platform == "win32":  # pragma: no mutate
    import msvcrt

    def try_lock(handle):
        """Try to take an exclusive operating-system lock on the file. True if it was taken."""
        try:
            handle.seek(0)  # pragma: no mutate (Windows only: never runs in a Linux mutation run)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # pragma: no mutate (Windows only)
        except OSError:  # pragma: no mutate (Windows only)
            return False  # pragma: no mutate (Windows only)
        return True  # pragma: no mutate (Windows only)

    def unlock(handle):
        handle.seek(0)  # pragma: no mutate (Windows only)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # pragma: no mutate (Windows only)

else:
    import fcntl

    # Marked alone: the two flags share no bits, so `+` and `^` give the same number as `|`.
    EXCLUSIVE_NOW = fcntl.LOCK_EX | fcntl.LOCK_NB  # pragma: no mutate

    def try_lock(handle):
        """Try to take an exclusive operating-system lock on the file. True if it was taken."""
        try:
            fcntl.flock(handle.fileno(), EXCLUSIVE_NOW)
        except OSError:
            return False
        return True

    def unlock(handle):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(path, wait, busy_message):
    """Hold a lock on a file for the block. The system drops it if the process dies, so it can't go stale."""
    deadline = time.monotonic() + wait
    with open(path, "a+b") as handle:
        while not try_lock(handle):
            if time.monotonic() > deadline:
                raise GraphError(busy_message)
            time.sleep(0.1)  # pragma: no mutate (a polling interval, a tuning value)
        try:
            yield
        finally:
            unlock(handle)


@contextlib.contextmanager
def locked(directory):
    """Let one graph command at a time read and change the files, across windows and processes."""
    path = directory / LOCK_FILE
    busy = f"another graph command is still running ({path}). Try again shortly"
    with file_lock(path, LOCK_WAIT, busy):
        recover(directory)
        yield


def parse_ids(pairs):
    ids = {}
    for pair in pairs:
        kind, _, value = pair.partition("=")
        if kind not in EXTERNAL_ID_KINDS or not value.strip():
            raise GraphError(f"--id must be KIND=VALUE with KIND one of {sorted(EXTERNAL_ID_KINDS)}: {pair!r}")
        ids[kind] = value.strip()
    return ids


def merge_ids(entity, ids):
    current = entity.setdefault("ids", {})
    for kind, value in ids.items():
        if kind in current and id_key(current[kind]) != id_key(value):
            raise GraphError(f"{entity['id']} already has {kind} id {current[kind]!r}, not {value!r}")
        current[kind] = value
    if not current:
        del entity["ids"]


def add_aliases(entity, aliases):
    taken = {name_key(label) for label in [entity["name"], *entity.get("aliases", [])]}
    for alias in aliases:
        if name_key(alias) not in taken:
            entity.setdefault("aliases", []).append(alias)
            taken.add(name_key(alias))


def describe_candidate(entity, reasons):
    return f"  {entity['id']}  {entity['name']}  ({', '.join(reasons)})"


def new_entity(args, entities):
    """The entity that add would create, from its arguments."""
    entity_id = f"{args.type}:{args.slug}" if args.slug else free_id(entities, f"{args.type}:{slugify(args.name)}")
    new = {"id": entity_id, "type": args.type, "name": args.name, "aliases": []}
    add_aliases(new, args.alias)
    for field in ("url", "note"):
        if getattr(args, field):
            new[field] = getattr(args, field)
    merge_ids(new, parse_ids(args.id))
    distinct = [resolve(entities, text)["id"] for text in args.distinct]
    if distinct:
        new["distinct_from"] = distinct
    return new


def report_possible_duplicates(found):
    print("possible duplicates:", file=sys.stderr)
    for entity, reasons, _ in found:
        print(describe_candidate(entity, reasons), file=sys.stderr)
    print(
        "If it is one of these, use update on it instead. If it is different from all of them,"
        " run add again with --distinct for each.",
        file=sys.stderr,
    )


def cmd_add(args):
    entities, relations = checked_load(args.data)
    new = new_entity(args, entities)
    found = candidates(entities, new)
    strong = [describe_candidate(entity, reasons) for entity, reasons, is_strong in found if is_strong]
    if strong:
        raise GraphError(
            "already in the graph:\n"
            + "\n".join(strong)
            + "\nIf it is the same thing, use update to add aliases or ids."
            " If it is a different thing with the same name, as can happen with authors, run add again with --distinct."
        )
    if found:
        report_possible_duplicates(found)
        return 3
    taken = next((entity for entity in entities if entity["id"] == new["id"]), None)
    if taken:  # only an explicit --slug can be taken: a generated id is always free
        raise GraphError(f"{new['id']} is already used by {taken['name']!r}; pick another --slug")
    save(args.data, entities + [new], relations)
    print(f"added {new['id']}")
    return 0


def cmd_update(args):
    entities, relations = checked_load(args.data)
    entity = resolve(entities, args.entity)
    add_aliases(entity, args.alias)
    merge_ids(entity, parse_ids(args.id))
    for field in ("url", "note"):
        if getattr(args, field):
            entity[field] = getattr(args, field)
    for text in args.distinct:
        other = resolve(entities, text)["id"]
        if other not in entity.setdefault("distinct_from", []):
            entity["distinct_from"].append(other)
    save(args.data, entities, relations)
    print(f"updated {entity['id']}")
    return 0


def link(relations, start, rel, end, source, status):
    """Add a relation unless the same one exists. Return True if it was added."""
    if any((r["from"], r["rel"], r["to"]) == (start, rel, end) for r in relations):
        return False
    relations.append({"from": start, "rel": rel, "to": end, "source": source, "status": status})
    return True


def cmd_link(args):
    entities, relations = checked_load(args.data)
    start, end = resolve(entities, args.start)["id"], resolve(entities, args.end)["id"]
    if unsourced({"source": args.source, "status": args.status}):
        raise GraphError(f"a verified link must name the document it was checked against: {SOURCE_FIX}")
    if link(relations, start, args.rel, end, args.source, args.status):
        save(args.data, entities, relations)
        print(f"linked {start} {args.rel} {end}")
    else:
        print(f"already linked: {start} {args.rel} {end}")
    return 0


def cmd_unlink(args):
    entities, relations = checked_load(args.data)
    start, end = resolve(entities, args.start)["id"], resolve(entities, args.end)["id"]
    target = (start, args.rel, end)
    if target not in {(r["from"], r["rel"], r["to"]) for r in relations}:
        raise GraphError(f"no relation {start} {args.rel} {end}")
    kept = [r for r in relations if (r["from"], r["rel"], r["to"]) != target]
    save(args.data, entities, kept)
    print(f"unlinked {start} {args.rel} {end}")
    return 0


def cmd_remove(args):
    entities, relations = checked_load(args.data)
    entity = resolve(entities, args.entity)
    target = entity["id"]
    kept = list(entities)
    kept.remove(entity)
    for other in kept:
        if target in other.get("distinct_from", []):
            other["distinct_from"].remove(target)
            if not other["distinct_from"]:
                del other["distinct_from"]
    links = [r for r in relations if target not in (r["from"], r["to"])]
    save(args.data, kept, links)
    print(f"removed {target} and {len(relations) - len(links)} relations")
    return 0


def merge(entities, relations, keep, drop):
    """Fold the entity drop into keep: names, aliases, ids, and every relation. Returns the new lists."""
    keep_id, drop_id = keep["id"], drop["id"]
    if keep is drop:  # pragma: no mutate (two different entities never compare equal, so == agrees)
        raise GraphError("merge needs two different entities of the same type")
    if keep["type"] != drop["type"]:
        raise GraphError("merge needs two different entities of the same type")
    if marked_distinct(keep, drop):
        raise GraphError(f"{keep_id} and {drop_id} were checked and marked as distinct, so they can't be merged")
    absorb(keep, drop)
    kept = list(entities)
    kept.remove(drop)
    for entity in kept:
        repoint_distinct(entity, keep_id, drop_id)
    return kept, merged_relations(relations, keep_id, drop_id)


def absorb(keep, drop):
    """Give keep the distinct marks, ids, names, url, and note of drop."""
    for other in drop.get("distinct_from", []):
        if other not in keep.setdefault("distinct_from", []):
            keep["distinct_from"].append(other)
    merge_ids(keep, drop.get("ids", {}))
    add_aliases(keep, [drop["name"], *drop.get("aliases", [])])
    for field in ("url", "note"):
        if field in drop and field not in keep:
            keep[field] = drop[field]
    if "standing" in drop and drop["standing"]["checked"] > keep.get("standing", {}).get("checked", ""):
        keep["standing"] = drop["standing"]


def repoint_distinct(entity, keep_id, drop_id):
    """Make distinct marks that named drop name keep, without duplicates or marks on itself."""
    others = [keep_id if o == drop_id else o for o in entity.get("distinct_from", [])]
    others = list(dict.fromkeys(others))  # a mark on the entity itself can't arise: the save would refuse it
    if others:
        entity["distinct_from"] = others
    else:
        entity.pop("distinct_from", None)


def repoint(relation, keep_id, drop_id):
    ends = {end: keep_id if relation[end] == drop_id else relation[end] for end in ("from", "to")}
    return {**relation, **ends}


def merged_relations(relations, keep_id, drop_id):
    """The relations with drop replaced by keep, dropping loops and keeping one of each, verified first."""
    merged: dict[tuple, dict] = {}
    for relation in (repoint(r, keep_id, drop_id) for r in relations):
        key = (relation["from"], relation["rel"], relation["to"])
        if relation["from"] == relation["to"]:
            continue
        if key not in merged or STRENGTH.index(relation["status"]) > STRENGTH.index(merged[key]["status"]):
            merged[key] = relation
    return list(merged.values())


def cmd_merge(args):
    entities, relations = checked_load(args.data)
    keep, drop = resolve(entities, args.keep), resolve(entities, args.drop)
    entities, relations = merge(entities, relations, keep, drop)
    save(args.data, entities, relations)
    print(f"merged {drop['id']} into {keep['id']}")
    return 0


def cmd_dupes(args):
    entities, _ = checked_load(args.data)
    found = dupes(entities)
    for a, b, reasons in found:
        print(f"{a['id']}  <->  {b['id']}  ({', '.join(reasons)})")
    if not found:
        print("no likely duplicates")
    return 0


def cmd_islands(args):
    entities, relations = checked_load(args.data)
    found = islands(entities, relations)
    for entity in found:
        print(f"{entity['id']}  {entity['name']}")
    if not found:
        print("every paper has extracted entities")
    return 0


def s2_keys(paper):
    """Identifier keys for a paper record from the scholar client."""
    keys: set[tuple[str, ...]] = set()
    if paper.get("paperId"):
        keys.add(("s2", str(paper["paperId"]).casefold()))
    for name, kind in (("ArXiv", "arxiv"), ("DOI", "doi")):
        value = (paper.get("externalIds") or {}).get(name)
        if value:
            keys.add((kind, str(value).casefold()))
    return keys


def cites(entities, relations, paper_id, record):
    """Add cites relations between this paper and graph papers found in its references and citations."""
    index = {key: e["id"] for e in entities if is_paper(e) for key in external_keys(e)}
    added = []
    for edge, start, end in citation_pairs(index, paper_id, record):
        if link(relations, start, "cites", end, CITATION_SOURCES[edge], "verified"):
            added.append((start, end))
    return added


def citation_pairs(index, paper_id, record):
    """(edge, citing id, cited id) for each reference or citation that is a paper in the graph."""
    for edge in CITATION_SOURCES:
        for match in papers_in_graph(index, record.get(edge) or []):
            if match != paper_id:  # pragma: no mutate (the paper's own id is the very string it matches)
                yield (edge, paper_id, match) if edge in OUTGOING else (edge, match, paper_id)


def papers_in_graph(index, papers):
    """The graph id of each Semantic Scholar paper record that matches a paper in the graph."""
    for paper in papers:
        match = next((index[key] for key in s2_keys(paper) if key in index), None)
        if match:
            yield match


def read_citations(file):
    """The saved output of s2.py paper ID --references --citations."""
    try:
        record = json.loads(Path(file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise GraphError(f"can't read {file}: {err}") from None
    if not isinstance(record, dict) or ("references" not in record and "citations" not in record):
        raise GraphError("expected the output of: s2.py paper ID --references --citations")
    return record


def adopt_s2_id(paper, record):
    """Give the paper the Semantic Scholar id from the record, if it has none yet."""
    if "s2" not in dict(external_keys(paper)) and "s2" in dict(s2_keys(record)):
        merge_ids(paper, {"s2": record["paperId"]})


def today():
    return datetime.date.today().isoformat()


def set_standing(paper, record):
    """Copy the paper's citation counts, venue, and year from a Semantic Scholar record. True if it had counts."""
    if type(record.get("citationCount")) is not int:  # pragma: no mutate (types are unique, so != agrees)
        return False
    standing = {"citations": record["citationCount"]}
    for field, key, kind in (
        ("influential", "influentialCitationCount", int),
        ("venue", "venue", str),
        ("year", "year", int),
    ):
        # pragma: no mutate below: types are unique objects, and so is the empty string, so `==` agrees with `is`.
        if type(record.get(key)) is kind and record[key] != "":  # pragma: no mutate
            standing[field] = record[key]
    paper["standing"] = {**standing, "checked": today()}
    return True


def describe_standing(paper):
    standing = paper["standing"]
    return f"{paper['id']}: {standing['citations']} citations, checked {standing['checked']}"


def cmd_cites(args):
    entities, relations = checked_load(args.data)
    paper = resolve(entities, args.paper)
    if not is_paper(paper):
        raise GraphError(f"{paper['id']} is not a paper")
    record = read_citations(args.file)
    adopt_s2_id(paper, record)
    added = cites(entities, relations, paper["id"], record)
    has_standing = set_standing(paper, record)
    save(args.data, entities, relations)
    for start, end in added:
        print(f"linked {start} cites {end}")
    print(f"{len(added)} citation links added")
    if has_standing:
        print(f"standing: {describe_standing(paper)}")
    return 0


def read_batch(file):
    """The saved output of s2.py batch, or of s2.py paper, as a list of paper records."""
    try:
        records = json.loads(Path(file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise GraphError(f"can't read {file}: {err}") from None
    records = [records] if isinstance(records, dict) else records
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise GraphError("expected the output of: s2.py batch ID...")
    return records


def count(number, word):
    return f"{number} {word}{'' if number == 1 else 's'}"


def requested_keys(record):
    """The key of the id that was asked about. A paper Semantic Scholar doesn't know comes back with nothing else."""
    asked = str(record.get("requestedId") or "")
    kind, _, value = asked.partition(":")
    if kind in ("ARXIV", "DOI") and value:
        return {(kind.lower(), id_key(value))}
    return {("s2", id_key(asked))} if asked else set()


def mark_checked(paper):
    """Note that Semantic Scholar had no counts for the paper, so it isn't asked again until the check is old.
    Counts saved earlier are kept."""
    if "citations" not in paper.get("standing", {}):
        paper["standing"] = {"checked": today()}


def find_paper(index, record):
    """The graph paper a Semantic Scholar record describes, or None if it isn't in the graph."""
    return next((index[key] for key in s2_keys(record) | requested_keys(record) if key in index), None)


def save_counts(paper, record):
    """Save the record's counts on the paper. Returns "updated", or "no counts" if the record had none."""
    if set_standing(paper, record):
        adopt_s2_id(paper, record)
        return "updated"
    mark_checked(paper)
    return "no counts"


def apply_standing(entities, relations, records):
    """Save each record's counts, and link the paper to the graph papers in its reference list. Returns how many
    papers were updated, had no counts, or matched no paper in the graph, how many records came with a reference
    list, and how many citation links they added."""
    index = {key: e for e in entities if is_paper(e) for key in external_keys(e)}
    results: Counter[str] = Counter()
    for record in records:
        paper = find_paper(index, record)
        if paper is None:
            results["unmatched"] += 1
            continue
        results[save_counts(paper, record)] += 1
        if isinstance(record.get("references"), list):
            results["with references"] += 1
            results["links"] += len(cites(entities, relations, paper["id"], record))
    return results


def standing_summary(results):
    summary = [f"{count(results['updated'], 'paper')} updated"]
    if results["no counts"]:
        summary.append(f"{results['no counts']} without citation data")
    if results["with references"]:
        summary.append(f"{count(results['links'], 'citation link')} added")
    summary.append(f"{count(results['unmatched'], 'record')} matched no paper in the graph")
    return ", ".join(summary)


def cmd_standing(args):
    entities, relations = checked_load(args.data)
    results = apply_standing(entities, relations, read_batch(args.file))
    save(args.data, entities, relations)
    print(standing_summary(results))
    return 0


def lookup_id(paper):
    """The id to look the paper up by on Semantic Scholar, or None if it has none."""
    keys = dict(external_keys(paper))
    for kind, prefix in (("s2", ""), ("arxiv", "ARXIV:"), ("doi", "DOI:")):
        if kind in keys:
            return prefix + keys[kind]
    return None


def cmd_standing_due(args):
    entities, _ = checked_load(args.data)
    cutoff = (datetime.date.today() - datetime.timedelta(days=args.days)).isoformat()
    due = [
        lookup_id(e)
        for e in entities
        if is_paper(e) and e.get("standing", {}).get("checked", "") <= cutoff and lookup_id(e)
    ]
    try:
        Path(args.file).write_text("".join(f"{paper_id}\n" for paper_id in due), encoding="utf-8")
    except OSError as err:
        raise GraphError(f"can't write {args.file}: {err}") from None
    print(f"{count(len(due), 'paper')} due" if due else "no papers due")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Query and change the knowledge graph.")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="folder with entities.jsonl and relations.jsonl (default: research/graph)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("validate", help="check the graph files").set_defaults(func=cmd_validate)
    commands.add_parser("stats", help="count entities and relations").set_defaults(func=cmd_stats)

    search_cmd = commands.add_parser("search", help="find entities by text")
    search_cmd.add_argument("text")
    search_cmd.set_defaults(func=cmd_search)

    neighbours_cmd = commands.add_parser("neighbours", help="show an entity's connections")
    neighbours_cmd.add_argument("entity", help="id, name, or alias")
    neighbours_cmd.add_argument("--depth", type=int, default=1)
    neighbours_cmd.set_defaults(func=cmd_neighbours)

    path_cmd = commands.add_parser("path", help="show how two entities connect")
    path_cmd.add_argument("start")
    path_cmd.add_argument("end")
    path_cmd.set_defaults(func=cmd_path)

    dupes_cmd = commands.add_parser("dupes", help="list entities that might be duplicates")
    dupes_cmd.set_defaults(func=cmd_dupes)
    islands_cmd = commands.add_parser("islands", help="list papers with nothing extracted yet")
    islands_cmd.set_defaults(func=cmd_islands)

    def entity_fields(command):
        command.add_argument("--alias", action="append", default=[], help="another name; repeat for more")
        command.add_argument(
            "--id",
            action="append",
            default=[],
            metavar="KIND=VALUE",
            help=f"external id, KIND one of {', '.join(sorted(EXTERNAL_ID_KINDS))}",
        )
        command.add_argument("--url")
        command.add_argument("--note")
        command.add_argument(
            "--distinct",
            action="append",
            default=[],
            metavar="ENTITY",
            help="confirm it is not this possible duplicate; repeat for more",
        )

    add_cmd = commands.add_parser("add", help="add an entity after checking for duplicates")
    add_cmd.add_argument("--type", required=True, choices=sorted(ENTITY_TYPES))
    add_cmd.add_argument("--name", required=True)
    add_cmd.add_argument("--slug", help="id after the type prefix; default: made from the name")
    entity_fields(add_cmd)
    add_cmd.set_defaults(func=cmd_add)

    update_cmd = commands.add_parser("update", help="add aliases, ids, or details to an entity")
    update_cmd.add_argument("entity", help="id, name, or alias")
    entity_fields(update_cmd)
    update_cmd.set_defaults(func=cmd_update)

    link_cmd = commands.add_parser("link", help="add a relation between two entities")
    link_cmd.add_argument("start", help="id, name, or alias")
    link_cmd.add_argument("rel", choices=sorted(RELATION_TYPES))
    link_cmd.add_argument("end", help="id, name, or alias")
    link_cmd.add_argument("--source", required=True, help="where it comes from, such as ARXIV:2401.00001, section 3")
    link_cmd.add_argument("--status", required=True, choices=sorted(STATUSES))
    link_cmd.set_defaults(func=cmd_link)

    unlink_cmd = commands.add_parser("unlink", help="remove one relation")
    unlink_cmd.add_argument("start")
    unlink_cmd.add_argument("rel", choices=sorted(RELATION_TYPES))
    unlink_cmd.add_argument("end")
    unlink_cmd.set_defaults(func=cmd_unlink)

    remove_cmd = commands.add_parser("remove", help="remove an entity and all its relations")
    remove_cmd.add_argument("entity")
    remove_cmd.set_defaults(func=cmd_remove)

    merge_cmd = commands.add_parser("merge", help="fold a duplicate into the entity to keep")
    merge_cmd.add_argument("keep")
    merge_cmd.add_argument("drop")
    merge_cmd.set_defaults(func=cmd_merge)

    cites_cmd = commands.add_parser("cites", help="link a paper to graph papers it cites or is cited by")
    cites_cmd.add_argument("paper", help="id, name, or alias")
    cites_cmd.add_argument("file", help="saved output of: s2.py paper ID --references --citations")
    cites_cmd.set_defaults(func=cmd_cites)

    standing_cmd = commands.add_parser("standing", help="save papers' citation counts from Semantic Scholar")
    standing_cmd.add_argument("file", help="saved output of: s2.py batch ID...")
    standing_cmd.set_defaults(func=cmd_standing)

    due_cmd = commands.add_parser(
        "standing-due", help="write the ids of papers whose standing is missing or old to a file, one per line"
    )
    due_cmd.add_argument("file", help="where to write the ids, for: s2.py batch --ids-file FILE")
    due_cmd.add_argument("--days", type=int, default=30, help="how old a check may be (default: 30)")
    due_cmd.set_defaults(func=cmd_standing_due)

    return parser


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    try:
        if not args.data.is_dir():
            raise GraphError(f"graph folder not found: {args.data}")
        with locked(args.data):
            return args.func(args)
    except GraphError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no mutate (`is` and `<=` agree for the names a module can have)
    sys.exit(main())
