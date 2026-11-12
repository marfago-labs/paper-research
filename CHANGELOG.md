# Changelog

All notable changes to the plugin are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version numbers follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
