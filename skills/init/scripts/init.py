#!/usr/bin/env python3
"""Set up or update a paper-research workspace. Standard library only.

Run from the workspace root. It never overwrites a research file that exists. It changes only:
- missing starter files in research/,
- the marked paper-research block in CLAUDE.md (created, or replaced if present),
- missing entries in .claude/settings.json (merged, nothing removed),
- missing lines in .gitignore.
--dry-run prints what would change, with a diff for files that exist, and writes nothing. It also prints,
on a line starting with "! ", the command that writes the changes. The user runs that command, because
init changes the permission rules and instructions that steer Claude, so Claude must not run it.
--sandbox also turns on Claude Code's sandbox for shell commands, limited to the same hosts.
Exit codes: 0 success, 1 a file couldn't be read or updated safely, 2 usage error.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL_DIR / "templates"
PLUGIN_JSON = SKILL_DIR.parents[1] / ".claude-plugin" / "plugin.json"
BEGIN = "<!-- paper-research:begin (written by the init skill; edit outside this block) -->"
END = "<!-- paper-research:end -->"
GITIGNORE = [
    "__pycache__/",
    ".cache/",
    "research/pdfs/",
    "research/fulltext/",
    "research/recap/",
    "research/graph/.lock",
    ".claude/settings.local.json",
]
CLAUDE_HEADER = (
    "# Paper research workspace\n\n"
    "Add this workspace's own settings, such as the user's topics, above or below the block.\n\n"
)
# init writes no allow rules. Ask rules only add a prompt, so they can't widen permissions, and init writes
# only two kinds: approval for editing a file, and approval for fetching from a named host.
ASK_RULE = re.compile(r"Edit\(/[^()\s]+\)|WebFetch\(domain:[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}\)")
# Settings keys that must be of this type if present, so a merge can't fail halfway on a wrong shape.
EXPECTED_SHAPE = [
    ("permissions", dict),
    ("permissions.allow", list),
    ("permissions.ask", list),
    ("permissions.deny", list),
    ("autoMode", dict),
    ("autoMode.soft_deny", list),
    ("sandbox", dict),
    ("sandbox.filesystem", dict),
    ("sandbox.filesystem.denyWrite", list),
    ("sandbox.network", dict),
    ("sandbox.network.allowedDomains", list),
    ("sandbox.network.deniedDomains", list),
]
MISSING = object()
# Characters a path may hold and still sit safely inside double quotes in bash, PowerShell, and cmd.
SAFE_PATH = re.compile(r"[\w .:/()@+,=~-]+")


class InitError(Exception):
    pass


def version():
    try:
        return json.loads(PLUGIN_JSON.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, ValueError):
        return "unknown"


def block():
    body = (TEMPLATES / "rules-block.md").read_text(encoding="utf-8").strip()
    return f"{BEGIN}\n<!-- plugin version {version()} -->\n\n{body}\n\n{END}\n"


def claude_md(current):
    """CLAUDE.md with the block added or replaced, leaving everything else as it is."""
    if current is None:
        return CLAUDE_HEADER + block()
    if current.count(BEGIN) > 1 or current.count(END) > 1:
        raise InitError("CLAUDE.md has more than one paper-research block; remove the extra ones by hand first")
    has_begin, has_end = BEGIN in current, END in current
    if not has_begin and not has_end:
        return current.rstrip("\n") + "\n\n" + block()
    start, end = current.find(BEGIN), current.find(END)
    # The markers are different texts, so they can't start at the same place.
    if has_begin != has_end or end < start:  # pragma: no mutate
        raise InitError("CLAUDE.md has only one of the paper-research markers; fix it by hand first")
    return current[:start] + block() + current[end + len(END) :].lstrip("\n")


def load_template(name):
    return json.loads((TEMPLATES / name).read_text(encoding="utf-8"))


def check_template(template):
    """Refuse a settings template that would allow anything, or ask about anything but edits and fetches."""
    for rule in template.get("permissions", {}).get("allow", []):
        raise InitError(f"the plugin's settings template has an allow rule init won't write: {rule!r}")
    for rule in template.get("permissions", {}).get("ask", []):
        if not isinstance(rule, str) or not ASK_RULE.fullmatch(rule):
            raise InitError(f"the plugin's settings template has an ask rule init won't write: {rule!r}")
    return template


def extend(target, rules):
    target.extend(rule for rule in rules if rule not in target)


def merge_settings(current, sandbox=False):
    """Add the template's rules to the settings, removing nothing."""
    template = check_template(load_template("settings.json"))
    settings = json.loads(json.dumps(current))
    permissions = settings.setdefault("permissions", {})
    extend(permissions.setdefault("ask", []), template["permissions"]["ask"])
    soft = settings.setdefault("autoMode", {}).setdefault("soft_deny", [])
    if not soft:
        soft.append("$defaults")
    extend(soft, template["autoMode"]["soft_deny"])
    merge_sandbox(settings, sandbox)
    return settings


def merge_sandbox(settings, turn_on):
    """Turn the sandbox on if asked, and keep any sandbox from reaching hosts that could publish notes."""
    if turn_on:
        box = settings.setdefault("sandbox", {})
        box["enabled"] = True
        box["allowUnsandboxedCommands"] = False
    if "sandbox" not in settings:
        return
    template = load_template("sandbox.json")["sandbox"]
    # The approval prompt covers Claude's file tools only, so keep sandboxed shell commands from writing
    # the files that later sessions load as instructions. The ./ paths mean the workspace only because they
    # go in the project's .claude/settings.json: in ~/.claude/settings.json they would mean ~/.claude.
    files = settings["sandbox"].setdefault("filesystem", {})
    extend(files.setdefault("denyWrite", []), template["filesystem"]["denyWrite"])
    wanted = template["network"]
    network = settings["sandbox"].setdefault("network", {})
    if turn_on:
        extend(network.setdefault("allowedDomains", []), wanted["allowedDomains"])
    # Claude Code also opens the hosts of WebFetch(domain:...) allow rules to sandboxed commands. A denied
    # domain stays blocked whatever allows it, and the WebFetch tool itself isn't affected.
    extend(network.setdefault("deniedDomains", []), wanted["deniedDomains"])


def lookup(settings, path):
    for key in path.split("."):
        if not isinstance(settings, dict) or key not in settings:
            return MISSING
        settings = settings[key]
    return settings


def parse_settings(path, text):
    if text is None:
        return {}
    try:
        settings = json.loads(text)
    except ValueError as err:
        raise InitError(f"{path} is not valid JSON ({err}); fix it by hand first") from None
    if not isinstance(settings, dict) or any(
        (value := lookup(settings, key)) is not MISSING and not isinstance(value, kind) for key, kind in EXPECTED_SHAPE
    ):
        raise InitError(f"{path} has an unexpected shape; fix it by hand first")
    return settings


def detect_indent(text):
    """The indentation the file already uses, so a merge doesn't reformat it."""
    for line in text.splitlines():
        indent = line[: len(line) - len(line.lstrip(" \t"))]
        if indent and line.strip():
            return "\t" if indent.startswith("\t") else len(indent)
    return 2


def dump(settings, indent):
    return json.dumps(settings, indent=indent, ensure_ascii=False) + "\n"


def read_or_none(path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def starter_files(workspace):
    """Each starter file that the workspace doesn't have yet, as a change."""
    for template in sorted((TEMPLATES / "research").rglob("*")):
        target = workspace / "research" / template.relative_to(TEMPLATES / "research")
        if template.is_file() and not target.exists():
            yield target, None, template.read_text(encoding="utf-8")


def settings_change(workspace, sandbox):
    """The settings with the template merged in, as a list of at most one change."""
    path = workspace / ".claude" / "settings.json"
    text = read_or_none(path)
    current = parse_settings(path, text)
    merged = merge_settings(current, sandbox)
    if text is None:
        return [(path, None, dump(merged, 2))]
    return [(path, text, dump(merged, detect_indent(text)))] if merged != current else []


def gitignore_change(workspace):
    path = workspace / ".gitignore"
    old = read_or_none(path)
    lines = (old or "").splitlines()
    missing = [line for line in GITIGNORE if line not in lines]
    separator = "\n" if old and old.strip() else ""
    return path, old, (old or "").rstrip("\n") + separator + "".join(f"{m}\n" for m in missing)


def plan(workspace, sandbox=False):
    """Every change as (path, old text or None, new text)."""
    claude = workspace / "CLAUDE.md"
    old = read_or_none(claude)
    changes: list[tuple[Path, str | None, str]] = [  # pragma: no mutate
        *starter_files(workspace),
        (claude, old, claude_md(old)),
        *settings_change(workspace, sandbox),
        gitignore_change(workspace),
    ]
    return [(p, o, n) for p, o, n in changes if o != n]


def describe(path, old, new, workspace):
    name = path.relative_to(workspace).as_posix()
    if old is None:
        return f"create {name}"
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm="")
    return f"update {name}\n" + "\n".join(diff)


def build_parser():
    parser = argparse.ArgumentParser(description="Set up or update a paper-research workspace.")
    parser.add_argument("--workspace", type=Path, default=Path("."), help="workspace root (default: here)")
    parser.add_argument("--dry-run", action="store_true", help="show the changes without writing them")
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="also turn on the sandbox for shell commands, reaching only the hosts the scripts use",
    )
    return parser


def write_command(workspace, sandbox):
    """The command that writes the changes, for the user to run, or None if a path would need shell quoting."""
    script = Path(__file__).resolve().as_posix()
    folder = workspace.as_posix()
    if not (SAFE_PATH.fullmatch(script) and SAFE_PATH.fullmatch(folder)):
        return None
    return f'python "{script}" --workspace "{folder}"' + (" --sandbox" if sandbox else "")


def show_write_command(workspace, sandbox):
    command = write_command(workspace, sandbox)
    if command is None:
        print("no ready-made command: a path here needs shell quoting, so run init.py from a terminal")
        print("in the workspace folder")
    else:
        print(f"! {command}")


def apply(changes, workspace, dry_run):
    """Print each change, and write it unless this is a dry run."""
    for path, old, new in changes:
        print(describe(path, old, new, workspace))
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new, encoding="utf-8")
    if not changes:
        print("workspace is up to date")
    elif dry_run:
        print(f"{len(changes)} changes; nothing written (dry run)")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2
    try:
        changes = plan(workspace, args.sandbox)
    except InitError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    apply(changes, workspace, args.dry_run)
    if args.dry_run and changes:
        show_write_command(workspace, args.sandbox)
    return 0


if __name__ == "__main__":  # pragma: no mutate
    sys.exit(main())
