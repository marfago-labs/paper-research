"""Steps for the recap and init features."""

import json
import os
import re
import shutil
import subprocess

from behave import given, then, when

import recap


def research(context):
    return context.workspace / "research"


@when("the turn ends")
def turn_ends(context):
    context.run_script("recap", ["--stop-hook"], stdin=json.dumps({"cwd": str(context.workspace)}))


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


@then("the recap folder holds the page, its script library, and the data")
def recap_folder(context):
    names = sorted(p.name for p in (research(context) / "recap").iterdir())
    assert names == sorted([*recap.PAGE_FILES, "recap-data.js"]), names


@given('the file "{name}" contains the text "{text}"')
def given_file(context, name, text):
    target = context.workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace('\\"', '"').replace("\\n", "\n"), encoding="utf-8")


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


@then('the file "{name}" is still "{text}"')
def file_unchanged(context, name, text):
    want = text.replace('\\"', '"').replace("\\n", "\n")
    assert (context.workspace / name).read_text(encoding="utf-8") == want, name


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


def tool_call(context, tool, tool_input):
    event = {"cwd": str(context.workspace), "tool_name": tool, "tool_input": tool_input}
    run_hook(context, "guard", event)


@when('Claude uses {tool} on "{path}"')
def uses_tool(context, tool, path):
    tool_call(context, tool, {"notebook_path" if tool == "NotebookEdit" else "file_path": path})


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


# --- what the recap page shows, made from the data recap.py wrote -------------------------------------------

# Loads the data as the page does, and prints the HTML its own library makes of it for the Activity tab.
RENDER = (
    'const fs = require("fs"), vm = require("vm"); const window = {};'
    ' vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), { window });'
    " process.stdout.write(require(process.argv[2]).buildRecap(window.RECAP_DATA).html);"
)


def recap_html(context):
    node = shutil.which("node")
    assert node, "these steps run the page's library, which needs Node"
    page = research(context) / "recap"
    done = subprocess.run(
        [node, "-e", RENDER, str(page / "recap-data.js"), str(page / "recap-lib.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def papers_under(html, heading):
    found = re.search(rf"<h3>{re.escape(heading)} \(\d+\)</h3><ul>(.*?)</ul>", html)
    return found.group(1) if found else ""


@given('the reading list holds "{title}" as {paper_id} with the status {status}')
def reading_list_row(context, title, paper_id, status):
    row = f"| 2026-11-23 | {title} | {paper_id} | {status} | - | test | A summary. |\n"
    with open(research(context) / "papers.md", "a", encoding="utf-8") as handle:
        handle.write(row)


@then("the Activity tab counts {count:d} {label}")
def activity_counts(context, count, label):
    html = recap_html(context)
    assert f"<b>{count}</b><span>{label}</span>" in html, html[:600]


@then('the Activity tab lists "{title}" under "{heading}"')
def activity_lists(context, title, heading):
    listed = papers_under(recap_html(context), heading)
    assert f">{title}</a>" in listed, f"{title!r} not under {heading!r}: {listed!r}"


@then('the Activity tab does not list "{title}" under "{heading}"')
def activity_does_not_list(context, title, heading):
    listed = papers_under(recap_html(context), heading)
    assert f">{title}</a>" not in listed, f"{title!r} is under {heading!r}: {listed!r}"


# --- the plugin itself ---------------------------------------------------------------------------------------


# --- the documentation ----------------------------------------------------------------------------------
