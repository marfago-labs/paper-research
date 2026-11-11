"""Evaluate graph.py's duplicate check on the pairs in data/pairs.jsonl, as SPEC.md section 4 describes.

Each pair is an existing entity and a new name, known to be the same thing or different things. The pair is replayed
through graph.py's check twice (with the entities' real ids, and with names only), and the outcome (refuse, ask, or
add) is counted as right or as one of three kinds of bad: a missed duplicate, a wrong merge, or a needless ask. Every
rate comes with a 95% Wilson interval and its counts, by kind and by kind and type; nothing is averaged over kinds.

  python evals/dedup/evaluate.py [--split dev|test] [--threshold T ...] [--alias-rule ask|refuse ...]
                                 [--sweep] [--limit L] [--json FILE] [--summary FILE]

With more than one setting the report also lists the pairs whose outcome changed from the first. --sweep prints the
trade between missed duplicates and needless asks at thresholds 0.30 to 0.90, and the threshold it chooses on dev.
It reports only: the decision rule is applied when a change is proposed. Exit codes: 0; 2 if the pairs are missing.
"""

from __future__ import annotations

import argparse
import contextlib
import itertools
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "skills" / "graph" / "scripts"))
import graph  # noqa: E402

PAIRS = HERE / "data" / "pairs.jsonl"
RUNS = ("ids", "names only")
Z = 1.96  # 95%
SWEEP = [round(0.30 + 0.05 * step, 2) for step in range(13)]  # 0.30 to 0.90
LIMIT = 0.05  # of similar-name pairs the chosen threshold may miss
ALIAS_RULES = ("ask", "refuse")
ALIAS = "same name as an alias"
EXAMPLES = 3  # changed pairs shown per kind and change
# What counts as bad, by the pair's label.
BAD = {"same": {"missed duplicates": "add"}, "different": {"wrong merges": "refuse", "needless asks": "ask"}}
RATES = ("missed duplicates", "wrong merges", "needless asks")


def load_pairs(path):
    """The pairs in the file, in order."""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def kind_of(pair):
    """The kind of a pair, with the change that a messy one makes."""
    return f"messy: {pair['messy']}" if pair["kind"] == "messy" else pair["kind"]


def wilson(bad, total):
    """The 95% Wilson interval for bad out of total, as (low, high); None when there are no pairs."""
    if not total:
        return None
    rate = bad / total
    centre = (rate + Z * Z / (2 * total)) / (1 + Z * Z / total)
    half = Z * math.sqrt(rate * (1 - rate) / total + Z * Z / (4 * total * total)) / (1 + Z * Z / total)
    return max(0.0, centre - half), min(1.0, centre + half)


def cell(bad, total):
    """'0.123 (0.100-0.150) 12/98', or '-' where there is nothing to count."""
    interval = wilson(bad, total)
    if interval is None:
        return "-"
    return f"{bad / total:.3f} ({interval[0]:.3f}-{interval[1]:.3f}) {bad}/{total}"


def entity(side, entity_type, entity_id, use_ids):
    """The graph entity for one side of a pair. The new side has no aliases."""
    found = {"id": f"{entity_type}:{entity_id}", "type": entity_type, "name": side["name"]}
    found["aliases"] = list(side.get("aliases", []))
    if use_ids and side.get("ids"):
        found["ids"] = dict(side["ids"])
    return found


@contextlib.contextmanager
def similarity_threshold(value):
    """graph.SIMILARITY set to value for a while: graph.py has no option for it, so the evaluation overrides it in
    its own process."""
    before = graph.SIMILARITY
    graph.SIMILARITY = value
    try:
        yield
    finally:
        graph.SIMILARITY = before


def prepare(pair, use_ids):
    """What decides a pair's outcome apart from the threshold and the alias rule, so that each pair is scored once and
    every setting is cheap. The check is made at a threshold nothing reaches, so no reason comes from similarity."""
    existing = entity(pair["existing"], pair["type"], "existing", use_ids)
    new = entity(pair["new"], pair["type"], "new", use_ids)
    with similarity_threshold(2.0):
        reasons, strong = graph.judged(existing, new)
    return {
        "strong": strong,
        "held": bool(reasons),
        "alias": ALIAS in reasons and not graph.conflicting_ids(existing, new),
        "score": graph.similarity(existing["name"], new["name"]),
    }


def outcome(prepared, threshold, alias_rule):
    """refuse, ask, or add for a prepared pair. The alias rule 'refuse' treats a name equal to an alias like an equal
    name (unless the ids conflict); the threshold decides only between ask and add."""
    if prepared["strong"] or (alias_rule == "refuse" and prepared["alias"]):
        return "refuse"
    return "ask" if prepared["held"] or prepared["score"] >= threshold else "add"


def settings_of(thresholds, rules):
    """Every (threshold, alias rule) to try, the first of each first."""
    return list(itertools.product(thresholds, rules))


def replay(pairs, settings):
    """{run: {setting: [outcome per pair]}} for every run and setting."""
    found: dict = {}
    for run in RUNS:
        prepared = [prepare(pair, run == "ids") for pair in pairs]
        found[run] = {setting: [outcome(p, *setting) for p in prepared] for setting in settings}
    return found


def tally(pairs, outcomes, group):
    """{group: Counter of (label, outcome)} where group(pair) names the row a pair belongs to."""
    found: dict = defaultdict(Counter)
    for pair, result in zip(pairs, outcomes):
        found[group(pair)][(pair["label"], result)] += 1
    return found


def rates(counts):
    """{rate: (bad, total)} for one row: each bad outcome over the pairs it can happen to."""
    totals = {label: sum(n for (name, _), n in counts.items() if name == label) for label in BAD}
    return {
        rate: (counts[(label, result)], totals[label]) for label, bad in BAD.items() for rate, result in bad.items()
    }


def table(groups, title):
    """A markdown table with one row per group and one column per rate. A rate that does not apply shows '-'."""
    lines = [f"| {title} | pairs | " + " | ".join(RATES) + " |", "|---" * (len(RATES) + 2) + "|"]
    for name, counts in sorted(groups.items()):
        found = rates(counts)
        pairs = sum(counts.values())
        lines.append(f"| {name} | {pairs} | " + " | ".join(cell(*found[rate]) for rate in RATES) + " |")
    return "\n".join(lines)


def by_kind(pairs, outcomes):
    return tally(pairs, outcomes, kind_of)


def by_kind_and_type(pairs, outcomes):
    return tally(pairs, outcomes, lambda pair: f"{kind_of(pair)} / {pair['type']}")


def setting_name(setting):
    return f"threshold {setting[0]}, alias rule {setting[1]}"


def report_run(pairs, outcomes, run, setting):
    """The two tables of one run at one setting."""
    heading = f"### {run}, {setting_name(setting)}"
    return "\n\n".join(
        [
            heading,
            table(by_kind(pairs, outcomes), "kind"),
            "By kind and type\n\n" + table(by_kind_and_type(pairs, outcomes), "kind / type"),
        ]
    )


def changed(pairs, before, after):
    """The pairs whose outcome differs: [(pair, outcome before, outcome after)]."""
    return [(pair, old, new) for pair, old, new in zip(pairs, before, after) if old != new]


def describe(pair):
    return f"{pair['existing']['name']} -> {pair['new']['name']}"


def report_changes(pairs, outcomes, run, first, other):
    """The pairs whose outcome changed from the first setting to another, by kind and direction, with a few examples.
    This list, not a single number, is what a change is judged on."""
    found = changed(pairs, outcomes[first], outcomes[other])
    groups: dict = defaultdict(list)
    for pair, old, new in found:
        groups[(kind_of(pair), pair["label"], old, new)].append(pair)
    lines = [f"### {run}: {setting_name(first)} to {setting_name(other)}: {len(found)} pairs changed", ""]
    if not found:
        return "\n".join(lines + ["None."])
    lines += ["| kind | label | from | to | pairs | examples |", "|---|---|---|---|---|---|"]
    for (kind, label, old, new), group in sorted(groups.items()):
        shown = "; ".join(describe(pair) for pair in group[:EXAMPLES])
        lines.append(f"| {kind} | {label} | {old} | {new} | {len(group)} | {shown} |")
    return "\n".join(lines)


def curve(pairs, prepared):
    """[{threshold, missed: (bad, total) over similar-name pairs, needless: (bad, total) over look-alike pairs}] for
    every threshold of the sweep, from pairs prepared once. The alias rule does not matter here: it never turns an ask
    into an add."""
    similar = [p for pair, p in zip(pairs, prepared) if pair["kind"] == "similar name"]
    lookalike = [p for pair, p in zip(pairs, prepared) if pair["kind"] == "look-alike"]
    return [
        {
            "threshold": value,
            "missed": (sum(outcome(p, value, "ask") == "add" for p in similar), len(similar)),
            "needless": (sum(outcome(p, value, "ask") == "ask" for p in lookalike), len(lookalike)),
        }
        for value in SWEEP
    ]


def choose(points, limit):
    """The highest threshold whose missed-duplicate rate on similar-name pairs is at most limit: the fewest needless
    asks that still find nearly every similar spelling. None if no threshold keeps the rate that low."""
    fitting = [
        point["threshold"]
        for point in points
        if point["missed"][1] and point["missed"][0] / point["missed"][1] <= limit
    ]
    return max(fitting) if fitting else None


def report_sweep(points, split, chosen):
    lines = [
        f"### Threshold sweep, {split}, names only",
        "",
        "| threshold | missed duplicates, similar name | needless asks, look-alike |",
        "|---|---|---|",
    ]
    for point in points:
        mark = " (chosen on dev)" if point["threshold"] == chosen else ""
        lines.append(f"| {point['threshold']:.2f}{mark} | {cell(*point['missed'])} | {cell(*point['needless'])} |")
    return "\n".join(lines)


def sweep_report(by_split, limit):
    """The sweep on dev and on test, and the threshold chosen on dev. Names only, since ids refuse more and so never
    lower the missed-duplicate rate of a similar spelling."""
    points = {}
    for split, pairs in by_split.items():
        points[split] = curve(pairs, [prepare(pair, False) for pair in pairs])
    chosen = choose(points["dev"], limit) if "dev" in points else None
    text = "\n\n".join(report_sweep(points[split], split, chosen) for split in sorted(points))
    verdict = (
        f"Chosen on dev: the highest threshold with at most {limit:.0%} missed duplicates on similar-name pairs is "
        + ("none of them." if chosen is None else f"{chosen:.2f}.")
    )
    return text + "\n\n" + verdict, {"chosen on dev": chosen, "limit": limit, "points": points}


def figures(pairs, outcomes):
    """{kind: {rate: [bad, total]}} for one run at one setting, for the JSON file."""
    return {
        kind: {rate: list(found) for rate, found in rates(counts).items()}
        for kind, counts in by_kind(pairs, outcomes).items()
    }


def report_one_run(pairs, results, run, settings):
    """(markdown parts, figures by setting) for one run: its tables at every setting, then what changed from the first
    setting to each other one."""
    parts: list = []
    data = {}
    for setting in settings:
        parts += ["", report_run(pairs, results[setting], run, setting)]
        data[f"{run}, {setting_name(setting)}"] = figures(pairs, results[setting])
    for other in settings[1:]:
        parts += ["", report_changes(pairs, results, run, settings[0], other)]
    return parts, data


def build_report(pairs, settings, split):
    """(markdown, data) for the split's pairs at every setting."""
    results = replay(pairs, settings)
    parts = [f"## Duplicate detection, {split} split", "", f"{len(pairs)} pairs."]
    data: dict = {"split": split, "pairs": len(pairs), "settings": {}}
    for run in RUNS:
        run_parts, run_data = report_one_run(pairs, results[run], run, settings)
        parts += run_parts
        data["settings"].update(run_data)
    return "\n".join(parts), data


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pairs", default=str(PAIRS), help="the pairs file (default %(default)s)")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--threshold", type=float, nargs="+", help="similarity threshold(s), default graph.SIMILARITY")
    parser.add_argument(
        "--alias-rule", choices=ALIAS_RULES, nargs="+", default=["ask"], help="what a name equal to an alias does"
    )
    parser.add_argument("--sweep", action="store_true", help="the curve of missed duplicates and needless asks")
    parser.add_argument(
        "--limit", type=float, default=LIMIT, help="missed duplicates allowed when choosing (default %(default)s)"
    )
    parser.add_argument("--json", help="write the figures to this file")
    parser.add_argument("--summary", help="append the report to this file, such as $GITHUB_STEP_SUMMARY")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not Path(args.pairs).exists():
        print(f"no pairs at {args.pairs}", file=sys.stderr)
        return 2
    every = load_pairs(args.pairs)
    by_split = {split: [pair for pair in every if pair["split"] == split] for split in ("dev", "test")}
    settings = settings_of(args.threshold or [graph.SIMILARITY], args.alias_rule)
    text, data = build_report(by_split[args.split], settings, args.split)
    if args.sweep:
        more, data["sweep"] = sweep_report(by_split, args.limit)
        text += "\n\n" + more
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    if args.json:
        Path(args.json).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
