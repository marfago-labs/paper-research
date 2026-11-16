"""Behave hooks: a fresh workspace per scenario, and helpers to run the plugin's scripts."""

import os
import re
import subprocess
import sys
import tempfile
import unicodedata
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


def unescaped(text):
    """Text with [U+XXXX] written out as the character it names, so a scenario can carry an invisible one.

    The characters themselves are not written in the feature files, because they show as nothing in a review, and a
    console that isn't UTF-8 cannot print them in the report.
    """
    return re.sub(r"\[U\+([0-9A-Fa-f]{4,6})\]", lambda m: chr(int(m.group(1), 16)), text)


def hidden_characters(text):
    """The characters in text that show nothing but that a model reads: format characters, tags, and selectors.

    Found from the Unicode tables and the known ranges, not with the pattern the scripts use, so a scenario can
    fail if that pattern is wrong. Joiners and the emoji selector are not counted, since text needs them. It is
    stricter than the script on a few format characters that show or shape text, such as the soft hyphen, which no
    scenario uses.
    """
    found = []
    for char in text:
        code = ord(char)
        in_tags = 0xE0000 <= code <= 0xE007F or 0xE0100 <= code <= 0xE01EF
        formatting = unicodedata.category(char) == "Cf" and code not in (0x200C, 0x200D)
        if in_tags or formatting:
            found.append(f"U+{code:04X}")
    return found


def before_all(context):
    context.repo = REPO
    context.run_script = lambda name, args, cwd=None, stdin=None: run_script(context, name, args, cwd, stdin)


def before_scenario(context, scenario):
    context._folder = tempfile.TemporaryDirectory()
    context.workspace = Path(context._folder.name)
    context.original_cwd = os.getcwd()
    context.result = SimpleNamespace(code=None, out="", err="")
    context.patches = []

    def place(part):
        """A command-line word with WORKSPACE and ELSEWHERE (a temporary folder) replaced by their folders."""
        part = part.replace("WORKSPACE", str(context.workspace))
        return part.replace("ELSEWHERE", str(context.elsewhere)) if hasattr(context, "elsewhere") else part

    context.place = place
    context.unescaped = unescaped
    context.hidden_characters = hidden_characters


def after_scenario(context, scenario):
    os.chdir(context.original_cwd)
    for patcher in context.patches:
        patcher.stop()
    context._folder.cleanup()
    # Scenarios that run the clients can leave request-pacing state in the repo's .cache. Remove only that,
    # so other things kept there, such as the gitleaks binary, survive.
    for state in (REPO / ".cache").glob("*-last-request*"):
        state.unlink(missing_ok=True)
