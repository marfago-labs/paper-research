"""Behave hooks: a fresh workspace per scenario, and helpers to run the plugin's scripts."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "graph": REPO / "skills" / "graph" / "scripts" / "graph.py",
    "recap": REPO / "skills" / "recap" / "scripts" / "recap.py",
    "init": REPO / "skills" / "init" / "scripts" / "init.py",
    "arxiv": REPO / "skills" / "arxiv" / "scripts" / "arxiv.py",
    "scholar": REPO / "skills" / "scholar" / "scripts" / "s2.py",
}
for folder in ("graph", "recap", "init"):
    sys.path.insert(0, str(REPO / "skills" / folder / "scripts"))


def run_script(context, name, args, cwd=None, stdin=None):
    """Run one of the plugin's scripts as a user would, from the workspace root."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(
        [sys.executable, str(SCRIPTS[name]), *args],
        cwd=cwd or context.workspace,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    context.result = SimpleNamespace(code=done.returncode, out=done.stdout, err=done.stderr)
    return context.result


def before_all(context):
    context.repo = REPO
    context.run_script = lambda name, args, cwd=None, stdin=None: run_script(context, name, args, cwd, stdin)


def before_scenario(context, scenario):
    context._folder = tempfile.TemporaryDirectory()
    context.workspace = Path(context._folder.name)
    context.result = SimpleNamespace(code=None, out="", err="")


def after_scenario(context, scenario):
    context._folder.cleanup()
