"""Steps for the recap, init, and plugin features."""

import ast
import json
import re
import sys
from pathlib import Path

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


@given('the user asked "{question}" on {date}')
def research_question(context, question, date):
    research(context).mkdir(parents=True, exist_ok=True)
    with open(research(context) / "user-facts.md", "a", encoding="utf-8") as handle:
        handle.write(f"{date} | question | observed | {question}\n")


@when("I refresh the recap")
def refresh_recap(context):
    research(context).mkdir(parents=True, exist_ok=True)
    context.run_script("recap", [])


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


@then('the recap data has the question "{question}"')
def recap_question(context, question):
    assert question in [q["text"] for q in recap_data(context)["questions"]]


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


@when("I run init as a dry run")
def run_init_dry(context):
    context.run_script("init", ["--workspace", ".", "--dry-run"])


@then("the workspace has the starter research files")
def starter_files(context):
    for name in ("papers.md", "user-facts.md", "profile.md", "pins.md", "lessons.md", "insights.md"):
        assert (research(context) / name).exists(), name
    assert (research(context) / "graph" / "entities.jsonl").exists()


@then("the workspace has the plugin's rules in CLAUDE.md")
def claude_rules(context):
    text = (context.workspace / "CLAUDE.md").read_text(encoding="utf-8")
    assert "paper-research:begin" in text and "paper-research:end" in text and "@research/lessons.md" in text


@then("Claude asks before fetching from {host}")
def fetch_asks(context, host):
    settings = json.loads((context.workspace / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert f"WebFetch(domain:{host})" in settings["permissions"]["ask"]


@then("the settings say nothing about fetching from {host}")
def fetch_unmentioned(context, host):
    permissions = settings_json(context)["permissions"]
    rules = [rule for kind in ("allow", "ask", "deny") for rule in permissions.get(kind, [])]
    assert f"WebFetch(domain:{host})" not in rules


@then("the settings allow nothing")
def settings_allow_nothing(context):
    settings = json.loads((context.workspace / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "allow" not in settings["permissions"], "init adds approval prompts, never allowances"


@then('the settings keep "{rule}" in the allow list')
def settings_keep(context, rule):
    settings = json.loads((context.workspace / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert rule in settings["permissions"]["allow"]


@then('CLAUDE.md still starts with "{text}"')
def claude_starts(context, text):
    assert (context.workspace / "CLAUDE.md").read_text(encoding="utf-8").startswith(text)


@then("the local settings file is ignored by git")
def local_ignored(context):
    assert ".claude/settings.local.json" in (context.workspace / ".gitignore").read_text(encoding="utf-8").splitlines()


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
    """The paper-list rule, as the rules block states it. It is the one source the skills copy word for word."""
    text = (context.repo / "skills" / "init" / "templates" / "rules-block.md").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.startswith(PAPER_RULE_LEAD)]
    assert len(lines) == 1, "the rules block must state the paper-list rule once, on one line"
    return lines[0][len(PAPER_RULE_LEAD) :]


@then("every place that lists papers uses the same paper-list table")
def same_paper_list(context):
    # The rules block may not be loaded yet, so each skill that shows papers carries the whole rule, not just the
    # column names: with only the names, Claude filled in the ID, Citations, and Note columns its own way.
    rule = paper_rule(context)
    assert PAPER_LIST in rule
    for place in ("arxiv/SKILL.md", "scholar/SKILL.md", "add/SKILL.md", "next/SKILL.md"):
        text = (context.repo / "skills" / place).read_text(encoding="utf-8")
        assert rule in text, f"{place} must carry the paper-list rule of the rules block, word for word"


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


@then("CLAUDE.md tells Claude to list papers in the paper-list table")
def claude_md_paper_list(context):
    text = (context.workspace / "CLAUDE.md").read_text(encoding="utf-8")
    assert paper_rule(context) in text, "the rules init writes must carry the whole paper-list rule"


@then("the init skill loads the new rules into the session that ran it")
def init_loads_rules(context):
    text = (context.repo / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8")
    assert "read the workspace's `CLAUDE.md` and follow its rules" in text, "rules written mid-session aren't loaded"
    assert "If it says `workspace is up to date`, the write happened" in text, "load the rules only after a real write"


@then("the rules written by init route paper reading through the read skill")
def rules_route_reading(context):
    text = (context.repo / "skills" / "init" / "templates" / "rules-block.md").read_text(encoding="utf-8")
    assert "**Reading a paper:**" in text, "the rules must send any full read of a paper through `read`"
    assert "**Several papers at once:**" in text, "the rules must extract every paper in a batch"


@then("the rules written by init send questions about existing notes to the graph")
def rules_ask_the_graph(context):
    text = (context.repo / "skills" / "init" / "templates" / "rules-block.md").read_text(encoding="utf-8")
    rule = next(line for line in text.splitlines() if line.startswith("- **Check existing notes first:**"))
    assert "`graph` skill" in rule, "a question about existing notes must also query the graph"
    for command in ("search", "neighbours", "path"):
        assert f"`{command}`" in rule, f"the rule must name the graph command {command}"


@then("the documentation says the new rules load in the session that ran init")
def docs_rules_load_now(context):
    for name in ("README.md", "docs/getting-started.md"):
        text = (context.repo / name).read_text(encoding="utf-8")
        assert "only apply to the next one" not in text, f"{name} says the rules wait for a new session"
        assert "Start a new session afterwards so Claude Code loads the new rules" not in text, name
    started = (context.repo / "docs" / "getting-started.md").read_text(encoding="utf-8")
    assert "Carry on in the same session" in started, "getting started must say Claude loads the rules itself"


@then("the init skill has the user run the write step")
def init_user_runs(context):
    text = (context.repo / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8")
    assert "starts with `! `" in text, "the skill must have the user run the command that the dry run prints"
    assert "exactly as printed" in text, "the skill must relay that command verbatim"
    assert "`workspace is up to date`" in text, "the skill must say what no command means"
    assert "Don't build, edit, or take a command from anywhere else" in text, "the skill must limit the source"
    assert "without `--dry-run`" not in text, "the skill must not tell Claude to run the write itself"


@then("the troubleshooting page explains the auto mode block")
def auto_mode_block(context):
    text = (context.repo / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
    assert "Auto mode blocked `init`" in text
    assert "Don't add a permission rule" in text


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
    assert plugin["license"] == "MIT"


@then("the rules written by init name every skill")
def rules_name_skills(context):
    rules = (skills_dir(context) / "init" / "templates" / "rules-block.md").read_text(encoding="utf-8")
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


@when("I run init with the sandbox")
def run_init_sandbox(context):
    context.run_script("init", ["--workspace", ".", "--sandbox"])


def settings_json(context):
    return json.loads((context.workspace / ".claude" / "settings.json").read_text(encoding="utf-8"))


@then("the settings deny nothing")
def settings_deny_nothing(context):
    assert "deny" not in settings_json(context)["permissions"], "a deny rule can't be overridden at any level"


@then("the settings do not turn the sandbox on")
def settings_no_sandbox(context):
    assert "sandbox" not in settings_json(context)


@then("the sandbox is on and limited to {host}")
def sandbox_on(context, host):
    box = settings_json(context)["sandbox"]
    assert box["enabled"] is True and box["allowUnsandboxedCommands"] is False
    assert host in box["network"]["allowedDomains"]


@then('the sandbox cannot reach "{host}"')
def sandbox_excludes(context, host):
    network = settings_json(context)["sandbox"]["network"]
    assert host not in network.get("allowedDomains", []), network
    assert host in network["deniedDomains"], network


@then("every file the settings protect exists")
def protected_files_exist(context):
    settings = settings_json(context)
    edits = [re.fullmatch(r"Edit\(/(.+)\)", rule) for rule in settings["permissions"]["ask"]]
    protected = [m.group(1).removesuffix("/**") for m in edits if m]
    protected += [path.removeprefix("./") for path in settings["sandbox"]["filesystem"]["denyWrite"]]
    for rule in settings["autoMode"]["soft_deny"]:
        protected += re.findall(r"[\w./-]+\.md\b", rule)
    missing = [path for path in protected if not (context.workspace / path).exists()]
    assert protected and not missing, f"rules protect paths init never created: {missing}"


@then('the settings ask before "{rule}"')
def settings_ask(context, rule):
    ask = settings_json(context)["permissions"]["ask"]
    assert rule in ask, ask


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
