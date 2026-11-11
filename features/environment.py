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
for folder in ("graph", "recap", "arxiv", "scholar", "init"):
    sys.path.insert(0, str(REPO / "skills" / folder / "scripts"))


def run_script(context, name, args, cwd=None):
    """Run one of the plugin's scripts as a user would, from the workspace root."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(
        [sys.executable, str(SCRIPTS[name]), *args],
        cwd=cwd or context.workspace,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    context.result = SimpleNamespace(code=done.returncode, out=done.stdout, err=done.stderr)
    return context.result


def before_all(context):
    context.repo = REPO
    context.run_script = lambda name, args, cwd=None: run_script(context, name, args, cwd)


def before_scenario(context, scenario):
    context._folder = tempfile.TemporaryDirectory()
    context.workspace = Path(context._folder.name)
    context.original_cwd = os.getcwd()
    context.result = SimpleNamespace(code=None, out="", err="")
    context.patches = []


def after_scenario(context, scenario):
    os.chdir(context.original_cwd)
    for patcher in context.patches:
        patcher.stop()
    context._folder.cleanup()
    # Scenarios that run the clients can leave request-pacing state in the repo's .cache. Remove only that,
    # so other things kept there, such as the gitleaks binary, survive.
    for state in (REPO / ".cache").glob("*-last-request*"):
        state.unlink(missing_ok=True)
