"""Steps for the recap, init, and plugin features."""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

PAPERS_HEAD = "# Papers\n\n| Added | Title | ID | Status | Rating | Tags | Summary |\n|---|---|---|---|---|---|---|\n"


def research(context):
    return context.workspace / "research"


def recap_data(context):
    text = (research(context) / "recap" / "recap-data.js").read_text(encoding="utf-8")
    return json.loads(text.split("window.RECAP_DATA = ", 1)[1].rstrip().rstrip(";"))


@given("a research folder with these papers")
def research_papers(context):
    research(context).mkdir(parents=True, exist_ok=True)
    rows = "".join(
        f"| {r['added']} | {r['title']} | {r['id']} | {r['status']} | - | tag | A summary. |\n" for r in context.table
    )
    (research(context) / "papers.md").write_text(PAPERS_HEAD + rows, encoding="utf-8")


@given('the full text of "{number}" is saved')
def saved_full_text(context, number):
    folder = research(context) / "fulltext"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{number}.md").write_text("# A paper", encoding="utf-8")


@given('the graph has the paper "{ident}" with only its author')
def graph_only_author(context, ident):
    folder = research(context) / "graph"
    folder.mkdir(parents=True, exist_ok=True)
    entities = [
        {"id": f"paper:{ident}", "type": "paper", "name": "A paper", "aliases": [f"ARXIV:{ident}"]},
        {"id": "author:ann", "type": "author", "name": "Ann"},
    ]
    relation = {"from": f"paper:{ident}", "rel": "authored-by", "to": "author:ann", "source": "s", "status": "verified"}
    (folder / "entities.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entities), encoding="utf-8")
    (folder / "relations.jsonl").write_text(json.dumps(relation) + "\n", encoding="utf-8")


@given('the graph has the paper "{ident}" with {count:d} citations, cited by the paper "{other}"')
def graph_standing(context, ident, count, other):
    folder = research(context) / "graph"
    folder.mkdir(parents=True, exist_ok=True)
    standing = {"citations": count, "checked": "2026-11-01"}
    entities = [
        {"id": f"paper:{ident}", "type": "paper", "name": "Cited", "aliases": [], "standing": standing},
        {"id": f"paper:{other}", "type": "paper", "name": "Citing", "aliases": []},
    ]
    relation = {"from": f"paper:{other}", "rel": "cites", "to": f"paper:{ident}", "source": "s", "status": "verified"}
    (folder / "entities.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entities), encoding="utf-8")
    (folder / "relations.jsonl").write_text(json.dumps(relation) + "\n", encoding="utf-8")


@then("the recap data gives {ident} {count:d} citations")
def recap_citations(context, ident, count):
    papers = {p["id"]: p for p in recap_data(context)["papers"]}
    assert papers[ident]["standing"]["citations"] == count, papers[ident]


@then("the recap data has no citation counts for {ident}")
def recap_no_citations(context, ident):
    papers = {p["id"]: p for p in recap_data(context)["papers"]}
    assert "standing" not in papers[ident], papers[ident]


@then("the recap data says {ident} is cited by {cited:d} of my papers, in {insights:d} insight, and in {pins:d} pins")
def recap_collection(context, ident, cited, insights, pins):
    papers = {p["id"]: p for p in recap_data(context)["papers"]}
    expected = {"cited_by": cited, "insights": insights, "pins": pins}
    assert papers[ident]["collection"] == expected, papers[ident]


@given('the graph has the paper "{ident}" with a dataset it evaluates on')
def graph_extracted(context, ident):
    graph_only_author(context, ident)
    folder = research(context) / "graph"
    with open(folder / "entities.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "dataset:d", "type": "dataset", "name": "D", "aliases": []}) + "\n")
    relation = {"from": f"paper:{ident}", "rel": "evaluates-on", "to": "dataset:d", "source": "s", "status": "verified"}
    with open(folder / "relations.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(relation) + "\n")


@given('an insight "{title}" drawn from {ident}')
def research_insight(context, title, ident):
    research(context).mkdir(parents=True, exist_ok=True)
    text = (
        f"# Insights\n\n## {title}\n\n- **ID:** `insight:one`\n- **Kind:** `practice`\n"
        f"- **Sources:** `{ident}`, section 3.\n"
    )
    (research(context) / "insights.md").write_text(text, encoding="utf-8")


@given('the user logged the {kind} "{text}" on {date}')
def research_fact(context, kind, text, date):
    research(context).mkdir(parents=True, exist_ok=True)
    with open(research(context) / "user-facts.md", "a", encoding="utf-8") as handle:
        handle.write(f"{date} | {kind} | stated | {text}\n")


@when("I refresh the recap")
def refresh_recap(context):
    research(context).mkdir(parents=True, exist_ok=True)
    context.run_script("recap", [])


@when("the turn ends")
def turn_ends(context):
    context.run_script("recap", ["--stop-hook"], stdin=json.dumps({"cwd": str(context.workspace)}))


@when("the turn ends again after the hook already asked once")
def turn_ends_again(context):
    event = {"cwd": str(context.workspace), "stop_hook_active": True}
    context.run_script("recap", ["--stop-hook"], stdin=json.dumps(event))


@when('the hook is sent "{event}"')
def hook_sent(context, event):
    context.run_script("recap", ["--stop-hook"], stdin=event)


@given('the file "{name}" holds bytes that are not UTF-8')
def file_with_bad_bytes(context, name):
    target = context.workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes([0xFF, 0xFE, 0x00, 0x80, 0x81]))


@when("the recap page is refreshed")
def page_refreshed(context):
    context.run_script("recap", [])
    data = research(context) / "recap" / "recap-data.js"
    later = max(path.stat().st_mtime for path in research(context).rglob("*") if path.is_file()) + 10
    os.utime(data, (later, later))


@given("a workspace just set up by init")
def workspace_set_up(context):
    context.run_script("init", ["--workspace", "."])
    assert context.result.code == 0, context.result.err


@given('the user added the pin "{text}"')
def added_pin(context, text):
    with open(research(context) / "pins.md", "a", encoding="utf-8") as handle:
        handle.write(f"- **[concept] {text}:** a fact. Added: 2026-11-15\n")


@then("Claude is told to refresh the recap and log the questions")
def told_to_refresh(context):
    assert context.result.code == 0, context.result.err
    answer = json.loads(context.result.out)
    assert answer["decision"] == "block", answer
    assert "recap skill" in answer["reason"] and "user-facts.md" in answer["reason"], answer
    assert "from this session" in answer["reason"], answer


@then("the turn is allowed to end")
def turn_may_end(context):
    assert context.result.code == 0, context.result.err
    assert context.result.out == "", context.result.out


@when("the turn ends through the registered hook command with python3 {state}")
def turn_ends_through_command(context, state):
    manifest = json.loads((context.repo / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    command = manifest["hooks"]["Stop"][0]["hooks"][0]["command"]
    run_registered(context, command, state, {"cwd": str(context.workspace)})


def run_registered(context, command, state, event):
    """Run a hook command as hooks.json registers it, with python3 missing, failing, broken, or working."""
    sh = shutil.which("sh")
    assert sh, "these scenarios need a POSIX shell"
    python = f'"{Path(sys.executable).as_posix()}"'
    fake = context.workspace / "fake-python3.sh"
    bodies = {
        "crashing after it read the event": "cat > /dev/null; echo Traceback >&2; exit 3",
        "only the Windows Store alias": "echo 'Python was not found' >&2; exit 49",
    }
    python3 = {"missing": "no-such-python3-anywhere", "failing": "false", "working": python}.get(state)
    if python3 is None:
        with fake.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(bodies[state] + "\n")
        python3 = f'sh "{fake.as_posix()}"'
    command = command.replace("python3 ", f"{python3} ", 1).replace("|| python ", f"|| {python} ", 1)
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": context.repo.as_posix(), "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(
        [sh, "-c", command],
        cwd=context.workspace,
        env=env,
        input=json.dumps(event),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    context.result = SimpleNamespace(code=done.returncode, out=done.stdout, err=done.stderr)


@then("the plugin runs that check when a turn ends")
def plugin_has_stop_hook(context):
    manifest = json.loads((context.repo / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    (entry,) = manifest["hooks"]["Stop"][0]["hooks"]
    assert entry["type"] == "command", entry
    assert "${CLAUDE_PLUGIN_ROOT}/skills/recap/scripts/recap.py" in entry["command"], entry
    assert entry["command"].endswith("--stop-hook"), entry
    first, second = entry["command"].split(" || ")
    assert first.startswith("python3 ") and second.startswith("python "), entry
    script = context.repo / "skills" / "recap" / "scripts" / "recap.py"
    assert script.is_file()


@then("the recap data lists {count:d} papers")
def recap_paper_count(context, count):
    assert len(recap_data(context)["papers"]) == count


@then('the recap data marks {ident} as "{state}"')
def recap_marks(context, ident, state):
    papers = {p["id"]: p for p in recap_data(context)["papers"]}
    assert papers[ident].get("graph") == state, papers[ident]


@then("the recap data has no graph status for {ident}")
def recap_no_status(context, ident):
    papers = {p["id"]: p for p in recap_data(context)["papers"]}
    assert "graph" not in papers[ident], papers[ident]


@then("the recap data links the insight to {ident}")
def recap_insight_link(context, ident):
    assert ident in recap_data(context)["insights"][0]["papers"]


@then('the recap data has the {kind} "{text}"')
def recap_fact(context, kind, text):
    facts = [(f["type"], f["text"]) for f in recap_data(context)["facts"]]
    assert (kind, text) in facts, facts


@then('the recap data says the graph cannot be shown because "{text}"')
def recap_graph_error(context, text):
    error = recap_data(context)["graph"]["error"]
    assert text in error, error


@then("the recap folder holds the page, its script library, and the data")
def recap_folder(context):
    names = sorted(p.name for p in (research(context) / "recap").iterdir())
    assert names == sorted(
        ["recap.html", "recap-lib.js", "cytoscape-3.30.4.min.js", "cytoscape-LICENSE.txt", "recap-data.js"]
    ), names


@given('the file "{name}" contains the text "{text}"')
def given_file(context, name, text):
    target = context.workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace('\\"', '"').replace("\\n", "\n"), encoding="utf-8")


@given('the file "{name}" is empty')
def given_empty_file(context, name):
    target = context.workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")


@when("I run init")
def run_init(context):
    context.run_script("init", ["--workspace", "."])


@then("the workspace has the starter research files")
def starter_files(context):
    for name in ("papers.md", "user-facts.md", "profile.md", "pins.md", "lessons.md", "insights.md"):
        assert (research(context) / name).exists(), name
    assert (research(context) / "graph" / "entities.jsonl").exists()


def rules_text(context):
    return (context.repo / "skills" / "init" / "templates" / "rules.md").read_text(encoding="utf-8").strip()


@then("the output holds the plugin's rules and the lessons")
def output_has_rules(context):
    out = context.result.out
    assert rules_text(context) in out, out[:300]
    assert "--- research/lessons.md begins ---" in out and out.rstrip().endswith("--- research/lessons.md ends ---")
    assert out.index(rules_text(context)) < out.index("--- research/lessons.md begins ---"), "rules come first"


@then('the file "{name}" is still "{text}"')
def file_unchanged(context, name, text):
    want = text.replace('\\"', '"').replace("\\n", "\n")
    assert (context.workspace / name).read_text(encoding="utf-8") == want, name


@then("the local settings file is ignored by git")
def local_ignored(context):
    assert ".claude/settings.local.json" in (context.workspace / ".gitignore").read_text(encoding="utf-8").splitlines()


def run_hook(context, hook, event):
    stdin = event if isinstance(event, str) else json.dumps(event)
    return context.run_script("init", ["--hook", hook], stdin=stdin)


@when("a session starts in the workspace")
def session_starts(context):
    event = {"cwd": str(context.workspace), "source": "startup"}
    context.session = {hook: run_hook(context, hook, event) for hook in ("rules", "lessons")}


@then("Claude is given the plugin's rules")
def given_rules(context):
    result = context.session["rules"]
    assert result.code == 0 and result.err == "", result.err
    assert result.out.strip() == rules_text(context), result.out[:300]
    assert len(result.out) < 10000, "Claude Code keeps only 10,000 characters of a hook's output"


@then('Claude is given the lessons, including "{text}"')
def given_lessons(context, text):
    result = context.session["lessons"]
    assert result.code == 0 and result.err == "", result.err
    assert text in result.out and "--- research/lessons.md begins ---" in result.out, result.out


@then("Claude is given nothing by the plugin")
def given_nothing(context):
    for hook, result in context.session.items():
        assert (result.code, result.out, result.err) == (0, "", ""), (hook, result)


def tool_call(context, tool, tool_input):
    event = {"cwd": str(context.workspace), "tool_name": tool, "tool_input": tool_input}
    run_hook(context, "guard", event)


@when('Claude uses {tool} on "{path}"')
def uses_tool(context, tool, path):
    tool_call(context, tool, {"notebook_path" if tool == "NotebookEdit" else "file_path": path})


@when('Claude uses {tool} with the input "{raw}"')
def uses_tool_with(context, tool, raw):
    tool_call(context, tool, json.loads(raw.replace('\\"', '"')))


@when('Claude fetches "{url}"')
def fetches(context, url):
    tool_call(context, "WebFetch", {"url": url})


@given('"{link}" is a link to "{target}"')
def make_link(context, link, target):
    try:
        os.link(context.workspace / target, context.workspace / link)
    except OSError:
        context.scenario.skip("this system can't create links here")


@then('I am asked to approve it, because of "{text}"')
def asked_to_approve(context, text):
    # Only stdout and the exit code count: Claude Code ignores stderr from a hook that exits 0, and a missing
    # python3 writes to it before the fallback runs.
    assert context.result.code == 0, context.result.err
    output = json.loads(context.result.out)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse" and output["permissionDecision"] == "ask", output
    assert text in output["permissionDecisionReason"], output


@then("the tool call goes ahead without a prompt from the plugin")
def no_prompt(context):
    assert (context.result.code, context.result.out, context.result.err) == (0, "", ""), context.result


@when('the {hook} hook is sent "{event}"')
def hook_sent_raw(context, hook, event):
    run_hook(context, hook, event)


# --- the plugin itself ---------------------------------------------------------------------------------------


def skills_dir(context):
    return context.repo / "skills"


def skill_folders(context):
    return sorted(p for p in skills_dir(context).iterdir() if p.is_dir())


def front_matter(path):
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    assert match, f"{path} has no front matter"
    return dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)


@given("the plugin repository")
def plugin_repo(context):
    assert (context.repo / ".claude-plugin" / "plugin.json").exists()


@then("every skill has a SKILL.md whose name is its folder name")
def skill_names(context):
    for folder in skill_folders(context):
        assert front_matter(folder / "SKILL.md").get("name") == folder.name, folder.name


@then("every skill description says when to use it and fits in 1024 characters")
def skill_descriptions(context):
    for folder in skill_folders(context):
        description = front_matter(folder / "SKILL.md").get("description", "")
        assert "Use when" in description or "Use after" in description, folder.name
        assert 20 < len(description) <= 1024, (folder.name, len(description))


@then("no skill refers to the old workspace layout")
def no_old_layout(context):
    for folder in skill_folders(context):
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
        for old in ("paper-research/", ".claude/skills", "rules.md", "read-website-fast"):
            assert old not in text, f"{folder.name} mentions {old}"


@then('the {skill} skill says "{text}"')
def skill_says(context, skill, text):
    path = context.repo / "skills" / skill / "SKILL.md"
    assert text in path.read_text(encoding="utf-8"), f"{skill} lost the instruction: {text}"


@then("the arxiv skill routes reading a paper through the read skill")
def arxiv_routes_reading(context):
    text = (context.repo / "skills" / "arxiv" / "SKILL.md").read_text(encoding="utf-8")
    assert "run `read` to read, summarize, analyze, review, or discuss a paper" in text, (
        "a paper read through arxiv must reach the graph"
    )
    assert "Unless you're already following the `read` skill" in text, "read uses arxiv, so it must not loop"
    description = front_matter(context.repo / "skills" / "arxiv" / "SKILL.md")["description"]
    assert "To read, summarize, analyze, review, or discuss a paper, use the read skill" in description, (
        "Claude picks skills by description"
    )
    read = front_matter(context.repo / "skills" / "read" / "SKILL.md")["description"]
    assert "analyze, review" in read, "'analyze the top 3' must pick read, not arxiv"


PAPER_LIST = "`Published | Title | ID | Citations | Topic | Note`"
PAPER_RULE_LEAD = "- **Paper lists:** whenever you list papers to the user, "


def paper_rule(context):
    """The paper-list rule, as the plugin's rules state it. It is the one source the skills copy word for word."""
    lines = [line for line in rules_text(context).splitlines() if line.startswith(PAPER_RULE_LEAD)]
    assert len(lines) == 1, "the rules must state the paper-list rule once, on one line"
    return lines[0][len(PAPER_RULE_LEAD) :]


@then("every place that lists papers uses the same paper-list table")
def same_paper_list(context):
    # The rules may not be loaded yet, so each skill that shows papers carries the whole rule, not just the
    # column names: with only the names, Claude filled in the ID, Citations, and Note columns its own way.
    rule = paper_rule(context)
    assert PAPER_LIST in rule
    for place in ("arxiv/SKILL.md", "scholar/SKILL.md", "add/SKILL.md", "next/SKILL.md"):
        text = (context.repo / "skills" / place).read_text(encoding="utf-8")
        assert rule in text, f"{place} must carry the paper-list rule of the rules, word for word"


@then("the paper-list rule says what goes in each column")
def paper_rule_columns(context):
    rule = paper_rule(context)
    for part, why in (
        ("`Published` is the publication date as `YYYY-MM-DD`", "one date format"),
        ("or `unknown`; never guess it", "never invent a date"),
        ("`ID` is the paper's `link` from `arxiv` or `scholar`", "the scripts build the link, so it is always one"),
        ("copied as it is so that it stays a link", "a bare id is not a link"),
        ("or the link itself for anything else", "a row without an arXiv or DOI id still has an ID"),
        ("from one `scholar` `batch` call for all the listed papers, made for every list", "never skipped"),
        ("Write `-` only when Semantic Scholar has no count", "a dash never stands for a count not fetched"),
        ("If the call fails, write `?` and say so below the table", "a failed lookup is shown as one"),
        ("the saved count that `graph.py search <id>` shows, with the date it was checked", "dated fallback"),
        ("`Topic` is two to five words", "short topics"),
        ("`Note` is one sentence: the main result, or why the paper matters to this user", "a result, not metadata"),
        ("not details such as the venue, page count, or code", "metadata goes below the table"),
        ("Put the total, caveats, and suggestions below the table", "the table holds only papers"),
    ):
        assert part in rule, why


@then("the init skill has Claude follow the rules in the session that ran it")
def init_loads_rules(context):
    text = (context.repo / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8")
    assert "Follow them for the rest of this session" in text, "rules printed mid-session must be followed at once"
    assert "the plugin loads them on its own" in text, "later sessions get them from the hook"


@then("the plugin's rules route paper reading through the read skill")
def rules_route_reading(context):
    text = rules_text(context)
    assert "**Reading a paper:**" in text, "the rules must send any full read of a paper through `read`"
    assert "**Several papers at once:**" in text, "the rules must extract every paper in a batch"


@then("the plugin's rules send questions about existing notes to the graph")
def rules_ask_the_graph(context):
    rule = next(
        line for line in rules_text(context).splitlines() if line.startswith("- **Check existing notes first:**")
    )
    assert "`graph` skill" in rule, "a question about existing notes must also query the graph"
    for command in ("search", "neighbours", "path"):
        assert f"`{command}`" in rule, f"the rule must name the graph command {command}"


SETUP_DOCS = ("README.md", "docs/getting-started.md", "docs/troubleshooting.md", "skills/init/SKILL.md")


@then("setting up needs no command from the user and no change to their settings")
def setup_needs_nothing(context):
    for name in SETUP_DOCS:
        text = (context.repo / name).read_text(encoding="utf-8")
        for old in (
            "! python",
            "init --dry-run",
            "init.py --dry-run",
            "--sandbox",
            "auto-mode rules",
            "@research/lessons",
        ):
            assert old not in text, f"{name} still describes the old setup: {old}"
    skill = (context.repo / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8")
    assert "you can run it yourself without asking" in skill, "Claude runs init itself"
    assert "never touches `CLAUDE.md` or `.claude/`" in skill, (
        "init must not write Claude's own instructions or settings"
    )


def hook_entries(context, event):
    manifest = json.loads((context.repo / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    (group,) = manifest["hooks"][event]
    return group, group["hooks"]


def check_launcher(command, script, args):
    first, second = command.split(" || ")
    for part, python in ((first, "python3"), (second, "python")):
        assert part == f'{python} "${{CLAUDE_PLUGIN_ROOT}}/{script}" {args}', command


@then("the plugin registers its session and approval hooks")
def plugin_registers_hooks(context):
    import init

    group, entries = hook_entries(context, "SessionStart")
    assert group["matcher"] == "startup|resume|clear|compact", group
    assert [entry["type"] for entry in entries] == ["command", "command"], entries
    for entry, hook in zip(entries, ("rules", "lessons")):
        check_launcher(entry["command"], "skills/init/scripts/init.py", f"--hook {hook}")
    group, (entry,) = hook_entries(context, "PreToolUse")
    assert group["matcher"].split("|") == [*init.EDIT_TOOLS, "WebFetch"], "the matcher must name every guarded tool"
    check_launcher(entry["command"], "skills/init/scripts/init.py", "--hook guard")
    _, (entry,) = hook_entries(context, "Stop")
    check_launcher(entry["command"], "skills/recap/scripts/recap.py", "--stop-hook")


@when("the registered approval hook runs before an edit to the lessons, with python3 {state}")
def guard_through_command(context, state):
    _, (entry,) = hook_entries(context, "PreToolUse")
    event = {"cwd": str(context.workspace), "tool_name": "Edit", "tool_input": {"file_path": "research/lessons.md"}}
    run_registered(context, entry["command"], state, event)


@then("every script a skill refers to exists")
def scripts_exist(context):
    pattern = re.compile(r"<skills>/(\w+)/scripts/([\w.]+)")
    seen = 0
    for folder in skill_folders(context):
        for skill, script in pattern.findall((folder / "SKILL.md").read_text(encoding="utf-8")):
            seen += 1
            assert (skills_dir(context) / skill / "scripts" / script).exists(), f"{folder.name}: {skill}/{script}"
    assert seen >= 5, seen


@then("the manifests are valid and agree on the plugin name")
def manifests(context):
    plugin = json.loads((context.repo / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((context.repo / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert plugin["name"] == market["plugins"][0]["name"] == "paper-research"
    assert re.fullmatch(r"\d+\.\d+\.\d+", plugin["version"]), plugin["version"]
    assert plugin["license"] == "Apache-2.0"


@then("the plugin's rules name every skill")
def rules_name_skills(context):
    rules = rules_text(context)
    for folder in skill_folders(context):
        assert f"`{folder.name}`" in rules, f"rules do not mention {folder.name}"


def script_files(context):
    return [p for p in skills_dir(context).glob("*/scripts/*.py") if not p.name.startswith("test_")]


@then("the scripts import only the Python standard library")
def imported_modules(path):
    """The top-level name of every module a file imports absolutely."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module.split(".")[0]


def stdlib_only(context):
    assert hasattr(sys, "stdlib_module_names"), "needs Python 3.10 or later"
    siblings = {p.stem for p in skills_dir(context).glob("*/scripts/*.py")}
    for path in script_files(context):
        for top in imported_modules(path):
            assert top in sys.stdlib_module_names or top in siblings, f"{path.name} imports {top}"


@then("the scripts name only these hosts: {hosts}")
def only_hosts(context, hosts):
    allowed = {h.strip() for h in hosts.split(",")}
    for path in script_files(context):
        for host in re.findall(r"https?://([A-Za-z0-9.-]+)", path.read_text(encoding="utf-8")):
            assert host in allowed, f"{path.name} names {host}"


@then("the page loads only files shipped next to it")
def page_local(context):
    page = (skills_dir(context) / "recap" / "page" / "recap.html").read_text(encoding="utf-8")
    sources = re.findall(r'<script src="([^"]+)"', page)
    assert sources, "no scripts"
    for source in sources:
        assert not re.match(r"(https?:)?//", source), source
        assert (Path(skills_dir(context) / "recap" / "page") / source).exists() or source == "recap-data.js", source


# --- the documentation ----------------------------------------------------------------------------------


def doc_files(context):
    return [context.repo / "README.md", context.repo / "CONTRIBUTING.md", *sorted((context.repo / "docs").glob("*.md"))]


def heading_slugs(path):
    """The anchors GitHub makes for a file's headings."""
    slugs = set()
    for heading in re.findall(r"^#{1,6} (.+)$", path.read_text(encoding="utf-8"), re.M):
        text = re.sub(r"[`*_]", "", heading).strip().lower()
        slugs.add(re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text)))
    return slugs


@then("every link in the docs points to a file and heading that exist")
def local_links(doc):
    """Each link in a document that points inside the repository."""
    for target in re.findall(r"\]\(([^)\s]+)\)", doc.read_text(encoding="utf-8")):
        if not re.match(r"[a-z]+://|mailto:", target):
            yield target


def check_link(doc, target):
    path, _, anchor = target.partition("#")
    destination = (doc.parent / path).resolve() if path else doc
    assert destination.exists(), f"{doc.name} links to {target}, which does not exist"
    if anchor:
        assert anchor in heading_slugs(destination), f"{doc.name} links to {target}, but no heading matches"


def docs_links(context):
    checked = 0
    for doc in doc_files(context):
        for target in local_links(doc):
            check_link(doc, target)
            checked += 1
    assert checked >= 30, checked


@then("the docs describe every skill")
def docs_skills(context):
    text = (context.repo / "docs" / "skills.md").read_text(encoding="utf-8")
    for folder in skill_folders(context):
        pattern = rf"^## .*(?<![A-Za-z0-9_]){folder.name}(?![A-Za-z0-9_])"
        assert re.search(pattern, text, re.M), f"docs/skills.md has no section for {folder.name}"


@then('only the path of "{name}" is printed')
def only_the_path(context, name):
    assert Path(context.result.out.strip()).resolve() == (context.workspace / name).resolve(), context.result.out[:200]


@then('the file "{name}" holds {count:d} papers')
def file_holds_papers(context, name, count):
    saved = json.loads((context.workspace / name).read_text(encoding="utf-8"))
    papers = saved["papers"] if isinstance(saved, dict) and "papers" in saved else saved
    assert len(papers) == count, saved


@then('the file "{name}" has no abstracts')
def file_has_no_abstracts(context, name):
    saved = json.loads((context.workspace / name).read_text(encoding="utf-8"))
    assert all("abstract" not in paper for paper in saved["papers"]), saved


def documented_types(cell):
    """The entity types a docs cell names: a list of types, "a work", or "any type"."""
    import graph

    if cell.startswith("a work"):
        return graph.WORKS
    if cell.startswith("any type"):
        return graph.ENTITY_TYPES
    return {name.strip() for name in cell.split(",")}


@then("the documented relation table matches the rules the script enforces")
def documented_relation_table(context):
    """docs/knowledge-graph.md says which entity types each relation joins; graph.RELATION_ENDS must agree."""
    import graph

    text = (context.repo / "docs" / "knowledge-graph.md").read_text(encoding="utf-8")
    start = text.index("| Relation | From | To |")
    table = text[start : text.index("\n\n", start)]
    documented = {}
    for row in table.splitlines()[2:]:
        relations, source, target = [cell.strip() for cell in row.strip("|").split("|")]
        for rel in re.findall(r"`([a-z-]+)`", relations):
            documented[rel] = (documented_types(source), documented_types(target))
    assert documented == dict(graph.RELATION_ENDS), (documented, graph.RELATION_ENDS)


@then("the command reference lists every command of {script}")
def docs_commands(context, script):
    out = context.run_script(script, ["--help"]).out
    commands = re.search(r"\{([a-z,-]+)\}", out).group(1).split(",")
    reference = (context.repo / "docs" / "reference.md").read_text(encoding="utf-8")
    for command in commands:
        assert f"`{command} " in reference or f"`{command}`" in reference, f"reference.md misses {script} {command}"


@then("the command reference lists every option of init")
def docs_init_options(context):
    out = context.run_script("init", ["--help"]).out
    reference = (context.repo / "docs" / "reference.md").read_text(encoding="utf-8")
    for option in re.findall(r"(--[a-z-]+)", out):
        if option != "--help":
            assert option in reference, f"reference.md misses init {option}"
