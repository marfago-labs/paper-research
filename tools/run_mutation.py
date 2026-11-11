#!/usr/bin/env python3
"""Mutation-test one module on a temporary copy of the repository, so the real files are never changed.

Usage: python tools/run_mutation.py <graph|recap|arxiv|s2|init> [--max-survival PERCENT]
Needs cosmic-ray on the PATH, for example: uvx --from cosmic-ray python tools/run_mutation.py init
Prints the surviving mutants with their diffs. Exit 0 if the survival rate is at or below the limit.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("graph", "recap", "arxiv", "s2", "init")


def run(command, cwd, check=True, capture=False):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(command, cwd=cwd, check=check, env=env, capture_output=capture, text=True)


def main(argv):
    parser = argparse.ArgumentParser(description="Mutation-test one module on a copy of the repository.")
    parser.add_argument("module", choices=MODULES)
    parser.add_argument("--max-survival", type=float, default=5.0, help="allowed survival rate in percent")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(
            ROOT,
            copy,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"),
        )
        config, session = f"mutation/{args.module}.toml", "session.sqlite"
        run(["cosmic-ray", "init", config, session], copy, capture=True)
        run(["cr-filter-pragma", session], copy, capture=True)  # skip lines marked "# pragma: no mutate"
        run(["cosmic-ray", "baseline", config], copy, capture=True)
        run(["cosmic-ray", "exec", config, session], copy, capture=True)
        report = run(["cr-report", session, "--surviving-only", "--show-diff"], copy, capture=True)
        print(report.stdout)
        rate = run(["cr-rate", session, "--fail-over", str(args.max_survival)], copy, check=False, capture=True)
        print(f"{args.module}: survival rate {rate.stdout.strip()}% (limit {args.max_survival}%)")
        return rate.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
