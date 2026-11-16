#!/usr/bin/env python3
"""Write a Markdown report of the code's complexity, for the CI job summary. Standard library only.

CI already fails on a function over the limits. This shows the numbers: how many functions there are, the mean and
the highest of each measure, and the functions closest to the limits, so a creeping one is seen before it fails.

It reads the JSON that three tools write, so it adds no dependency:

- ruff's C901 check with the limit set to 0, which reports the cyclomatic complexity of every Python function,
- complexipy, which reports the cognitive complexity of every Python function,
- ESLint with both limits set to 0, which reports both measures for every JavaScript function. ESLint leaves out a
  function whose cognitive complexity is 0, so that is what a missing one counts as.

Functions that share a name in one Python file, such as a helper method in several test classes, are counted once,
with the highest score of each measure: ruff gives the bare name and complexipy gives `Class::name`, so they can only
be matched on the bare name.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

RUFF_MESSAGE = re.compile(r"`(?P<name>[^`]+)` is too complex \((?P<score>\d+) > \d+\)")
ESLINT_CYCLOMATIC = re.compile(r"^(?P<kind>.*?) has a complexity of (?P<score>\d+)\.")
ESLINT_COGNITIVE = re.compile(r"Cognitive Complexity from (?P<score>\d+) to")
SHOWN = 10  # the functions listed as closest to the limits, for each language


def relative(path, root):
    """A path as the report shows it: relative to root when it is inside it, with forward slashes.

    Windows tools may give a long-path form such as `\\\\?\\F:\\...`, which is the same file.
    """
    path = Path(re.sub(r"^[\\/]{2}\?[\\/]", "", str(path)))
    if path.is_absolute():
        with contextlib.suppress(ValueError):  # outside root: shown whole
            path = path.resolve().relative_to(root.resolve())
    return path.as_posix().replace("\\", "/")


def keep_highest(table, key, measure, score):
    entry = table.setdefault(key, {"cyclomatic": 0, "cognitive": 0})
    entry[measure] = max(entry[measure], score)


def python_scores(ruff, complexipy, root):
    """{(file, function): {"cyclomatic": n, "cognitive": n}} for every Python function."""
    table: dict[tuple[str, str], dict[str, int]] = {}
    for finding in ruff:
        found = RUFF_MESSAGE.fullmatch(finding.get("message", ""))
        if finding.get("code") == "C901" and found:
            key = (relative(finding["filename"], root), found["name"])
            keep_highest(table, key, "cyclomatic", int(found["score"]))
    for function in complexipy:
        key = (relative(function["path"], root), function["function_name"].split("::")[-1])
        keep_highest(table, key, "cognitive", int(function["complexity"]))
    return table


def eslint_name(kind, line):
    """A JavaScript function's name for the report: its quoted name, or what it is and its line for an arrow."""
    named = re.search(r"'([^']+)'", kind)
    return f"{named[1]} (line {line})" if named else f"{kind.lower()} (line {line})"


def matches(messages, rule, pattern):
    """{line: match} for each of ESLint's messages from rule that pattern finds."""
    found = {}
    for message in messages:
        hit = pattern.search(message.get("message", ""))
        if message.get("ruleId") == rule and hit:
            found[message["line"]] = hit
    return found


def javascript_scores(eslint, root):
    """{(file, function): {"cyclomatic": n, "cognitive": n}} for every JavaScript function, keyed by its line."""
    table: dict[tuple[str, str], dict[str, int]] = {}
    for report in eslint:
        path = relative(report["filePath"], root)
        names = {}
        for line, hit in matches(report["messages"], "complexity", ESLINT_CYCLOMATIC).items():
            names[line] = eslint_name(hit["kind"], line)
            keep_highest(table, (path, names[line]), "cyclomatic", int(hit["score"]))
        for line, hit in matches(report["messages"], "sonarjs/cognitive-complexity", ESLINT_COGNITIVE).items():
            keep_highest(table, (path, names.get(line, f"function (line {line})")), "cognitive", int(hit["score"]))
    return table


def cell(text):
    """Text for a Markdown table cell in backticks: a pipe would end the cell, and a backtick the code span."""
    return "`" + text.replace("|", "\\|").replace("`", "'") + "`"


def closeness(entry, limits):
    """How close a function is to the limits: its higher share of either one."""
    return max(entry["cyclomatic"] / limits["cyclomatic"], entry["cognitive"] / limits["cognitive"])


def summary_row(language, table, limits):
    if not table:
        return f"| {language} | 0 | - | - | 0 |"
    count = len(table)
    cells = []
    for measure in ("cyclomatic", "cognitive"):
        scores = [entry[measure] for entry in table.values()]
        cells.append(f"{sum(scores) / count:.1f} / {max(scores)}")
    at_limit = sum(1 for entry in table.values() if closeness(entry, limits) >= 1)
    return f"| {language} | {count} | {cells[0]} | {cells[1]} | {at_limit} |"


def closest(language, table, limits):
    """The Markdown rows of the functions closest to the limits, highest first, then by file and name."""
    ranked = sorted(table.items(), key=lambda item: (-closeness(item[1], limits), item[0]))
    return [
        f"| {language} | {cell(name)} | {cell(path)} | {entry['cyclomatic']} | {entry['cognitive']} |"
        for (path, name), entry in ranked[:SHOWN]
    ]


def report(tables, limits):
    """The whole report, as Markdown lines."""
    lines = [
        "## Complexity",
        "",
        f"Limits: cyclomatic {limits['cyclomatic']}, cognitive {limits['cognitive']}. CI fails on a function over"
        " either one.",
        "",
        "| Language | Functions | Cyclomatic mean / max | Cognitive mean / max | At a limit |",
        "|---|---|---|---|---|",
        *(summary_row(language, table, limits) for language, table in tables.items()),
        "",
        f"### Closest to the limits (top {SHOWN} for each language)",
        "",
        "| Language | Function | File | Cyclomatic | Cognitive |",
        "|---|---|---|---|---|",
    ]
    for language, table in tables.items():
        lines += closest(language, table, limits)
    return lines


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise SystemExit(f"error: can't read {path}: {err}") from err


def positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("a limit must be 1 or more")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description="Write a Markdown complexity report from ruff, complexipy, ESLint.")
    parser.add_argument("--ruff", required=True, help="ruff's JSON output for C901 with the limit set to 0")
    parser.add_argument("--complexipy", required=True, help="complexipy's JSON output")
    parser.add_argument("--eslint", required=True, help="ESLint's JSON output with both limits set to 0")
    parser.add_argument("--cyclomatic-limit", type=positive, required=True)
    parser.add_argument("--cognitive-limit", type=positive, required=True)
    parser.add_argument("--root", type=Path, default=Path("."), help="the folder paths are shown relative to")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    limits = {"cyclomatic": args.cyclomatic_limit, "cognitive": args.cognitive_limit}
    tables = {
        "Python": python_scores(load(args.ruff), load(args.complexipy), args.root),
        "JavaScript": javascript_scores(load(args.eslint), args.root),
    }
    print("\n".join(report(tables, limits)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
