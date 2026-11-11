"""Build the pairs of the duplicate-detection evaluation, as SPEC.md section 3 describes. Run by hand, never in CI.

It downloads entities with the names they go by from DBLP, Wikidata, the Hugging Face Hub, and the Papers with Code
archive, and writes pairs of an existing entity and a new name, each known to be the same thing or different things,
split into dev and test. The output is committed, so every evaluation reads the same frozen files.

  python evals/dedup/build_dataset.py [--scale X] [--seed N] [--cache DIR] [--out DIR] [--audit]

--audit asks Jev, through OpenRouter (OPENROUTER_API_KEY), about every second name not yet judged in data/audit.jsonl.
Without it the build only reads that file, needs no key, and prints how many names are unjudged and what asking would
cost.

--scale multiplies every target: 1 for the dataset, less for a quick look.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import gzip
import hashlib
import json
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "skills" / "graph" / "scripts"))
import audit_labels  # noqa: E402

import graph  # noqa: E402

TYPES = ("author", "tool", "model", "method", "dataset")
SPLITS = ("dev", "test")
SEED = 20261108
# Pairs per split, for each kind (SPEC.md section 2). A kind with fewer candidates gives all it has; within a kind,
# the types take turns, so a type with few candidates gives all of them and the others share the rest.
TARGETS = {
    "similar name": 500,
    "known alias": 200,
    "dissimilar name": 300,
    "look-alike": 500,
    "same name": 300,
    "alias collision": 300,
}
MESSY_PER_KIND = 20
SAME, DIFFERENT = "same", "different"
LABELS = {
    "similar name": SAME,
    "known alias": SAME,
    "dissimilar name": SAME,
    "messy": SAME,
    "look-alike": DIFFERENT,
    "same name": DIFFERENT,
    "alias collision": DIFFERENT,
}
# Different records of these sources are different things: their editors merge duplicates (DBLP, Wikidata). Papers
# with Code is left out, since most of its records with the same name are one dataset entered twice, and so is the
# Hub, where a repository of the same name in another account is mostly a copy of the same weights.
DISTINCT_SOURCES = frozenset({"dblp", "wikidata"})
# A second name is similar when it shares a whole word with the first name or is this close to it by edit ratio. The
# detector compares character trigrams, so this is a different measure; it decides only the kind of a pair.
SIMILAR_RATIO = 0.6
MIN_PAPERS = 2  # Papers with Code records cited by fewer papers are mostly spam
CROWDED_KEY = 200  # a look-alike key shared by more entities than this is too common to mean anything
HUB_PAGES = 2  # of 1,000 models each, the most downloaded first
WIKIDATA = "https://query.wikidata.org/sparql"
DBLP = "https://sparql.dblp.org/sparql"
HUB = "https://huggingface.co/api/models?sort=downloads&direction=-1&limit=1000"
# People whose DBLP id starts with one of these: about 11,600 each, chosen by nothing about their names.
DBLP_SLICES = ("17", "27")
RETRIES = 4
# Words that follow a person's surname (in the form graph.loose gives them), so the surname is the word before.
SUFFIXES = frozenset({"jr", "sr", "junior", "senior", "filho", "neto", "ii", "iii", "iv"})
USER_AGENT = "paper-research-eval/0.1 (https://github.com/marfago-labs/paper-research)"
PWC = "https://huggingface.co/datasets/pwc-archive/files/resolve/main/"
PWC_FILES = {"method": "jul-28-methods.json.gz", "dataset": "jul-28-datasets.json.gz"}
SOFTWARE = "wd:Q7397 wd:Q341 wd:Q188860 wd:Q1130645 wd:Q271680"
MODELS = "wd:Q115305900 wd:Q115215420"
LICENCES = {
    "wikidata": "CC0 1.0 (https://creativecommons.org/publicdomain/zero/1.0/)",
    "dblp": "CC0 1.0 (https://creativecommons.org/publicdomain/zero/1.0/), dblp computer science bibliography",
    "hf": "Hugging Face Hub API metadata: repository ids only, no model content",
    "pwc": "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/), Papers with Code archive of 2025-07-28",
}

# DBLP people, with every name they published under and their ORCID. DBLP's editors split people who share a name
# into separate persons, and collect papers they can't yet assign in placeholder profiles (AmbiguousCreator), which
# are not one person and are left out.
DBLP_PREFIXES = """PREFIX dblp: <https://dblp.org/rdf/schema#> PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""
PERSON_FIELDS = """?item rdf:type dblp:Person ; dblp:primaryCreatorName ?label .
  FILTER NOT EXISTS {{ ?item rdf:type dblp:AmbiguousCreator }}
  OPTIONAL {{ ?item dblp:creatorName ?alias }}
  OPTIONAL {{ ?item owl:sameAs ?orcid . FILTER(STRSTARTS(STR(?orcid), "https://orcid.org/")) }}"""
AUTHORS = (
    DBLP_PREFIXES
    + """SELECT ?item ?label ?alias ?orcid WHERE {{ """
    + PERSON_FIELDS
    + """
  FILTER(STRSTARTS(STR(?item), "https://dblp.org/pid/{slice}/")) }}"""
)
# For each person of the slice who shares a name with another DBLP person, one such person.
HOMONYMS = (
    DBLP_PREFIXES
    + """SELECT ?item (SAMPLE(?namesake) AS ?other) WHERE {{
  ?item rdf:type dblp:Person ; dblp:primaryCreatorName ?name . FILTER(STRSTARTS(STR(?item), "https://dblp.org/pid/{slice}/"))
  FILTER NOT EXISTS {{ ?item rdf:type dblp:AmbiguousCreator }}
  ?namesake rdf:type dblp:Person ; dblp:primaryCreatorName ?name . FILTER(?namesake != ?item)
  FILTER NOT EXISTS {{ ?namesake rdf:type dblp:AmbiguousCreator }} }} GROUP BY ?item"""
)
PEOPLE = (
    DBLP_PREFIXES + "SELECT ?item ?label ?alias ?orcid WHERE {{ VALUES ?item {{ {items} }} " + PERSON_FIELDS + " }}"
)
GOLD_PREFIX = {"wikidata": "wd:", "dblp": "dblp:"}
URI_PREFIXES = ("http://www.wikidata.org/entity/", "https://dblp.org/pid/", "https://orcid.org/")
ITEMS = """SELECT ?item ?label ?alias ?repo WHERE {{
  ?item wdt:P31 ?class {extra} ; rdfs:label ?label . VALUES ?class {{ {classes} }} FILTER(LANG(?label) = "en")
  OPTIONAL {{ ?item skos:altLabel ?alias . FILTER(LANG(?alias) = "en") }}
  OPTIONAL {{ ?item wdt:P1324 ?repo }} }}"""


# Fetching


def sparql(query, endpoint=WIKIDATA):
    """Rows of a query to Wikidata or DBLP, each a dict of variable to value, with URIs shortened to their id."""
    url = f"{endpoint}?{urllib.parse.urlencode({'query': query})}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    request = urllib.request.Request(url, headers=headers)
    bindings = with_retries(lambda: fetch_json(request)["results"]["bindings"])
    time.sleep(2)  # be gentle with the public endpoint
    return [{key: shorten(value["value"]) for key, value in row.items()} for row in bindings]


def cached(cache, key, produce):
    """produce()'s result, from the cache if it holds one for key and otherwise written there. With the same cache and
    seed a rebuild gives the same pairs: the sources change, and the cache is what fixes them."""
    path = Path(cache) / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = produce()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


def rows_of(query, cache, endpoint=WIKIDATA):
    """The rows of a SPARQL query, cached."""
    return cached(cache, endpoint + query, lambda: sparql(query, endpoint))


def fetch_json(request):
    with urllib.request.urlopen(request, timeout=180) as response:  # nosec B310: a fixed https endpoint
        return json.load(response)


def with_retries(fetch):
    """fetch(), tried again after a pause when the public endpoint is busy, as it often is for a moment."""
    for attempt in range(1, RETRIES):
        try:
            return fetch()
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(30 * attempt)
    return fetch()


def shorten(value):
    """A Wikidata item, DBLP person, or ORCID URI as its id: 'Q42', '17/10073', '0000-0002-7622-6714'."""
    prefix = next((prefix for prefix in URI_PREFIXES if value.startswith(prefix)), "")
    return value[len(prefix) :]


def pwc_records(name, cache):
    """A Papers with Code archive file, downloaded once into cache."""
    path = Path(cache) / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(PWC + name, path)  # nosec B310: a fixed https URL
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def hub_page(url):
    """(models, the next page's URL or None) for one page of the Hub's model list."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310: a fixed https endpoint
        found = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("Link") or "")
        return json.load(response), found.group(1) if found else None


def hub_models(pages=HUB_PAGES):
    """The most downloaded models on the Hugging Face Hub, pages of 1,000 at a time."""
    models: list = []
    url = HUB
    for _ in range(pages):
        found, url = with_retries(lambda url=url: hub_page(url))
        models += found
        if not url:
            break
    return models


# Entities


def github_id(url):
    """'org/repo' from a GitHub URL, or None."""
    parsed = urllib.parse.urlparse(url or "")
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.lower() not in ("github.com", "www.github.com") or len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def row_ids(row):
    ids = {}
    if row.get("orcid"):
        ids["orcid"] = row["orcid"]
    repo = github_id(row.get("repo"))
    if repo:
        ids["github"] = repo
    return ids


def add_alias(group, alias):
    """Add alias to the group's names, unless it differs from one of them only in case or separators: that is the
    same name."""
    if graph.name_key(alias) not in {graph.name_key(name) for name in group["names"]} | {""}:
        group["names"].append(alias)


def sparql_groups(rows, entity_type, source="wikidata"):
    """{gold: group} from Wikidata or DBLP rows of item, label, and optional alias and ids."""
    groups: dict = {}
    for row in rows:
        gold = GOLD_PREFIX[source] + row["item"]
        group = groups.setdefault(
            gold, {"gold": gold, "type": entity_type, "names": [row["label"]], "ids": {}, "source": source}
        )
        if row.get("alias"):
            add_alias(group, row["alias"])
        group["ids"].update(row_ids(row))
    return groups


def looks_like_a_name(record):
    """Whether a Papers with Code record still holds a real name. Spam overwrote thousands of records with support-line
    text ('How to Contact ... Support'), which is long or asks something, and spam is cited by at most one paper.
    Keeping records with a short name, no question, and at least two papers leaves no spam in a hand check."""
    name, full = (record.get("name") or "").strip(), (record.get("full_name") or "").strip()
    short = 0 < len(name) <= 40 and len(full) <= 120 and "?" not in name + full
    return short and (record.get("num_papers") or 0) >= MIN_PAPERS


def pwc_groups(records, entity_type):
    """{gold: group} for the Papers with Code records that hold a name: the short name, and the full name if it
    differs."""
    groups = {}
    for record in records:
        if not looks_like_a_name(record):
            continue
        name, full = record["name"].strip(), (record.get("full_name") or "").strip()
        gold = "pwc:" + urllib.parse.urlparse(record["url"]).path.strip("/")
        groups[gold] = {"gold": gold, "type": entity_type, "names": [name], "ids": {}, "source": "pwc"}
        add_alias(groups[gold], full)
    return groups


def hub_groups(models):
    """{gold: group} for Hub models: the repository name as the name, the full repository id as the hf id."""
    groups = {}
    for repo in (model["id"] for model in models):
        name = repo.rsplit("/", 1)[-1]
        groups["hf:" + repo] = {
            "gold": "hf:" + repo,
            "type": "model",
            "names": [name],
            "ids": {"hf": repo},
            "source": "hf",
        }
    return groups


def fetch_authors(cache):
    """Author groups from the DBLP slices, with the people outside them who share a name with one of them, so that
    homonyms are found among the authors like any other pair of entities with one name."""
    people: dict = {}
    rows: list = []
    for prefix in DBLP_SLICES:
        people.update(sparql_groups(rows_of(AUTHORS.format(slice=prefix), cache, DBLP), "author", "dblp"))
        rows += rows_of(HOMONYMS.format(slice=prefix), cache, DBLP)
    missing = sorted({row["other"] for row in rows} - {gold.removeprefix("dblp:") for gold in people})
    for start in range(0, len(missing), 200):
        batch = " ".join(f"<https://dblp.org/pid/{item}>" for item in missing[start : start + 200])
        people.update(sparql_groups(rows_of(PEOPLE.format(items=batch), cache, DBLP), "author", "dblp"))
    return people


def without(groups, others):
    """The groups that are not also in others. A Wikidata item can be both a Python tool and a model (Whisper); in
    two pools it would give the same pairs twice, which are not independent. It stays a model, the narrower class."""
    return {gold: group for gold, group in groups.items() if gold not in others}


def fetch_groups(cache):
    """{type: {gold: group}} for every type."""
    python_software = ITEMS.format(classes=SOFTWARE, extra="; wdt:P277 wd:Q28865")
    wikidata_models = sparql_groups(rows_of(ITEMS.format(classes=MODELS, extra=""), cache), "model")
    hub = cached(cache, f"{HUB} {HUB_PAGES}", hub_models)
    models = {**wikidata_models, **hub_groups(hub)}
    pools = {
        "author": fetch_authors(cache),
        "tool": without(sparql_groups(rows_of(python_software, cache), "tool"), models),
        "model": models,
    }
    for entity_type, name in PWC_FILES.items():
        pools[entity_type] = pwc_groups(pwc_records(name, cache), entity_type)
    return pools


# Second names and their audit


def similar_names(first, second):
    """Whether the second name is close enough to the first for a search by spelling to be expected to find it: they
    share a whole word, or their edit ratio is at least SIMILAR_RATIO. Compared in the detector's loose form."""
    x, y = graph.loose(first), graph.loose(second)
    return bool(set(x.split()) & set(y.split())) or difflib.SequenceMatcher(None, x, y).ratio() >= SIMILAR_RATIO


def audited(pools):
    """The groups whose second names Jev judges: every source but DBLP, whose variants are curated by its editors."""
    return [group for pool in pools.values() for group in pool.values() if group["source"] != "dblp"]


def second_name_pairs(pools):
    """(type, first name, second name) for every second name the audit judges."""
    return [(group["type"], group["names"][0], name) for group in audited(pools) for name in group["names"][1:]]


def apply_audit(pools, verdicts):
    """Take out of each group, in place, the second names Jev is confident are not the same thing as the first.
    Returns {source and type: {"kept", "removed", "unaudited"}}: a name Jev has not seen is kept, and counted, so a
    build without --audit shows how much is left unjudged."""
    found: dict = defaultdict(Counter)
    for group in (group for pool in pools.values() for group in pool.values()):
        found[f"{group['source']} {group['type']}"].update(filter_names(group, verdicts))
    return {key: dict(counts) for key, counts in sorted(found.items())}


def filter_names(group, verdicts):
    """Apply the audit to one group, in place. Returns what happened to its second names, as counts."""
    first, seconds = group["names"][0], group["names"][1:]
    judged = group["source"] != "dblp"
    rows = {name: verdicts.get((group["type"], first, name)) if judged else None for name in seconds}
    group["names"] = [first] + [name for name, row in rows.items() if not audit_labels.rejected(row)]
    return {
        "removed": sum(audit_labels.rejected(row) for row in rows.values()),
        "unaudited": sum(row is None for row in rows.values()) if judged else 0,
        "kept": len(group["names"]) - 1,
    }


def audit(args, pools):
    """Judge the second names not yet in the audit file, if asked to, and remove the ones the audit rejects. Without
    --audit, print how many are unjudged and about what asking would cost, from the answers kept so far."""
    path = Path(args.out) / "audit.jsonl"
    pairs, known = second_name_pairs(pools), audit_labels.load(path)
    todo = audit_labels.missing(pairs, known)
    guess = audit_labels.estimate(len(todo), known)
    print(f"audit: {len(todo)} of {len(set(pairs))} second names unjudged" + cost_text(guess))
    if args.audit and todo:
        spent = audit_labels.judge(pairs, path, audit_labels.api_key(), max_cost=args.audit_budget)
        print(
            f"audit: asked {spent['asked']}, skipped {spent['skipped']}, not asked {spent['not asked']}; "
            f"{spent['input_tokens']} input and {spent['output_tokens']} output tokens, ${spent['cost']:.4f}"
        )
    return apply_audit(pools, audit_labels.load(path))


def cost_text(guess):
    return "" if guess is None else f", about ${guess:.4f} to ask"


# Look-alikes


def surname_words(words):
    """The words of a person's name without the generational suffixes that follow a surname ('Healy Jr.', 'Almeida
    Júnior', 'Smith III'), which would otherwise be taken for it. A closed list: nothing else follows a surname so."""
    while words and words[-1] in SUFFIXES:
        words = words[:-1]
    return words


def look_alike_keys(group):
    """Keys that look-alikes share, found by rules and never by the detector's score: surname and first initial
    for people; for other things, a shared word of four letters or more, or the same name without its numbers."""
    words = graph.loose(group["names"][0]).split()
    if group["type"] == "author":
        words = surname_words(words)
        return {("person", words[-1], words[0][0])} if len(words) >= 2 else set()
    keys = {("word", word) for word in words if len(word) >= 4 and not word.isdigit()}
    base = " ".join(word for word in words if not word.isdigit())
    if base != " ".join(words):
        keys.add(("family", base))
    return keys


def look_alike_index(pool):
    index = defaultdict(list)
    for gold in sorted(pool):
        for key in look_alike_keys(pool[gold]):
            index[key].append(gold)
    return {key: golds for key, golds in index.items() if len(golds) <= CROWDED_KEY}


# Pairs


def side(group, name, aliases=()):
    """One side of a pair: an entity under one of its names, with its ids, and aliases if it is the existing side."""
    return {"gold": group["gold"], "name": name, "aliases": list(aliases), "ids": dict(group["ids"])}


def pair(kind, existing, new, group, **extra):
    """A pair of kind: the existing side and the new side, which has no aliases since add is given a name alone."""
    del new["aliases"]
    row = {"kind": kind, "label": LABELS[kind], "type": group["type"], "source": group["source"]}
    return {**row, **extra, "existing": existing, "new": new}


def by_source(pool):
    """{source: {gold: group}}: pairs of different things are only formed within one source."""
    found: dict = defaultdict(dict)
    for gold, group in pool.items():
        found[group["source"]][gold] = group
    return found


def name_pairs(pool, rng):
    """{kind: [pairs]} of one entity's first name and one of its other names: similar, dissimilar, and known alias.
    One pair per entity and kind, so that pairs are independent."""
    found: dict = defaultdict(list)
    for gold in sorted(pool):
        for row in entity_name_pairs(pool[gold], rng):
            found[row["kind"]].append(row)
    return found


def entity_name_pairs(group, rng):
    """The name pairs of one entity: none if it has a single name."""
    first, others = group["names"][0], group["names"][1:]
    if not others:
        return []
    similar = [name for name in others if similar_names(first, name)]
    options = {"similar name": similar, "dissimilar name": [name for name in others if name not in similar]}
    found = [
        pair(kind, side(group, first), side(group, rng.choice(names)), group)
        for kind, names in options.items()
        if names
    ]
    return found + [pair("known alias", side(group, first, others), side(group, rng.choice(others)), group)]


def look_alike_pairs(pool, rng):
    """Pairs of a seed and a look-alike with another name, within one source; each entity in at most one pair."""
    found = []
    for source_pool in by_source(pool).values():
        index = look_alike_index(source_pool)
        used: set = set()
        order = sorted(source_pool)
        rng.shuffle(order)
        for seed in order:
            choice = pick_look_alike(seed, source_pool, index, used, rng)
            if choice:
                used.update((seed, choice))
                group, other = source_pool[seed], source_pool[choice]
                found.append(pair("look-alike", side(group, group["names"][0]), side(other, other["names"][0]), group))
    return found


def pick_look_alike(seed, pool, index, used, rng):
    """A look-alike of seed not used yet whose name differs from the seed's and that shares no external id with it, or
    None. Two records with one id are one thing listed twice (Wikidata has two items for the same GitHub repository)."""
    if seed in used:
        return None
    key = graph.name_key(pool[seed]["names"][0])
    found = {other for look in look_alike_keys(pool[seed]) for other in index.get(look, ())}
    options = sorted(
        o
        for o in found - used - {seed}
        if graph.name_key(pool[o]["names"][0]) != key and not shares_id(pool[seed], pool[o])
    )
    return rng.choice(options) if options else None


def shares_id(group, other):
    """Whether two groups have an external id in common, which makes them the same thing."""
    return bool(id_keys(group) & id_keys(other))


def id_keys(group):
    return {(kind, graph.id_key(value)) for kind, value in group["ids"].items()}


def same_name_pairs(pool):
    """Pairs of two different entities with the same name, within one source whose records are distinct things. One
    pair per name: a third entity with the name would be correlated with the other two."""
    found = []
    for source, source_pool in by_source(pool).items():
        if source not in DISTINCT_SOURCES:
            continue
        named = defaultdict(list)
        for gold in sorted(source_pool):
            named[graph.name_key(source_pool[gold]["names"][0])].append(source_pool[gold])
        for group, other in (golds[:2] for golds in named.values() if len(golds) > 1):
            found.append(pair("same name", side(group, group["names"][0]), side(other, other["names"][0]), group))
    return found


def alias_collision_pairs(pool):
    """Pairs of an entity with aliases and a different entity named like one of them, within one source whose records
    are distinct things. Each entity is in at most one pair: many people named 'Jie Li' collide with the one 'Jie S.
    Li' who also published as 'Jie Li', and pairs sharing him would not be independent."""
    found = []
    for source, source_pool in by_source(pool).items():
        if source not in DISTINCT_SOURCES:
            continue
        holders = defaultdict(list)
        for gold in sorted(source_pool):
            for alias in source_pool[gold]["names"][1:]:
                holders[graph.name_key(alias)].append(source_pool[gold])
        used: set = set()
        for gold in sorted(source_pool):
            found += collision(source_pool[gold], holders, used)
    return found


def collision(other, holders, used):
    """[the pair of other and the first unused entity holding its name as an alias], or [] if there is none. Marks
    both entities of a pair as used."""
    name = other["names"][0]
    key = graph.name_key(name)
    for group in holders.get(key, ()) if other["gold"] not in used else ():
        if group["gold"] not in used | {other["gold"]} and graph.name_key(group["names"][0]) != key:
            used.update((group["gold"], other["gold"]))
            existing = side(group, group["names"][0], group["names"][1:])
            return [pair("alias collision", existing, side(other, name), group)]
    return []


def messy_pairs(pool, rng, limit):
    """{change: [pairs]} of a name and the same name changed as text extracted from a PDF, one pair per entity, at
    most limit per change: entities are taken in random order, so a change that fits few names still finds them."""
    found: dict = defaultdict(list)
    order = sorted(pool)
    rng.shuffle(order)
    for gold in order:
        open_changes = [change for change in MESSES if len(found.get(change, ())) < limit]
        for row in entity_messes(pool[gold], rng, open_changes):
            found[row["messy"]].append(row)
    return found


def entity_messes(group, rng, changes):
    """The messy pairs of one entity: one of its names, changed by each of changes that fits it."""
    name = rng.choice(group["names"])
    others = [other for other in group["names"] if other != name]
    found = []
    for change in changes:
        changed = MESSES[change](name, rng, others)
        if changed:
            found.append(pair("messy", side(group, name), side(group, changed), group, messy=change))
    return found


def candidates(pools, rng, scale):
    """{stratum: {type: [pairs]}}, the pairs that could be chosen. A stratum is a kind, or a messy change."""
    found: dict = defaultdict(lambda: defaultdict(list))
    for entity_type, pool in pools.items():
        for kind, pairs in name_pairs(pool, rng).items():
            found[kind][entity_type] = pairs
        found["look-alike"][entity_type] = look_alike_pairs(pool, rng)
        found["same name"][entity_type] = same_name_pairs(pool)
        found["alias collision"][entity_type] = alias_collision_pairs(pool)
        for change, pairs in messy_pairs(pool, rng, target("messy", scale)).items():
            found[f"messy: {change}"][entity_type] = pairs
    return found


def balanced(by_type, total, rng):
    """Up to total pairs, the types taking turns: a type with few pairs gives all of them, the others share the
    rest."""
    queues = {entity_type: rng.sample(pairs, len(pairs)) for entity_type, pairs in sorted(by_type.items())}
    chosen: list = []
    while len(chosen) < total and any(queues.values()):
        for queue in queues.values():
            if queue and len(chosen) < total:
                chosen.append(queue.pop())
    return chosen


def target(stratum, scale):
    """Pairs of a stratum for both splits together."""
    per_split = MESSY_PER_KIND if stratum.startswith("messy") else TARGETS[stratum]
    return round(2 * per_split * scale)


def choose(pools, rng, scale=1.0):
    """The chosen pairs of every stratum, for both splits together."""
    found = candidates(pools, rng, scale)
    return [row for stratum in sorted(found) for row in balanced(found[stratum], target(stratum, scale), rng)]


# Splitting


def components(rows):
    """Lists of the rows that share an entity, directly or through other rows: they must go to one split."""
    parent: dict = {}

    def root(gold):
        while parent.setdefault(gold, gold) != gold:
            gold = parent[gold]
        return gold

    for row in rows:
        parent[root(row["new"]["gold"])] = root(row["existing"]["gold"])
    grouped = defaultdict(list)
    for row in rows:
        grouped[root(row["existing"]["gold"])].append(row)
    return [grouped[key] for key in sorted(grouped)]


def stratum_of(row):
    return f"messy: {row['messy']}" if row["kind"] == "messy" else row["kind"]


def assign_splits(rows, rng):
    """Set each row's split. A component goes to the split where its strata have fewer rows so far, so every stratum,
    even one of a handful of pairs, is shared about evenly."""
    counts: dict = {split: Counter() for split in SPLITS}
    groups = components(rows)
    rng.shuffle(groups)
    for group in groups:
        strata = Counter(stratum_of(row) for row in group)
        split = min(SPLITS, key=lambda name: sum(counts[name][key] for key in strata))
        counts[split].update(strata)
        for row in group:
            row["split"] = split
    return rows


# Messy names


def mess_case(name, rng, others):
    return name.swapcase().replace(" ", "  ", 1) if name.strip() else None


def mess_dash(name, rng, others):
    return name.replace("-", "–") if "-" in name else None


def mess_decomposed(name, rng, others):
    changed = unicodedata.normalize("NFD", name)
    return changed if changed != name else None


def mess_citation(name, rng, others):
    return f"{name} [{rng.randint(1, 60)}]"


def mess_line_break(name, rng, others):
    return line_break(name)


def mess_punctuation(name, rng, others):
    return f"{name}."


LIGATURES = (("ffi", "ﬃ"), ("ffl", "ﬄ"), ("ff", "ﬀ"), ("fi", "ﬁ"), ("fl", "ﬂ"))


def mess_ligature(name, rng, others):
    """Letters a PDF set as one ligature glyph: 'fine-tuning' as 'ﬁne-tuning'."""
    found = next(((plain, glyph) for plain, glyph in LIGATURES if plain in name), None)
    return name.replace(found[0], found[1], 1) if found else None


def mess_footnote(name, rng, others):
    """A footnote or affiliation mark: 'GPT-4*', 'Lei Li¹'."""
    return name + rng.choice(("*", "†", "‡", "¹", "²", "³"))


def mess_possessive(name, rng, others):
    return name + rng.choice(("'s", "’s"))


def mess_quotes(name, rng, others):
    left, right = rng.choice((("“", "”"), ("‘", "’"), ('"', '"')))
    return f"{left}{name}{right}"


def mess_invisible(name, rng, others):
    """A soft hyphen or zero-width space left inside a word by PDF extraction: 'Adap\\u00adtation'."""
    words = name.split(" ")
    longest = max(range(len(words)), key=lambda index: len(words[index]))
    word = words[longest]
    if len(word) < 4:
        return None
    words[longest] = word[: len(word) // 2] + rng.choice(("­", "​")) + word[len(word) // 2 :]
    return " ".join(words)


def mess_parenthetical(name, rng, others):
    """The name with another of its names in brackets, as papers introduce an abbreviation: 'Deep Graph Infomax
    (DGI)'. Only when the shorter of the two is one word, so that people's names don't get it."""
    short = [other for other in others if " " not in min(name, other, key=len).strip()]
    return f"{name} ({rng.choice(short)})" if short else None


# The changes of SPEC.md section 3. Each takes the name, the random source, and the entity's other names, and returns
# the changed name, or None if it doesn't apply.
MESSES = {
    "case": mess_case,
    "dash": mess_dash,
    "decomposed": mess_decomposed,
    "citation": mess_citation,
    "line-break": mess_line_break,
    "punctuation": mess_punctuation,
    "ligature": mess_ligature,
    "footnote": mess_footnote,
    "possessive": mess_possessive,
    "quotes": mess_quotes,
    "invisible": mess_invisible,
    "parenthetical": mess_parenthetical,
}


def line_break(name):
    """A long word split as at the end of a line: 'Adaptation' as 'Adap- tation'."""
    words = name.split(" ")
    for index, word in enumerate(words):
        if len(word) >= 8 and word.isalpha():
            words[index] = f"{word[: len(word) // 2]}- {word[len(word) // 2 :]}"
            return " ".join(words)
    return None


# Writing


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def counts(rows):
    """{split: {stratum: {type: pairs}}}."""
    found: dict = {split: defaultdict(Counter) for split in SPLITS}
    for row in rows:
        found[row["split"]][stratum_of(row)][row["type"]] += 1
    return {split: {key: dict(value) for key, value in sorted(strata.items())} for split, strata in found.items()}


def pool_sizes(pools):
    """{type: {source: entities, "several names": share}}: the share with more than one name, to read rates by."""
    found = {}
    for entity_type, pool in sorted(pools.items()):
        sizes = Counter(group["source"] for group in pool.values())
        several = sum(len(group["names"]) > 1 for group in pool.values()) / max(1, len(pool))
        found[entity_type] = {**dict(sorted(sizes.items())), "several names": round(several, 3)}
    return found


def snapshot(cache):
    """{file: first 16 hex digits of its SHA-256} for every file in the cache, which holds the source responses the
    pairs were built from. Delete the cache to download the sources again."""
    files = sorted(Path(cache).glob("*")) if Path(cache).is_dir() else []
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:16] for path in files if path.is_file()}


def manifest(args, rows, pools, audit_report):
    return {
        "built": datetime.date.today().isoformat(),
        "seed": args.seed,
        "scale": args.scale,
        "pairs": {split: sum(row["split"] == split for row in rows) for split in SPLITS},
        "pairs by stratum and type": counts(rows),
        "pool": pool_sizes(pools),
        "parameters": {
            "targets per split": TARGETS,
            "messy per change and split": MESSY_PER_KIND,
            "similar ratio": SIMILAR_RATIO,
            "distinct sources": sorted(DISTINCT_SOURCES),
            "hub pages": HUB_PAGES,
            "dblp slices": list(DBLP_SLICES),
        },
        "licences": LICENCES,
        "queries": {"authors": AUTHORS, "homonyms": HOMONYMS, "items": ITEMS, "hub": HUB},
        "second names by the audit": {
            "model": audit_labels.MODEL,
            "removed when P(same thing) is at most": audit_labels.MAX_SAME,
            "by source and type": audit_report,
            "spent, by snapshot": audit_labels.report(Path(args.out) / "audit.jsonl"),
        },
        "label check by hand": "not done yet",
        "sources snapshot": snapshot(args.cache),
        "reproducible": "from the snapshot: with the same cache and seed the builder gives the same pairs. The sources "
        "change, so without the cache it does not. The pairs are frozen",
    }


def build(args, pools, audit_report):
    rng = random.Random(args.seed)
    rows = assign_splits(choose(pools, rng, args.scale), rng)
    rows.sort(key=lambda row: (row["split"], stratum_of(row), row["type"], row["existing"]["gold"], row["new"]["name"]))
    out = Path(args.out)
    write_jsonl(out / "pairs.jsonl", rows)
    summary = manifest(args, rows, pools, audit_report)
    summary["pairs file sha256"] = hashlib.sha256((out / "pairs.jsonl").read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"pairs": summary["pairs"]}))
    return summary


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scale", type=float, default=1.0, help="multiplies every target (default %(default)s)")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--cache",
        default=str(HERE / ".cache" / "sources"),
        help="where source responses are kept: the snapshot a rebuild reads",
    )
    parser.add_argument("--out", default=str(HERE / "data"))
    parser.add_argument("--audit", action="store_true", help="ask Jev about second names not yet in audit.jsonl")
    parser.add_argument(
        "--audit-budget",
        type=float,
        default=audit_labels.MAX_COST,
        help="USD at which --audit stops asking (default %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    pools = fetch_groups(args.cache)
    build(args, pools, audit(args, pools))
    return 0


if __name__ == "__main__":
    sys.exit(main())
