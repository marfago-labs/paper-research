#!/usr/bin/env python3
"""Mutation-test one module on a temporary copy of the repository, so the module and its tests are never changed.

Usage: python tools/run_mutation.py <graph|recap|arxiv|s2|init|debuglog> [--max-survival PERCENT] [--workers N]
Needs cosmic-ray on the PATH, for example: uvx --from cosmic-ray python tools/run_mutation.py init
Prints the surviving mutants with their diffs. Exit 0 if the survival rate is at or below the limit. It also
keeps the counts of the run in mutation/results, and the README's badge in mutation/badge.json: commit both.
Each result holds a hash of the module, its tests, its configuration and the code they import, so a change to any
of them is seen.

cosmic-ray tests one mutant at a time. With --workers N, N workers each test mutants in a copy of their own, so a
machine with N cores finishes about N times sooner. Run it on Linux, for example in a container with a memory limit:
on Windows a timed-out test can leave the process running the mutated code behind.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import badges

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("graph", "recap", "arxiv", "s2", "init", "debuglog")
IGNORED = shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache")
LOCAL = '[cosmic-ray.distributor]\nname = "local"'
STARTUP = 30  # seconds for a worker to start listening
RESULTS = Path("mutation/results")  # the last run of each module, kept for the README badge
BADGE = Path("mutation/badge.json")


def run(command, cwd, check=True, capture=False):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(command, cwd=cwd, check=check, env=env, capture_output=capture, text=True)


def http_config(text, ports):
    """The module's configuration, sending mutants to workers on these ports instead of testing them here."""
    text = text.replace("\r\n", "\n")
    if LOCAL not in text:
        raise SystemExit(f"expected the configuration to contain:\n{LOCAL}")
    urls = ", ".join(f"'http://127.0.0.1:{port}'" for port in ports)
    return text.replace(
        LOCAL, f'[cosmic-ray.distributor]\nname = "http"\n\n[cosmic-ray.distributor.http]\nworker-urls = [{urls}]'
    )


def free_ports(count):
    """count ports nothing is listening on, all different: bound together, then let go for the workers to take."""
    sockets = [socket.socket() for _ in range(count)]
    try:
        for held in sockets:
            held.bind(("127.0.0.1", 0))
        return [held.getsockname()[1] for held in sockets]
    finally:
        for held in sockets:
            held.close()


def wait_until_listening(port, process):
    """Wait for the worker to listen. Whatever else listens on the port doesn't count: the worker must still run."""
    deadline = time.monotonic() + STARTUP
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"the worker on port {port} stopped before it was ready (exit code {process.poll()})")
        with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), timeout=1):
            return
        time.sleep(0.2)
    raise SystemExit(f"the worker on port {port} did not start")


@contextlib.contextmanager
def workers(copy, count):
    """Start count workers, each in a copy of its own. Yields their ports, or nothing when there is one."""
    if count < 2:
        yield []
        return
    ports = free_ports(count)
    processes = []
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        for n, port in enumerate(ports):
            folder = copy.parent / f"worker-{n}"
            shutil.copytree(copy, folder)
            command = ["cosmic-ray", "http-worker", "--port", str(port)]
            processes.append(
                subprocess.Popen(command, cwd=folder, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            )
        for port, process in zip(ports, processes):
            wait_until_listening(port, process)
        yield ports
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait()


def within_limit(rate, limit):
    """Whether the survival rate that cr-rate printed is at or below the limit, both in percent."""
    return float(rate) <= limit


def dependencies(root, module):
    """The paths whose change can change the module's result, as mutation.yml lists them."""
    workflow = (root / ".github/workflows/mutation.yml").read_text(encoding="utf-8")
    (paths,) = re.findall(rf'module: {module},[^\n]*paths: "([^"]+)"', workflow)
    return paths.split()


def tracked(root, paths):
    """The files git tracks under these paths, except SKILL.md: instructions for Claude, which no mutation test reads.
    Files git doesn't track, such as a scratch file or a cache, are left out, so a working copy and a fresh checkout
    give the same list."""
    try:
        listed = run(["git", "ls-files", "-z", "--", *paths], root, capture=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(
            f"cannot list the tracked files with git ({error}): install git, and trust the repository with "
            f"git config --global --add safe.directory {root}"
        ) from error
    return [name for name in listed.split("\0") if name and Path(name).name != "SKILL.md"]


def fingerprint(root, module):
    """A hash of what a module's mutation run depends on: its configuration, how tests are run, and every file git
    tracks under the paths mutation.yml lists for it, which include the code its tests import."""
    names = {f"mutation/{module}.toml", "tools/run_tests.py", *tracked(root, dependencies(root, module))}
    names = {name for name in names if (root / name).is_file()}  # a file deleted but not yet committed is gone
    digest = hashlib.sha256()
    for name in sorted(names):
        digest.update(name.encode() + b"\0")
        digest.update((root / name).read_bytes().replace(b"\r\n", b"\n"))  # the same on Windows and Linux
    return digest.hexdigest()[:16]


def record(root, module, report, today, fingerprint):
    """Keep the module's mutant counts and, from every module's last run, the badge the README shows."""
    jobs, survivors = (re.search(rf"{label}: (\d+)", report) for label in ("total jobs", "surviving mutants"))
    if not (jobs and survivors):
        raise SystemExit("cr-report did not print the number of mutants")
    result = {
        "module": module,
        "total": int(jobs[1]),
        "survivors": int(survivors[1]),
        "date": today,
        "hash": fingerprint,
    }
    folder = root / RESULTS
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{module}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (root / BADGE).write_text(json.dumps(badges.mutation_badge(folder)) + "\n", encoding="utf-8")
    except OSError as error:  # a read-only repository must not fail a run that passed
        print(f"warning: the result of {module} was not kept: {error}", file=sys.stderr)


def main(argv):
    parser = argparse.ArgumentParser(description="Mutation-test one module on a copy of the repository.")
    parser.add_argument("module", choices=MODULES)
    parser.add_argument("--max-survival", type=float, default=5.0, help="allowed survival rate in percent")
    parser.add_argument("--workers", type=int, default=1, help="mutants tested at once, each in its own copy")
    args = parser.parse_args(argv)
    stamp = fingerprint(ROOT, args.module)  # first, so a missing git fails in seconds and not after the last mutant
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(ROOT, copy, ignore=IGNORED)
        config, session = f"mutation/{args.module}.toml", "session.sqlite"
        with workers(copy, args.workers) as ports:
            if ports:
                config = f"mutation/{args.module}.workers.toml"
                (copy / config).write_text(http_config((copy / f"mutation/{args.module}.toml").read_text(), ports))
            run(["cosmic-ray", "init", config, session], copy, capture=True)
            run(["cr-filter-pragma", session], copy, capture=True)  # skip lines marked "# pragma: no mutate"
            run(["cosmic-ray", "baseline", config], copy, capture=True)
            run(["cosmic-ray", "exec", config, session], copy, capture=True)
        report = run(["cr-report", session, "--surviving-only", "--show-diff"], copy, capture=True)
        print(report.stdout)
        # The limit is checked here, not by cr-rate --fail-over, which ignores a limit of 0.
        rate = run(["cr-rate", session], copy, capture=True).stdout.strip()
        print(f"{args.module}: survival rate {rate}% (limit {args.max_survival}%)")
        record(ROOT, args.module, report.stdout, datetime.date.today().isoformat(), stamp)
        return 0 if within_limit(rate, args.max_survival) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
