#!/usr/bin/env python3
"""Write the JSON files that shields.io reads to draw the coverage and scenario badges. Standard library only.

Usage: python tools/badges.py --coverage cov/*.json --junit junit --out badges

--coverage takes the files that `coverage json` wrote, one per script, and --junit the folder that behave wrote
with `--junit`. Each badge is a small JSON file in shields.io's endpoint format, so the README can show a number
that CI measured on the last run of main, without a service holding the data.
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def coverage_counts(reports):
    """How many lines and branches the coverage files hold, and how many of them the tests ran."""
    covered = total = 0
    for report in reports:
        totals = json.loads(Path(report).read_text(encoding="utf-8"))["totals"]
        covered += totals["covered_lines"] + totals.get("covered_branches", 0)
        total += totals["num_statements"] + totals.get("num_branches", 0)
    return covered, total


def percent_text(covered, total):
    """The share covered, rounded down so that anything short of 100% never reads as 100%."""
    tenths = covered * 1000 // total
    return f"{tenths // 10}%" if tenths % 10 == 0 else f"{tenths / 10}%"


def coverage_badge(reports):
    covered, total = coverage_counts(reports)
    if not total:
        raise SystemExit("the coverage files hold no lines")
    color = "brightgreen" if covered == total else "yellow" if covered * 100 >= total * 90 else "red"
    return {"schemaVersion": 1, "label": "unit coverage", "message": percent_text(covered, total), "color": color}


def scenario_counts(folder):
    """The scenarios that ran and how many passed, from the JUnit files behave wrote, leaving out any skipped."""
    ran = passed = 0
    for report in sorted(Path(folder).glob("*.xml")):
        suite = ET.parse(report).getroot()
        count = int(suite.get("tests", 0)) - int(suite.get("skipped", 0))
        bad = sum(int(suite.get(name, 0)) for name in ("failures", "errors"))
        ran += count
        passed += count - bad
    return ran, passed


def scenario_badge(folder):
    ran, passed = scenario_counts(folder)
    if not ran:
        raise SystemExit("the JUnit folder holds no scenarios")
    ok = passed == ran
    message = f"{passed} passing" if ok else f"{passed} of {ran} passing"
    return {"schemaVersion": 1, "label": "scenarios", "message": message, "color": "brightgreen" if ok else "red"}


def mutation_badge(results):
    """The survivors of the last mutation run of every module, with the date of the oldest run."""
    found = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(Path(results).glob("*.json"))]
    if not found:
        raise SystemExit("the mutation results folder holds no results")
    survivors = sum(result["survivors"] for result in found)
    oldest = min(result["date"] for result in found)
    word = "survivor" if survivors == 1 else "survivors"
    modules = "module" if len(found) == 1 else "modules"
    message = f"{survivors} {word}, {len(found)} {modules}, {oldest}"
    return {"schemaVersion": 1, "label": "mutation", "message": message, "color": "red" if survivors else "brightgreen"}


def main(argv):
    parser = argparse.ArgumentParser(description="Write the coverage and scenario badges for shields.io.")
    parser.add_argument("--coverage", nargs="+", required=True, help="coverage json files, one per script")
    parser.add_argument("--junit", required=True, help="the folder behave wrote its JUnit files to")
    parser.add_argument("--out", required=True, help="the folder to write the badge files to")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    badges = {"coverage.json": coverage_badge(args.coverage), "scenarios.json": scenario_badge(args.junit)}
    for name, badge in badges.items():
        (out / name).write_text(json.dumps(badge) + "\n", encoding="utf-8")
        print(f"{name}: {badge['label']} {badge['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
