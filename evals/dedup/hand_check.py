"""The hand check of the pairs' labels, as SPEC.md section 3 describes: a blind sheet of 200 name pairs for a person to
judge, and a scorer for the filled sheet. Nothing here calls a model.

  python evals/dedup/hand_check.py make [--seed N]   writes hand-check.csv (to fill in) and .cache/hand-check-key.csv
  python evals/dedup/hand_check.py score [SHEET]     reads the filled sheet and prints the label error rates

The sheet has two parts. 100 second names are drawn from Jev's answers (data/audit.jsonl), 20 in each band of the
probability it gave to "same thing". The names Jev rejected (at most MAX_SAME) are in the sheet too, so that the scorer
can tell whether the threshold removes the right ones. 100 pairs are drawn from data/pairs.jsonl, 25 in each of the
four kinds whose label a person can judge from the names: similar name, dissimilar name, known alias, and look-alike.
Same-name and alias-collision pairs are left out: two people called `Jing Chen` can't be told apart by reading.

The sheet shows only the type and the two names. Not the first name's aliases, which would give known-alias pairs away
(the second name is one of them), and not the label, the kind, or Jev's answer, which stay in the key file, so
that the person judging is not led by them. They write `same` or `different` in `your_verdict`, or `unsure`.

`claude_verdict` may hold Claude's answer, filled in before the person reads the sheet; the person then writes
`your_verdict` only where they disagree, or `ok` to agree. The person's answer wins where there is one. The scorer
says how many rows rest on Claude's answer alone, since those measure Claude's agreement with the labels, not a
person's.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import audit_labels
import evaluate

HERE = Path(__file__).resolve().parent
SHEET = HERE / "hand-check.csv"
KEY = HERE / ".cache" / "hand-check-key.csv"
SEED = 20261110
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
PER_BAND = 20
JUDGED_KINDS = ("similar name", "dissimilar name", "known alias", "look-alike")
PER_KIND = 25
VERDICTS = ("same", "different", "unsure")
AGREE = "ok"  # in your_verdict: the person agrees with claude_verdict
MOSTLY_DIFFERENT = 0.10  # the removed names may be the same thing this often, for the threshold to be right
SHEET_FIELDS = ["id", "type", "first_name", "second_name", "claude_verdict", "your_verdict", "notes"]
KEY_FIELDS = ["id", "part", "kind", "label", "jev_same", "band"]


def band_of(probability):
    """The index of the band of BANDS that holds probability."""
    return next(index for index, (low, high) in enumerate(BANDS) if low <= probability < high)


def draw_audit(answers, rng):
    """PER_BAND answers of Jev's from each band, fewer if a band holds fewer."""
    bands = defaultdict(list)
    for key in sorted(answers):
        bands[band_of(answers[key]["probabilities"].get(audit_labels.SAME, 0.0))].append(answers[key])
    return [row for index in sorted(bands) for row in rng.sample(bands[index], min(PER_BAND, len(bands[index])))]


def draw_pairs(pairs, rng):
    """PER_KIND pairs from each judged kind, fewer if a kind holds fewer. Each pair is in the sheet once."""
    kinds = defaultdict(list)
    for pair in pairs:
        if pair["kind"] in JUDGED_KINDS:
            kinds[pair["kind"]].append(pair)
    return [row for kind in JUDGED_KINDS for row in rng.sample(kinds[kind], min(PER_KIND, len(kinds[kind])))]


def audit_entry(row, number):
    """(sheet row, key row) for one answer of Jev's."""
    same = row["probabilities"].get(audit_labels.SAME, 0.0)
    sheet = {
        "id": number,
        "type": row["type"],
        "first_name": row["first"],
        "second_name": row["second"],
    }
    return sheet, {"id": number, "part": "audit", "kind": "", "label": "", "jev_same": same, "band": band_of(same)}


def pair_entry(pair, number, answers):
    """(sheet row, key row) for one pair. Jev's answer is looked up when the second name was one he judged."""
    existing, new = pair["existing"], pair["new"]
    sheet = {
        "id": number,
        "type": pair["type"],
        "first_name": existing["name"],
        "second_name": new["name"],
    }
    answer = answers.get((pair["type"], existing["name"], new["name"]))
    same = answer["probabilities"].get(audit_labels.SAME, "") if answer else ""
    return sheet, {
        "id": number,
        "part": "pair",
        "kind": pair["kind"],
        "label": pair["label"],
        "jev_same": same,
        "band": "",
    }


def make_entries(answers, pairs, rng):
    """[(sheet row, key row)] for the whole sheet, in a random order so that the order tells nothing."""
    drawn = draw_audit(answers, rng)
    taken = {(row["type"], row["first"], row["second"]) for row in drawn}  # a name pair is judged once
    fresh = [pair for pair in pairs if (pair["type"], pair["existing"]["name"], pair["new"]["name"]) not in taken]
    entries = [audit_entry(row, 0) for row in drawn]
    entries += [pair_entry(pair, 0, answers) for pair in draw_pairs(fresh, rng)]
    rng.shuffle(entries)
    for number, (sheet, key) in enumerate(entries, start=1):
        sheet["id"] = key["id"] = number
    return entries


def write_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:  # the BOM makes Excel read it as UTF-8
        writer = csv.DictWriter(handle, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def make(seed, sheet=SHEET, key=KEY, audit=HERE / "data" / "audit.jsonl", pairs=evaluate.PAIRS):
    """Write the sheet and its key, and return the number of rows."""
    answers = audit_labels.load(audit)
    entries = make_entries(answers, evaluate.load_pairs(pairs), random.Random(seed))
    write_csv(sheet, SHEET_FIELDS, [sheet_row for sheet_row, _ in entries])
    write_csv(key, KEY_FIELDS, [key_row for _, key_row in entries])
    return len(entries)


def verdict_in(row, column, allowed=VERDICTS):
    """The verdict in one column of a sheet row, in lower case, or "". A verdict that is not allowed is an error: a
    typo would silently count as nothing."""
    verdict = (row.get(column) or "").strip().lower()
    if verdict and verdict not in allowed:
        raise ValueError(f"row {row['id']}: {column} must be one of {', '.join(allowed)}, not {verdict!r}")
    return verdict


def row_verdict(row):
    """(verdict, who decided it) for one sheet row, or ("", None) if it has none. The person's verdict wins over
    Claude's, and `ok` takes Claude's."""
    claude, person = verdict_in(row, "claude_verdict"), verdict_in(row, "your_verdict", (*VERDICTS, AGREE))
    if person == AGREE and not claude:
        raise ValueError(f"row {row['id']}: your_verdict is {AGREE!r}, but there is no claude_verdict")
    if person == AGREE:
        return claude, "person"
    if person:
        return person, "person, overriding Claude" if claude and claude != person else "person"
    return claude, "Claude only" if claude else None


def judged(sheet, key):
    """([(key row, verdict)], {who: rows}) for the sheet rows that have a verdict; who counts the rows decided by the
    person agreeing with Claude or alone, by the person overriding Claude, and by Claude alone."""
    keys = {row["id"]: row for row in read_csv(key)}
    found, who = [], {"person": 0, "person, overriding Claude": 0, "Claude only": 0}
    for row in read_csv(sheet):
        verdict, decided_by = row_verdict(row)
        if decided_by:
            who[decided_by] += 1
            found.append((keys[row["id"]], verdict))
    return found, who


def rate(bad, total):
    """{bad, total, rate, interval}, the interval from evaluate.wilson; rate and interval are None for no rows."""
    return {"bad": bad, "total": total, "rate": bad / total if total else None, "interval": evaluate.wilson(bad, total)}


def band_table(found):
    """{band label: how many were judged the same thing by hand, of those judged same or different} for Jev's answers.
    A name judged unsure counts for neither."""
    counts: dict = defaultdict(lambda: [0, 0])
    for key, verdict in found:
        if key["part"] == "audit" and verdict != "unsure":
            counts[int(key["band"])][0] += verdict == "same"
            counts[int(key["band"])][1] += 1
    return {
        f"{BANDS[index][0]:.1f}-{min(BANDS[index][1], 1.0):.1f}": {**rate(*counts[index]), "upper": BANDS[index][1]}
        for index in sorted(counts)
    }


def label_errors(found):
    """{kind: the pairs the person judged differently from the label, of those judged same or different}."""
    counts: dict = defaultdict(lambda: [0, 0])
    for key, verdict in found:
        if key["part"] == "pair" and verdict != "unsure":
            counts[key["kind"]][0] += verdict != key["label"]
            counts[key["kind"]][1] += 1
    return {kind: rate(*counts[kind]) for kind in sorted(counts)}


def suggest(bands):
    """The highest MAX_SAME, at a band's upper edge, at which the names Jev would remove (every band at or below it)
    were judged the same thing by hand at most MOSTLY_DIFFERENT of the time. None if even the lowest band exceeds it."""
    best, same, total = None, 0, 0
    for found in bands.values():
        same, total = same + found["bad"], total + found["total"]
        if total and same / total <= MOSTLY_DIFFERENT:
            best = found["upper"]
    return best


def score(sheet, key):
    """The error rates in a filled sheet: how often the same thing was judged by hand for each band of Jev's answers,
    how often the pairs' labels disagree with the person by kind, how many were unsure, and the MAX_SAME to use."""
    found, who = judged(sheet, key)
    bands = band_table(found)
    return {
        "judged": len(found),
        "decided by": who,
        "unsure": sum(verdict == "unsure" for _, verdict in found),
        "same thing by hand, by band of Jev's P(same thing)": bands,
        "label disagrees with the person, by kind": label_errors(found),
        "suggested MAX_SAME": suggest(bands),
        "MAX_SAME now": audit_labels.MAX_SAME,
    }


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["make"]:
        seed = int(args[args.index("--seed") + 1]) if "--seed" in args else SEED
        print(f"wrote {make(seed)} rows to {SHEET} and the key to {KEY}")
        return 0
    if args[:1] == ["score"]:
        print(json.dumps(score(args[1] if len(args) > 1 else SHEET, KEY), indent=1, ensure_ascii=False))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
