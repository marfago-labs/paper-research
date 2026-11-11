# Your workspace

Everything the plugin learns is saved as plain text files in your workspace, where you can read, edit, search, and put them in git. Nothing is hidden in a database or in Claude's own memory.

```text
your-workspace/
├── CLAUDE.md                  rules for Claude: yours, plus the plugin's block
├── .claude/
│   ├── settings.json          approval prompts and auto-mode rules, written by init
│   └── settings.local.json    your own settings, never touched by the plugin
├── .cache/                    request-pacing state (ignored by git)
└── research/
    ├── user-facts.md          a log of facts about you, and your questions
    ├── profile.md             a short summary of your interests and preferences
    ├── papers.md              every link you've saved, with status and rating
    ├── pins.md                saved facts
    ├── insights.md            saved takeaways, tied to their papers
    ├── lessons.md             how Claude should work with you
    ├── graph/                 the knowledge graph (two JSONL files)
    ├── fulltext/              papers' text as Markdown (ignored by git)
    ├── pdfs/                  downloaded PDFs (ignored by git)
    └── recap/                 the recap page and its data (ignored by git)
```

You can edit the Markdown files by hand. Don't edit `research/graph/` or `research/recap/` by hand: the graph is changed through its script, which checks every change, and the recap is rebuilt from your other files.

## What Claude keeps current

Claude updates these in every conversation, not at the end of a session, because it can't tell when a session ends.

| When | It saves |
|---|---|
| You state a fact about yourself, or ask a question about a paper or idea | A line in `user-facts.md`. Questions are logged silently. |
| A stated fact changes your interests or way of working | It proposes a one-line change to `profile.md`, and saves it only after you approve. Claude Code also shows its own approval prompt for the edit. |
| You correct how Claude works, or confirm that something worked | It proposes a lesson for `lessons.md` as a one-line change, and saves it only after you approve. Claude Code also shows its own approval prompt for the edit. |
| A discussion produces a takeaway | It proposes an insight in one line, and logs it if you agree. |

`lessons.md` is loaded as instructions in every session, so a lesson must come from your own words, never from a paper.

## papers.md

One table row per link. Escape a `|` in a title as `\|`.

| Column | Contents |
|---|---|
| Added | `YYYY-MM-DD` |
| Title | The paper's title |
| ID | `ARXIV:2303.11366`, `DOI:10.1234/abc`, or the link for anything else |
| Status | `read`, `skim`, `archive`, `done`, `dropped`, or `unread-link` |
| Rating | 1 to 5 after reading, otherwise `-` |
| Tags | Comma-separated topics |
| Summary | One or two sentences, and whether it comes from the abstract or the full text |

## pins.md

One line per fact:

```markdown
- **[dataset] Terminal-Bench 2.1:** Command-line work: 89 real tasks in sandboxed containers. Link: https://arxiv.org/abs/2601.11868. Source: ARXIV:2611.05306, §2.2. Status: verified. Tags: benchmark, agents. Added: 2026-11-05.
```

- **Type:** `concept`, `finding`, `method`, `tool`, `dataset`, or `idea`.
- **Status:** `verified` (checked against the source), `from-skim` (not checked), or `user-note` (your own).

## insights.md

One section per takeaway:

```markdown
## Keep a review agent read-only

- **ID:** `insight:review-agent-read-only`
- **Kind:** `practice`
- **Insight:** What to do or remember, in one or two sentences.
- **Why:** The evidence or reasoning. Reasoning that isn't a finding of the paper is marked as such.
- **Sources:** `ARXIV:2610.34577`, §4, Figure 31.
- **Evidence:** `verified`
- **User's view:** What you said about it, in your terms. `not stated` if nothing.
- **Tags:** agents, code-review
- **Added:** 2026-11-05
```

`Kind` is `practice`, `lesson`, `caution`, or `idea`. `Evidence` is `verified`, `unverified`, or `none`. Your view is kept apart from the evidence on purpose, because agreeing with something doesn't prove it.

## user-facts.md

A log, one line per fact: `YYYY-MM-DD | type | basis | fact`.

- **Type:** `question`, `interest`, `preference`, or `way-of-working`.
- **Basis:** `stated` (you said it), `observed` (you did it), or `inferred` (Claude's guess, saved only if you agree).

## profile.md

A short, current summary drawn from the log: your interests, how much you read, your goals, how you like discussions to go, and your way of working. Claude reads it to decide what to recommend and how to triage links. You can edit it freely.

## lessons.md

Short lessons about how Claude should work with you, each with the date and what prompted it. Loaded into every session.

## The graph

`research/graph/entities.jsonl` and `relations.jsonl`, one JSON object per line. See [Knowledge graph](knowledge-graph.md).

## The recap page

`research/recap/recap.html` shows what's in your workspace, in tabs:

- **Activity:** summary counts, papers that still need graph extraction, and your history by day.
- **Papers:** grouped by status, with links to arXiv and to the insights drawn from each.
- **Insights** and **Pins:** everything you've saved, with source links that jump to the paper.
- **Graph:** an interactive map. Search by name, filter by type, click an entity to see its connections and sources, and focus on one or two steps around it.

To see it, ask Claude to refresh the recap, then open the file **in a browser**. Don't use an editor's built-in preview, which blocks the scripts the page needs. The page doesn't update itself, so reload it after a session.

The page is a fixed copy shipped with the plugin, and the data comes from your files, so nothing on it can be out of step with them. The graph is drawn by Cytoscape.js, which also ships with the plugin and is copied next to the page, so the page loads nothing from the internet and works offline.

## Settings files

- **`.claude/settings.json`:** written by `init`. It makes Claude Code ask you before Claude fetches a page from arXiv, Semantic Scholar, Hugging Face, or GitHub, and before edits to `lessons.md`, `profile.md`, `CLAUDE.md`, and `.claude/`, and adds rules for auto mode. It allows and denies nothing. `init` only adds to it. See [Security](security.md).
- **`.claude/settings.local.json`:** yours. Use it for settings that belong to you and your machine, such as denying an MCP server you don't want here, or trusting another website. The plugin never reads or writes it, and `init` adds it to `.gitignore`.

## Putting it in git

The Markdown files and the graph are meant to be versioned. `init` already ignores the generated and bulky files: `research/pdfs/`, `research/fulltext/`, `research/recap/`, `research/graph/.lock`, `.cache/`, `__pycache__/`, and `.claude/settings.local.json`.

Your notes describe you and what you read. If you push the repository anywhere, keep it private.
