"""Ask a decision model whether a second name is the same thing as the first, for the dataset builder.

Wikidata and Papers with Code give some entities second names that are not names of the same thing: a version
(`o1-preview` for `OpenAI o1`), a paper title, a description. This asks Jev, TypeSafe's decision model, one Choice
question per pair through OpenRouter's Decisions API, and keeps every answer in a file the builder reads. Run by hand
through `build_dataset.py --audit`, never in CI: only pairs missing from the file are asked, and a rebuild without
`--audit` only reads it. Needs OPENROUTER_API_KEY in the environment; the key is never printed or written.

Every row keeps the tokens and the cost the service reports, so `python audit_labels.py [FILE]` totals what has been
spent, by model snapshot, and a run stops asking once it has spent MAX_COST.

Jev answers with the chosen option and a probability for each, and no explanation. The criteria below are the
labelling policy: a rename or another spelling is the same thing, a version, fork, or part is not.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.14"  # pinned: probabilities shift between versions
USER_AGENT = "paper-research-eval/0.1 (https://github.com/marfago-labs/paper-research)"
RETRIES = 4
WORKERS = 8
CHUNK = 64  # pairs asked between two checks of what has been spent
MAX_COST = 1.0  # USD: a run stops asking once it has spent this much, and says how many pairs it left
# A second name is dropped when Jev puts at most this much probability on 'same thing': it is confident that it is not.
# Provisional until a human-read sample sets it, as Jev's own documentation advises.
MAX_SAME = 0.2
SAME = "same_thing"
INSTRUCTIONS = "Is the second name another name for exactly the same thing as the first name?"
CRITERIA = {
    SAME: (
        "The second name is another name for exactly the same thing: an abbreviation or its expansion, another "
        "spelling, a former name or a rename, or a translation."
    ),
    "different_thing": (
        "The second name is a different thing: another version or release, a fork or derivative, a sub-dataset, "
        "split, task, or configuration, a part of the first or a family it belongs to, or something related."
    ),
    "not_a_name": "The second name is not a name: a paper title, a sentence or description, a list, a URL, or a path.",
}


def key_of(row):
    """What identifies a pair: the entity type and its two names."""
    return row["type"], row["first"], row["second"]


def load(path):
    """{pair: row} from the answers kept so far; empty if there is no file yet."""
    path = Path(path)
    if not path.exists():
        return {}
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {key_of(row): row for row in rows}


def request_for(entity_type, first, second, key, model):
    body = {
        "model": model,
        "state": {"entity type": entity_type, "first name": first, "second name": second},
        "questions": {"relation": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}},
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": USER_AGENT}
    return urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers=headers)


def fetch(request):
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310: a fixed https endpoint
        return json.load(response)


def post(request):
    """The decoded answer, tried again after a pause when the service is busy."""
    for attempt in range(1, RETRIES):
        try:
            return fetch(request)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(5 * attempt)
    return fetch(request)


def usage_of(result):
    """The tokens and cost the service reports for one answer; None for any it leaves out."""
    usage = result.get("usage") or {}
    return {name: usage.get(name) for name in ("input_tokens", "output_tokens", "cost")}


def decide(entity_type, first, second, key, model=MODEL):
    """One row: the pair, Jev's choice and its probabilities, which snapshot answered, and the tokens and cost."""
    result = post(request_for(entity_type, first, second, key, model))
    answer = result["answers"]["relation"]
    return {
        "type": entity_type,
        "first": first,
        "second": second,
        "verdict": answer["choice"],
        "confidence": answer["confidence"],
        "probabilities": answer["probabilities"],
        "model": result["model"],
        **usage_of(result),
    }


def rejected(row):
    """Whether Jev is confident that the second name is not the same thing. A pair never asked is not rejected."""
    return row is not None and row["probabilities"].get(SAME, 0.0) <= MAX_SAME


def attempt(pair, key, model):
    """The row for one pair, or None if the service refused it, so that one bad pair does not stop the run."""
    entity_type, first, second = pair
    try:
        return decide(entity_type, first, second, key, model)
    except (urllib.error.URLError, KeyError, ValueError) as error:
        print(f"  skipped {pair}: {error}")
        return None


def missing(pairs, known):
    """The pairs not yet in known, each once and in order."""
    return [pair for pair in dict.fromkeys(pairs) if pair not in known]


def estimate(count, known):
    """About what asking count more pairs will cost, from the mean cost of the answers kept so far; None if there are
    none to go by."""
    costs = [row["cost"] for row in known.values() if row.get("cost") is not None]
    return count * sum(costs) / len(costs) if costs else None


def record(row, handle, spent):
    """Write one answer to the file and add what it cost to spent; a pair the service refused is only counted."""
    if row is None:
        spent["skipped"] += 1
        return
    spent["asked"] += 1
    for name in ("input_tokens", "output_tokens", "cost"):
        spent[name] += row[name] or 0
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    handle.flush()


def judge(pairs, path, key, model=MODEL, workers=WORKERS, max_cost=MAX_COST):
    """Ask about every pair not already in the file at path, adding each answer to it as it arrives, until max_cost
    USD is spent. Returns the counts asked, skipped, and not asked (left for a later run), and the input and output
    tokens and the cost of this run."""
    path = Path(path)
    todo = missing(pairs, load(path))
    spent: Counter = Counter()
    path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as pool, path.open("a", encoding="utf-8") as handle:
        for start in range(0, len(todo), CHUNK):
            if spent["cost"] >= max_cost:
                break
            for row in pool.map(lambda pair: attempt(pair, key, model), todo[start : start + CHUNK]):
                record(row, handle, spent)
    spent["not asked"] = len(todo) - spent["asked"] - spent["skipped"]
    return {name: spent[name] for name in ("asked", "skipped", "not asked", "input_tokens", "output_tokens", "cost")}


def report(path):
    """Everything the file records about what was spent, by the snapshot that answered: calls, input and output
    tokens, cost, and the mean cost per call. Rows written before tokens were kept count as 'without tokens'."""
    found: dict = defaultdict(Counter)
    for row in load(path).values():
        totals = found[row["model"]]
        totals["calls"] += 1
        totals["without tokens"] += row.get("input_tokens") is None
        for name in ("input_tokens", "output_tokens", "cost"):
            totals[name] += row.get(name) or 0
    return {
        model: {**totals, "cost": round(totals["cost"], 6), "mean cost": round(totals["cost"] / totals["calls"], 8)}
        for model, totals in sorted(found.items())
    }


def api_key():
    """The key from the environment, or an explanation of what is missing."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("--audit needs OPENROUTER_API_KEY in the environment")
    return key


def main(argv=None):
    """Print what the audit file records about what was spent."""
    args = sys.argv[1:] if argv is None else argv
    path = args[0] if args else Path(__file__).resolve().parent / "data" / "audit.jsonl"
    found = report(path)
    print(json.dumps(found, indent=1) if found else f"no answers in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
