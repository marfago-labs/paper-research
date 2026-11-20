# Changelog

All notable changes to the plugin are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version numbers follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A local telemetry stack for debugging: `telemetry/docker-compose.yml` runs Grafana with an OpenTelemetry
  collector on `127.0.0.1`, and [Telemetry](docs/telemetry.md) shows how to send Claude Code's events, metrics, and
  traces to it, and what to look for.

### Changed

- Setting up a workspace is one step that Claude runs: `/paper-research:init` creates the starter files in
  `research/` and `.gitignore` entries, and never touches `CLAUDE.md` or `.claude/`. There is no `!` command to run,
  and nothing to run after an update.
- The plugin's rules and `research/lessons.md` come from two `SessionStart` hooks, at the start of every session and
  after the conversation is compacted, in any folder with `research/user-facts.md`. They used to be a block in
  `CLAUDE.md`.
- Approval prompts come from a `PreToolUse` hook instead of ask rules in `.claude/settings.json`. It asks before an
  edit to `research/lessons.md` or `research/profile.md` of any workspace, matching the file itself rather than its
  spelling, and before a fetch from `arxiv.org`, `export.arxiv.org`, `api.semanticscholar.org`, `huggingface.co`,
  `github.com`, or `api.github.com`, reading the host the way a browser does. If it can't tell which file or address
  a call uses, it asks. It no longer covers `CLAUDE.md` and `.claude/`, which are left to Claude Code, and no
  auto-mode rules are written.

### Removed

- `init --dry-run` and `init --sandbox`. To use the sandbox, add the settings that the security page shows.

To update a workspace set up with 0.3.0 or earlier, delete the block between the `paper-research:begin` and
`paper-research:end` lines in `CLAUDE.md`, and the `permissions.ask` and `autoMode.soft_deny` entries that `init`
added to `.claude/settings.json`. Otherwise the old rules load as well.

## [0.3.0] - 2026-11-17

### Added

- CI writes a complexity report to the job summary: for Python and JavaScript, the number of functions, the mean
  and highest cyclomatic and cognitive complexity, and the ten functions closest to the limits, so one that is creeping
  up is seen before it fails.
- A `Stop` hook (`hooks/hooks.json`) that checks the recap when Claude finishes a turn in a paper workspace. If a
  file the recap is built from changed since the page was last written, or the page was never written but the
  starter files were changed, it stops Claude once. Claude is told to log the session's questions and facts that are
  not yet in `research/user-facts.md`, including those from turns that changed no files, and to refresh the page
  with the `recap` skill. Before, both steps were rules in `CLAUDE.md` that a long chain of skills could drop. The
  command runs `recap.py --stop-hook` with `python3`, and falls back to `python`. It reads only the research files,
  writes nothing, and never asks twice in a turn.
- `arxiv.py search --until` limits results to papers submitted on or before a date, with `--since` for a range.
- `arxiv.py fetch --all-sections` lists every heading. By default `fetch` lists the title, the abstract, and the
  numbered sections, and says how many deeper headings there are, so a long paper's output stays short.
- `--brief` on `arxiv.py search` leaves out the abstracts, which are most of its output. `--out FILE` on `arxiv.py`
  `search` and `paper`, and on every `s2.py` command, saves the JSON to a file as UTF-8 and prints only its path.
  The file must be inside `research/`, or in a temporary folder outside the workspace (the system's, and `/tmp`
  outside Windows; a `.json` or `.txt` file there). It is never `CLAUDE.md`, `.mcp.json`, `lessons.md`, `profile.md`, or a file
  inside `.claude/` or `.git/`, in any letter case and in any project. `graph.py standing-due` follows the same rule
  for the file it writes.
- `graph.py link` refuses a relation between entity types it can't join, such as a concept `authored-by` an author,
  and says which types the relation joins. `graph.py validate` lists older links between the wrong types without
  blocking the graph.

### Changed

- The plugin is licensed under Apache 2.0 instead of MIT, with a `NOTICE` file. Versions 0.1.0 and 0.2.0,
  released under MIT, are also available under Apache 2.0.
- The docs gain `docs/architecture.md`, with a component diagram, what each part writes, the trust boundaries,
  and the design decisions. The README is shorter and shows the recap page's graph: the paper-to-graph diagram
  moved to `docs/knowledge-graph.md`, and the protections table and workspace layout to `docs/security.md` and
  `docs/workspace.md`. CONTRIBUTING says mutation tests run locally.
- The `read` skill extracts every dataset, model, method, tool, and concept with a role in the paper, including the
  baselines it compares against and the models it runs or uses as judges, and adds the paper's authors if they're
  missing. A name cited only in related work is still skipped. `graph.py validate` lists any paper with no
  `authored-by` link, and `read` runs it, so missing authors are caught in the same turn. A work with no author to
  record, such as an anonymous submission, says why with `graph.py update --no-authors`. `validate` shows each
  such reason, and the reason is dropped when the paper gets an author. In a graph with papers saved
  without authors, the first `read` adds the authors of all of them, which can take one longer turn.

- `arxiv.py` and `s2.py` remove invisible characters (tag characters, variation selectors outside the emoji range,
  zero-width spaces, direction marks and overrides, the deprecated format characters, interlinear annotation
  anchors, and the byte order mark) from every title, abstract, summary, author name, and field name they print or
  save with `--out`, in every command. The count goes to the error output, and the `arxiv` and `scholar` skills tell
  Claude to tell the user when tag characters or variation selectors were among them. Before, only `arxiv.py fetch`
  cleaned the text it saved. Both scripts use one function: `s2.py` now takes `write_output` from `arxiv.py`. Joiners
  and emoji selectors stay.
- `graph.py unlink` and `graph.py remove` warn about each entity other than a paper that they leave with no links.
  They still succeed, and `graph.py validate` lists any that are left.
- `graph.py add` saves an entity with its first link, given with `--link-from ENTITY REL` or `--link-to REL ENTITY`
  and `--source` and `--status`. Every type but a paper needs one, so an entity can no longer be left with no
  link when a later `link` is skipped or fails. `graph.py validate` lists any entity other than a paper with no
  links, and the `read` skill runs it after each extraction.
- The recap page's Activity tab lists every line of `user-facts.md` with its type, not only the questions. A question
  that was logged as an interest used to be missing from the page.
- With the sandbox on, `init` also stops sandboxed shell commands from writing anything in `.claude/`, where the
  settings and approval rules live. Run `init` again to add it to an existing sandbox. Claude Code's file tools were
  already covered by an approval prompt.
- Without an API key, the `scholar` skill says how to rank papers when `search` is refused: find candidates with
  `arxiv` `search`, look up their citation counts in one `batch` call, and say that the queries decided what could
  appear. It also says that a free API key gives a better answer, and that counts for recent papers show early
  traction, not influence.
- The `read` skill checks papers that came from a search or a ranking before reading them, stops to ask when a text is
  far longer than a paper or has chapters, reads a long work chapter by chapter, and says whether a Hugging Face
  download count is for all time or the last 30 days. The `next` skill checks each pick the same way.
- Without an API key, `s2.py search` reports an `HTTP 429` at once instead of retrying for up to 90 seconds, so
  the switch to arXiv search is quick. Other commands still retry.
- The `read` skill searches for code and data by the paper's title, says "not searched" for any place it couldn't
  search, and says which parts of the paper it read, marking claims from unread parts as unverified.
- The `add` skill keeps Semantic Scholar's spelling of an author's name, and adds arXiv's spelling as an alias.
- The `next` and `scholar` skills use a search with a year or date range for "similar papers from a period",
  because recommendations can't be limited to dates.

### Fixed

- The docs describe the current graph flow (each entity added with its first link, relation types checked,
  `validate` after each extraction), the `Stop` hook, and the invisible characters the scripts remove from what they
  print. Troubleshooting covers the new graph messages, and the test commands include `tools/test_*.py`.

## [0.2.0] - 2026-11-12

### Added

- Citation standing: a paper in the knowledge graph can keep its citation count, influential citations, venue,
  and year, with the date they were checked. The recap page shows them, how often a paper comes up in your own
  collection, and a menu to sort papers by reading status, most cited, most cited per year, or most connected.
- `s2.py batch --ids-file` sends any number of papers, 500 at a time, and keeps what it fetched if a later request
  fails.
- `s2.py batch --with-references` also fetches each paper's reference list. `graph.py standing` then saves the
  counts and adds a `cites` link from each paper to every paper in the graph that it cites, so reading a paper
  takes one Semantic Scholar request instead of three. `graph.py standing-due` lists the papers whose counts are
  missing or old.
- One table for every list of papers, with the columns `Published | Title | ID | Citations | Topic | Note`. Each
  paper from `arxiv.py` and `s2.py` comes with a ready `link` for the ID column, and the whole rule is in the
  workspace rules and in each skill that lists papers.
- `graph.py search` shows a paper's saved citation count and the date it was checked.
- `fetch` and `pdf` print a `next` reminder to follow the `read` skill, so a paper fetched any other way still
  reaches `research/papers.md` and the graph.
- `tools/run_mutation.py --workers N` tests N mutants at once.

### Changed

- `graph.py link` refuses a `verified` link whose source names no document, such as a reason in prose. Mark it
  `inferred` instead. `graph.py validate` lists older links that break the rule and exits with 1, without
  blocking the other commands.
- The `read` and `arxiv` skills name "analyze" and "review" as reasons to use `read`.
- The `read` skill chooses each link's status on its own, and reports a failed citation step in the same reply,
  with the error.
- The recap page says "nothing extracted yet" for a paper that was saved but never read.
- Every module is held at 0% surviving mutants.

### Fixed

- `tools/hooks/pre-commit` and `tools/gitleaks.py` are executable again. Git ignores a hook that isn't
  executable, so the secret scan didn't run for contributors on Linux and macOS.

## [0.1.0] - 2026-11-11

First release: the `arxiv`, `scholar`, `read`, `add`, `next`, `pin`, `insight`, `graph`, `recap`, and `init`
skills, with plain-file notes in the workspace, a knowledge graph with duplicate checks, and the recap page.

[Unreleased]: https://github.com/marfago-labs/paper-research/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/marfago-labs/paper-research/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/marfago-labs/paper-research/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/marfago-labs/paper-research/releases/tag/v0.1.0
