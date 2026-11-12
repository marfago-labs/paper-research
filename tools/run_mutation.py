#!/usr/bin/env python3
"""Mutation-test one module on a temporary copy of the repository, so the real files are never changed.

Usage: python tools/run_mutation.py <graph|recap|arxiv|s2|init> [--max-survival PERCENT] [--workers N]
Needs cosmic-ray on the PATH, for example: uvx --from cosmic-ray python tools/run_mutation.py init
Prints the surviving mutants with their diffs. Exit 0 if the survival rate is at or below the limit.

cosmic-ray tests one mutant at a time. With --workers N, N workers each test mutants in a copy of their own, so a
machine with N cores finishes about N times sooner. Run it on Linux, for example in a container with a memory limit:
on Windows a timed-out test can leave the process running the mutated code behind.
"""

import argparse
import contextlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("graph", "recap", "arxiv", "s2", "init")
IGNORED = shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache")
LOCAL = '[cosmic-ray.distributor]\nname = "local"'
STARTUP = 30  # seconds for a worker to start listening


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


def main(argv):
    parser = argparse.ArgumentParser(description="Mutation-test one module on a copy of the repository.")
    parser.add_argument("module", choices=MODULES)
    parser.add_argument("--max-survival", type=float, default=5.0, help="allowed survival rate in percent")
    parser.add_argument("--workers", type=int, default=1, help="mutants tested at once, each in its own copy")
    args = parser.parse_args(argv)
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
        rate = run(["cr-rate", session, "--fail-over", str(args.max_survival)], copy, check=False, capture=True)
        print(f"{args.module}: survival rate {rate.stdout.strip()}% (limit {args.max_survival}%)")
        return rate.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
