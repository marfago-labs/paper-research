# Contributing

## Layout

Each skill is a folder in `skills/` with a `SKILL.md`. Scripts live in the skill that owns them, under `scripts/`, with their tests beside them. Skills reach each other's scripts as `<skills>/<name>/scripts/...`, where `<skills>` is the folder that contains a skill's base directory. Scripts run from the user's workspace root and find `research/` and `.cache/` there.

| Folder | Holds |
|---|---|
| `skills/` | The skills, their scripts, and the unit tests beside the scripts |
| `skills/recap/page/` | The recap page, its rendering library, and their Node tests |
| `docs/` | The user documentation. Keep it in step with the skills and scripts: a scenario checks that its links resolve and that every skill and command is covered |
| `features/` | Behaviour scenarios in Gherkin, run with `behave` |
| `evals/dedup/` | The duplicate-detection evaluation, not shipped to users: its specification (`SPEC.md`), the dataset builder, `audit_labels.py` (asks Jev, through OpenRouter, whether second names are the same thing; run by hand with `build_dataset.py --audit`, never in CI), `evaluate.py` (replays the pairs through `graph.py`'s check and reports the rates), `hand_check.py` (the sheet for the hand check of the labels, and its scorer), the frozen pairs in `data/`, and `analysis.ipynb`, which describes the dataset and what the evaluation finds. The notebook needs pandas and matplotlib, which the project doesn't install, and CI doesn't run it: run it by hand after any change to the dataset |
| `mutation/` | One cosmic-ray configuration per script |
| `tools/` | Development helpers that are not shipped to users, including the gitleaks wrapper and the pre-commit hook |
| `.github/workflows/ci.yml` | Lint, static analysis, unit tests, coverage, and behaviour scenarios, on every push and pull request |
| `.github/workflows/mutation.yml` | Mutation tests, weekly and on request |

## Rules for changes

- **Standard library only** at run time. Development tools are listed in `requirements-dev.in` and `tools/js/package.json`, installed with hashes checked, and never become plugin dependencies. Keep `package.json` out of the repository root: Claude Code runs an npm install for a `package.json` at the plugin root when someone installs the plugin.
- **Package, not workspace:** nothing about one user, their papers, or their machine goes in this repo.
- **Coverage stays at 100%,** lines and branches, for every script and for `recap-lib.js`.
- **A change that makes `name_key` merge more names needs a repair path.** Validation refuses a graph in which two entities of one type share a key, and every command, `merge` included, loads through validation. So a key that merges names an older key kept apart can stop an existing graph from loading, with no command left to fix it. Ship such a change with a migration, or with a way to load the graph and merge the clashing pairs.
- **Functions stay simple:** cyclomatic complexity at most 6 and cognitive complexity at most 10, in Python and JavaScript, tests included. ruff (`C901`) and ESLint (`complexity`) check the first, complexipy and `sonarjs/cognitive-complexity` the second. Split a function rather than raising a limit. The inline script in `recap.html` isn't linted, so keep it small.
- **Every behaviour a user relies on** gets a scenario in `features/`, written in the user's words.
- **A change a user can see updates the docs** in the same commit: a new skill, command, option, file, or message. It also adds a line under `[Unreleased]` in `CHANGELOG.md`. Only a release changes the version: see [Releases](#releases).
- **Tests never use made-up absolute paths** such as `/no/such/folder`. Build a missing path inside a temporary folder. A mutant that skips a check can otherwise create real folders on the developer's machine.
- **Cytoscape.js is the only vendored file.** To update it, take `dist/cytoscape.min.js` and its licence from the npm release, put the version in the file name, and update the name in `recap.py`, `recap.html`, the recap tests, `features/steps/workspace_steps.py`, and `docs/troubleshooting.md`. Update the version, hash, and check command in [Security](docs/security.md#third-party-code).
- **Rules the user's agent follows** go in `skills/init/templates/rules-block.md` if they apply in every session, or in the skill that needs them.

## Checks

CI runs all of these. Run them locally before pushing:

```bash
pip install --require-hashes -r requirements-dev.txt && npm ci --prefix tools/js

ruff check skills tools features evals && ruff format --check skills tools features evals   # lint
mypy skills/graph/scripts/graph.py skills/recap/scripts/recap.py skills/arxiv/scripts/arxiv.py \
     skills/scholar/scripts/s2.py skills/init/scripts/init.py tools \
     evals/dedup/build_dataset.py evals/dedup/audit_labels.py evals/dedup/evaluate.py \
     evals/dedup/hand_check.py                                                    # types
bandit -q -r skills -x "*/test_*.py"                                             # security
python tools/gitleaks.py                                                         # secrets, every commit
complexipy skills tools features evals --max-complexity-allowed 10               # cognitive complexity
npm run lint --prefix tools/js                                                   # ESLint, complexity
npm run format:check --prefix tools/js                                           # Prettier (npm run format fixes)

for t in skills/*/scripts/test_*.py evals/*/test_*.py; do python "$t"; done      # unit tests
python evals/dedup/evaluate.py --split dev                                       # duplicate detection
npm test --prefix tools/js && npm run coverage --prefix tools/js                 # page tests, 100%
coverage run --branch --include="*/graph.py" skills/graph/scripts/test_graph.py && coverage report --fail-under=100
behave features                                                                  # behaviour

python tools/run_mutation.py init --max-survival 0 --workers 4                   # mutation, one module
```

- **Secrets:** turn on the pre-commit hook once per clone with `git config core.hooksPath tools/hooks`. It runs `python tools/gitleaks.py --staged` and stops a commit that adds something that looks like a secret. CI scans every commit with the same script. It downloads a pinned gitleaks release, checks its SHA-256, and keeps it in `.cache/`. If the github.com download fails, which happens when GitHub's release storage has an outage, it falls back to the GitHub API; the same checksum applies. It doesn't use the gitleaks GitHub Action, which needs a paid licence for organisations. If a finding is a false positive, add `gitleaks:allow` in a comment on that line. If it's real, remove the secret and rotate it, because it stays in the history.
- **Mutation tests** change the code in small ways and check that a test notices. They run on a copy of the repo, so your files are never touched. A mutant that survives is either a missing test, or an equivalent change that can't be observed. Every module is held at 0% survivors: kill a survivor with a test of real behaviour, rewrite code whose mutants can't be observed, and only then mark a line with `# pragma: no mutate`, saying why in a comment. The pragma skips every mutant on its line, so keep such lines small.
- **Run mutation tests on Linux, with a memory limit.** On Windows, a test that times out can leave the process running the mutated code behind, and a mutant that loops while it allocates can then fill the machine's memory. A container is the simple way:

  ```bash
  docker run --rm --memory=6g --memory-swap=6g --pids-limit=512 --cpus=4 -v "$PWD:/src:ro" -w /src python:3.12-slim \
    bash -c 'pip install -q --require-hashes -r requirements-dev.txt && python tools/run_mutation.py graph --max-survival 0 --workers 4'
  ```

  In PowerShell, write the volume as `"${PWD}:/src:ro"` and put the whole command on one line, or end each line with a backtick instead of a backslash. In Git Bash, set `MSYS_NO_PATHCONV=1` before `docker run`, or it rewrites the paths.

  `--workers N` tests N mutants at once, each in its own copy of the repo, so give the container N CPUs. Four workers ran `init` about three times faster than one. Each worker gets a free port chosen by the operating system.
- **While the mutation workflow is paused, nothing checks the 0% limits.** A change to a module's script or its tests therefore runs that module in the container, and its pull request reports the survival rate.
- **The survival limits in `.github/workflows/mutation.yml` are a ratchet.** Lower them when you kill survivors, and never raise them. Mutation tests run weekly and on request, not on every push, because the graph script alone takes about 45 minutes with one worker, or about 8 with four. The workflow is paused for now to save Actions minutes: run `gh workflow enable "Mutation tests"` to turn it back on, or run `tools/run_mutation.py` locally.
- **Unchanged modules are skipped.** A module runs again only when its script, its tests, the files they read, the tooling, or its limit has changed. Each pass uploads a marker artifact named after a hash of those files, and a later run with the same hash skips the module. Run the workflow by hand with `force` to re-test everything. If a module reads a new file, add it to that module's `paths` in the workflow.
- **A mutant that runs longer than 20 seconds counts as caught.** A normal test run takes about 2 seconds, so only a hang gets that far. Raise the `timeout` in `mutation/<module>.toml` if a test file ever gets that slow.
- **Changing a tool version:** edit `requirements-dev.in`, then run `uv pip compile requirements-dev.in --universal --generate-hashes --python-version 3.12 -o requirements-dev.txt`.
- **CI is kept to a few jobs,** because billing rounds each job up to a whole minute and bills Windows at 2x and macOS at 10x in private repos. Quick checks share one Linux job, and macOS isn't tested on every push. Add a check as a step of the `checks` job rather than a new job.
- **Actions are pinned to commit SHAs** with the release in a comment. Dependabot proposes updates to both.
- **`tools/run_tests.py`** is what the mutation runner calls. It succeeds only if tests really ran, because a mutant that makes a script exit during import would otherwise look like a pass.

## Releases

The version in `.claude-plugin/plugin.json` changes only in a release, never in a feature or fix. Claude Code installs an update for a plugin only when its version changes, so a bump is what delivers the merged changes to users. Versions follow [Semantic Versioning](https://semver.org/): a patch for fixes, a minor version for new features, a major version for a change that breaks existing workspaces.

1. **Collect the changes.** Each change a user can see adds a line under `## [Unreleased]` in `CHANGELOG.md` in the same pull request.
2. **Open a release pull request.** It does two things: it sets `version` in `.claude-plugin/plugin.json`, and it renames `[Unreleased]` to the new version and today's date, with a new empty `[Unreleased]` above it and the links at the bottom updated. `python tools/check_release.py` fails if the version has no dated entry, and the unit tests run it, so a bump without a changelog entry cannot merge.
3. **Merge it, then tag the merge commit** with `git tag vX.Y.Z` and `git push origin vX.Y.Z`. The Release check workflow fails if the tag is not `v` followed by the plugin's version.
4. **Create the GitHub release** from the tag, with the changelog entry as its notes: `gh release create vX.Y.Z --title vX.Y.Z --notes-file <the entry>`.

## Design decisions

- **Semantic Scholar (2026-11-05):** a read-only standard-library script with a fixed host and an optional API key from `SEMANTIC_SCHOLAR_API_KEY`, not an MCP server. Without a key, `search` is heavily rate-limited.
- **arXiv (2026-11-07):** a standard-library script, not an MCP server. It reads arXiv's HTML version as Markdown, and falls back to the PDF read by Claude Code's Read tool, so it needs no PDF converter.
- **Distribution (2026-11-07):** a Claude Code plugin, without hooks. Plugins can't carry permission rules or `CLAUDE.md` content, so the `init` skill writes them into the workspace.
- **Graph storage:** two JSONL files changed only through `graph.py`, which locks, checks for duplicates, validates, and saves crash-safely. Names and external ids are unique within a type, not across types.
- **Recap page:** a fixed page copied into the workspace, with all rendering in `recap-lib.js` so it can be tested in Node.
