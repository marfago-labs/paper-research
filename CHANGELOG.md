# Changelog

All notable changes to the plugin are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version numbers follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `arxiv.py search --until` limits results to papers submitted on or before a date, with `--since` for a range.
- `arxiv.py fetch --all-sections` lists every heading. By default `fetch` lists the title, the abstract, and the
  numbered sections, and says how many deeper headings there are, so a long paper's output stays short.
- `--brief` on `arxiv.py search` leaves out the abstracts, which are most of its output. `--out FILE` on `arxiv.py`
  `search` and `paper`, and on every `s2.py` command, saves the JSON to a file as UTF-8 and prints only its path.
  The file must be inside `research/`, or in a temporary folder outside the workspace (the system's, and `/tmp`
  outside Windows; a `.json` or `.txt` file there). It is never `CLAUDE.md`, `.mcp.json`, `lessons.md`, `profile.md`, or a file
  inside `.claude/` or `.git/`, in any letter case and in any project. `graph.py standing-due` follows the same rule
  for the file it writes.

### Changed

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

[Unreleased]: https://github.com/marfago-labs/paper-research/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/marfago-labs/paper-research/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/marfago-labs/paper-research/releases/tag/v0.1.0
