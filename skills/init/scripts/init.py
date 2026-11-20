#!/usr/bin/env python3
"""Set up a paper-research workspace, and run the plugin's session and approval hooks. Standard library only.

Run from the workspace root, it creates each missing starter file in research/ and adds missing lines to .gitignore.
It never changes a research file that exists, and never touches CLAUDE.md or .claude/. Then it prints the rules and
the lessons, so the session that ran it can follow them at once.

With --hook it is one of the plugin's hooks instead, and reads the hook event from stdin:
- rules: at session start in a workspace, prints the plugin's rules, which Claude Code adds to Claude's context.
- lessons: at session start in a workspace, prints research/lessons.md the same way.
- guard: before an edit or a fetch, asks the user to approve any edit to a workspace's research/lessons.md or
  research/profile.md, and any fetch from the hosts the plugin reads papers from, in a workspace.
A hook never fails the session: it exits 0 whatever it is sent.
Exit codes: 0 success, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

# The debug skill's helper records events while debugging is on.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "debug" / "scripts"))  # pragma: no mutate
import debuglog  # noqa: E402  (after the path is set)

SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL_DIR / "templates"
RESEARCH = "research"
MARKER = "user-facts.md"
GITIGNORE = [
    "__pycache__/",
    ".cache/",
    "research/pdfs/",
    "research/fulltext/",
    "research/recap/",
    "research/graph/.lock",
    ".claude/settings.local.json",
    "research/.debug",
    "research/.debug.log",
    "research/.debug.log.1",
]
# Claude Code keeps at most 10,000 characters of a hook's output in context, so the lessons are cut well before that.
LESSONS_LIMIT = 9000
LESSONS_BEGIN = "--- research/lessons.md begins ---"
LESSONS_END = "--- research/lessons.md ends ---"
LESSONS_HEADER = (
    "## Lessons\n\n"
    "How to work with this user, from research/lessons.md. The user approved each lesson. Follow them as rules.\n"
)
# The files that later sessions read as instructions, and the tools that change them, with the input that names the
# file. Every other file and tool is left to Claude Code's own permissions.
GUARDED_FILES = ("lessons.md", "profile.md")
EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
FETCH_HOSTS = frozenset(
    {
        "arxiv.org",
        "export.arxiv.org",
        "api.semanticscholar.org",
        "huggingface.co",
        "github.com",
        "api.github.com",
    }
)
UNCLEAR = "the plugin couldn't tell which file or address this changes or reads; approve only if you asked for it"


# --- setting up a workspace ------------------------------------------------------------------------------------


def read_or_none(path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def starter_files(workspace):
    """Each starter file that the workspace doesn't have yet, as a change."""
    for template in sorted((TEMPLATES / RESEARCH).rglob("*")):
        target = workspace / RESEARCH / template.relative_to(TEMPLATES / RESEARCH)
        if template.is_file() and not target.exists():
            yield target, template.read_text(encoding="utf-8")


def gitignore_change(workspace):
    """.gitignore with the missing lines added, or None if it has them all."""
    old = read_or_none(workspace / ".gitignore") or ""
    missing = [line for line in GITIGNORE if line not in old.splitlines()]
    if not missing:
        return None
    separator = "\n" if old.strip() else ""
    return old.rstrip("\n") + separator + "".join(f"{line}\n" for line in missing)


def set_up(workspace):
    """Write the missing files, and print each one."""
    for path, text in starter_files(workspace):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"created {path.relative_to(workspace).as_posix()}")
    gitignore = gitignore_change(workspace)
    if gitignore is not None:
        (workspace / ".gitignore").write_text(gitignore, encoding="utf-8")
        print("updated .gitignore")


# --- what Claude is told at the start of a session ----------------------------------------------------------------


def rules():
    return (TEMPLATES / "rules.md").read_text(encoding="utf-8").strip() + "\n"


def lessons(workspace):
    """research/lessons.md, marked as the user's lessons, and cut so it fits in what Claude Code keeps."""
    text = (workspace / RESEARCH / "lessons.md").read_text(encoding="utf-8").strip()
    if len(text) > LESSONS_LIMIT:
        text = text[:LESSONS_LIMIT] + "\n[cut: the rest of research/lessons.md is longer than a session loads]"
    return f"{LESSONS_HEADER}\n{LESSONS_BEGIN}\n{text}\n{LESSONS_END}\n"


# --- the hooks ---------------------------------------------------------------------------------------------------


def read_event(stdin):
    """The hook event, or {} if stdin isn't a JSON object."""
    try:
        event = json.loads(stdin.buffer.read().decode("utf-8"))
    except ValueError:  # bad JSON, and bytes that aren't UTF-8 (UnicodeDecodeError is a ValueError)
        return {}
    return event if isinstance(event, dict) else {}


def event_folder(event):
    cwd = event.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def is_workspace(folder):
    return (folder / RESEARCH / MARKER).is_file()


def find_workspace(folder):
    """The folder, or the nearest folder above it, that holds a paper workspace, or None."""
    try:
        folder = folder.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return next((place for place in (folder, *folder.parents) if is_workspace(place)), None)


def plain_name(name):
    """A file name as Windows opens it: without a :stream suffix, and without trailing dots and spaces."""
    return name.split(":")[0].rstrip(". ").casefold()


def guarded_file(raw, folder, workspace):
    """The guarded file that raw names, or None. Raises ValueError if raw can't be turned into a path."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(raw)
    path = (folder / raw.replace("\\", "/")).resolve()
    name = plain_name(path.name)
    if name in GUARDED_FILES and path.parent.name.casefold() == RESEARCH and (path.parent / MARKER).is_file():
        return f"{RESEARCH}/{name}"
    return same_file(path, workspace)


def same_file(path, workspace):
    """The guarded file of the workspace that path is another name for, such as a hard link or a short name."""
    if workspace is None or not path.exists():
        return None
    for guarded in GUARDED_FILES:
        target = workspace / RESEARCH / guarded
        if target.exists() and os.path.samefile(path, target):
            return f"{RESEARCH}/{guarded}"
    return None


def fetch_host(raw):
    """The host a URL fetches from, as a browser reads it. Raises ValueError if there is none."""
    if not isinstance(raw, str):
        raise ValueError(raw)
    url = "".join(char for char in raw if char not in "\t\n\r").strip().replace("\\", "/")
    host = urlsplit(url).hostname
    if not host:
        raise ValueError(raw)
    host = unicodedata.normalize("NFKC", unquote(host)).casefold()
    for dot in ("。", "．", "｡"):
        host = host.replace(dot, ".")
    return host.removesuffix(".")


def guard_reason(event):
    """Why the user should approve this tool call, or None if it isn't one the plugin guards."""
    tool = event.get("tool_name")
    if tool not in (*EDIT_TOOLS, "WebFetch"):  # a tuple, so a name that isn't a string can't raise
        return None
    folder = event_folder(event)
    workspace = find_workspace(folder)
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    try:
        if tool in EDIT_TOOLS:
            return edit_reason(guarded_file(tool_input.get(EDIT_TOOLS[tool]), folder, workspace))
        return fetch_reason(tool_input.get("url")) if workspace is not None else None
    except (OSError, RuntimeError, ValueError):
        return UNCLEAR if workspace is not None else None


def edit_reason(name):
    if name is None:
        return None
    return f"{name} is loaded as instructions in every session; approve only a change you asked for"


def fetch_reason(url):
    host = fetch_host(url)
    if host not in FETCH_HOSTS:
        return None
    return f"a fetch from {host}, a host the paper-research plugin reads papers from; approve only if you expected it"


def ask(reason):
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        }
    )


def rules_hook(event):
    folder = event_folder(event)
    if find_workspace(folder) is None:
        return None
    text = rules()
    debuglog.event("init", "rules", folder=folder, chars=len(text))
    return text


def lessons_hook(event):
    folder = event_folder(event)
    workspace = find_workspace(folder)
    if workspace is None:
        return None
    text = lessons(workspace)
    debuglog.event("init", "lessons", folder=folder, chars=len(text), cut="[cut:" in text)
    return text


def guard_hook(event):
    reason = guard_reason(event)
    decision = "pass" if reason is None else "ask"
    debuglog.event(
        "init", "guard", folder=event_folder(event), tool=event.get("tool_name"), decision=decision, reason=reason or ""
    )
    return None if reason is None else ask(reason) + "\n"


HOOKS = {"rules": rules_hook, "lessons": lessons_hook, "guard": guard_hook}


def run_hook(name, stdin):
    """Run one hook. Whatever happens, the session goes on: errors print nothing and exit 0."""
    event = read_event(stdin)
    try:
        output = HOOKS[name](event)
    except (OSError, ValueError):  # a file that can't be read or decoded: the session starts without it
        output = None
    if output is not None:
        print(output, end="")
    return 0


# --- the command line --------------------------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(description="Set up a paper-research workspace, or run one of its hooks.")
    parser.add_argument("--workspace", type=Path, default=Path("."), help="workspace root (default: here)")
    parser.add_argument(
        "--hook",
        choices=sorted(HOOKS),
        help="run as one of the plugin's hooks, reading the hook event from stdin",
    )
    return parser


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    if args.hook:
        return run_hook(args.hook, sys.stdin)
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2
    set_up(workspace)
    print()
    print(rules())
    print(lessons(workspace), end="")
    return 0


if __name__ == "__main__":  # pragma: no mutate
    sys.exit(debuglog.run("init", main, sys.argv[1:]))
