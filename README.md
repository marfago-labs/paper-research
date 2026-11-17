# paper-research

[![CI](https://github.com/marfago-labs/paper-research/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/marfago-labs/paper-research/actions/workflows/ci.yml)
[![Coverage 100%](https://img.shields.io/badge/coverage-100%25-brightgreen)](CONTRIBUTING.md)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)](#why-its-different)
[![Licence: Apache 2.0](https://img.shields.io/badge/licence-Apache%202.0-blue)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757)](https://docs.claude.com/en/docs/claude-code/plugins)

A Claude Code plugin for finding, reading, and discussing research papers with Claude, and keeping what matters: facts you pin, insights tied to their source papers, a knowledge graph of what papers use and build on, and a recap page you open in a browser.

Everything the plugin learns about you and your papers stays in plain files in your own workspace, where you can read, edit, and version it.

![The recap page's graph tab: papers, their authors, and the concepts, datasets, methods, models, and tools they use, with one paper's links listed beside the graph](docs/images/recap-graph.png)

## Install

In a terminal:

```bash
claude plugin marketplace add marfago-labs/paper-research
claude plugin install paper-research@paper-research
```

Or start `claude` in a terminal and run `/plugin marketplace add marfago-labs/paper-research` and `/plugin install paper-research@paper-research`. The `/plugin` command isn't available in the VS Code chat panel, so use the terminal there. Afterwards, run `/reload-plugins` in the chat panel so it loads the plugin's skills.

Then open the folder you want to use for papers and run:

```text
/paper-research:init
```

`init` shows what it will create, then gives you one command to run, starting with `!`, which sets up the workspace. Check that its path points into the plugin's folder, then run it yourself because it changes Claude's own permissions and rules, and Claude Code's auto mode won't let Claude do that. Claude then follows the new rules straight away, and every new session loads them on its own. After updating the plugin, run `init --dry-run` to see what would change, then `init` to refresh the rules.

**Requirements:** Python 3.9 or later, standard library only. The `read` and `pin` skills use the Hugging Face MCP server when it's available, and skip it when it isn't.

## Use

Paste a paper link and Claude starts a discussion. Paste several, or say "for later", and Claude saves and triages them. The skills are also available by name:

| Skill | What it does |
|---|---|
| `add` | Saves links to `research/papers.md` and suggests whether to read, skim, or archive each one |
| `next` | Recommends what to read next, with each paper's publication date and academic standing |
| `read` | Analyses a paper, including its code and data, discusses it, and extracts it into the graph |
| `pin` | Saves a fact, such as a dataset, method, or finding, with its source |
| `insight` | Logs a takeaway and connects it to its source papers |
| `graph` | Queries and changes the knowledge graph, with duplicate checks on every change |
| `recap` | Refreshes the recap page in `research/recap/recap.html` |
| `scholar`, `arxiv` | Read-only clients for Semantic Scholar and arXiv, used by the other skills |
| `init` | Sets up or updates the workspace |

## Why it's different

### It reads papers through a retriever built to distrust them

A research assistant reads text written by strangers, in the same session that holds your notes. A paper can contain text written to look like instructions, and no software removes that risk completely. Instead of handing Claude a fetched web page, this plugin puts a retriever between the paper and Claude, built around that threat.

Papers come in through small, purpose-built clients for arXiv and Semantic Scholar, written in Python's standard library with no dependencies to install or to compromise:

- **Fixed destinations.** Each client contacts only its own hosts: `arxiv.org`, `export.arxiv.org`, and `api.semanticscholar.org`. A redirect anywhere else is refused, so your Semantic Scholar API key can never be sent to another host.
- **Read-only, with limits.** The clients never write to a remote service. Each request has a size cap and a time limit, and requests are spaced as the services ask, even across several windows at once.
- **Checked input.** Paper and author IDs are validated before they become part of a URL or a file name, so a crafted ID can't write outside your workspace.
- **Cleaned text.** arXiv papers are converted to Markdown by the plugin's own converter, which drops scripts, styles, and page furniture. It also removes text hidden from human readers, such as `display:none`, near-white or tiny text, and strips invisible characters that can smuggle instructions. Each removal leaves a visible `[hidden text removed: N characters]` marker and Claude is told to warn you, because hidden text in a paper is itself a warning sign. The same invisible characters are removed from the titles and abstracts that the arXiv and Semantic Scholar clients print, and the count is reported, so Claude can tell you.
- **Labelled as data.** Everything the retriever returns is marked as untrusted. Claude's rules say to treat it as data, never to follow links found inside papers without asking, and never to send your notes anywhere.
- **Sections you can check.** Papers are read by section, and Claude cites the section, page, or figure behind each claim, so you can verify it against the paper.

Around the retriever, Claude Code asks you before Claude fetches a web page and before its file tools edit the files that steer every session. An optional sandbox cuts shell commands off from everything but arXiv and Semantic Scholar, and `init` refuses an update that would widen your permissions. [Security](docs/security.md) says what is enforced, what is only instructions, and what isn't covered.

### It gets better at finding what you care about

The plugin keeps a record of you as a reader, in plain files you can read and edit, and uses it every time it searches, triages, or recommends:

- **It listens.** Your questions and stated preferences go into a running log in `research/user-facts.md`, each marked as something you said, something you did, or something Claude inferred. Claude proposes changes to your reader profile in one line and you approve them, so it never decides who you are on its own. When a turn ends with research files changed and the recap page out of date, a hook stops Claude once to log the session's questions and refresh the page.
- **Your ratings steer recommendations.** After a paper, you give it 1 to 5. Papers you rate 4 or 5 become examples of what to find more of, and papers you rate 1 or 2 become examples of what to avoid, in Semantic Scholar's recommendations.
- **Searches start from your interests.** `next` builds its arXiv searches from the topics in your profile and the questions you keep asking, then picks papers by fit with you first. It also checks each pick's standing in the research community, with the evidence, so a good match isn't taken for a good paper.
- **Triage knows your priorities.** When you save a stack of links, `add` suggests whether each is worth a deep read, a skim, or an archive, based on your profile.
- **It learns how you work.** When you correct Claude or confirm that an approach worked, it proposes a lesson, and once you approve it, every later session follows it.
- **It won't shrink your horizons.** About one recommendation in five is deliberately outside your usual topics, and labelled that way.

There is no hidden model. The personalization is in files you control, and it is Claude's judgement applied to them. See [Your workspace](docs/workspace.md) for the files and [Skills](docs/skills.md#next) for how `next` works.

## Documentation

| Read | To |
|---|---|
| [Getting started](docs/getting-started.md) | Install the plugin, set up a workspace, and read your first paper |
| [Skills](docs/skills.md) | See what each skill does, step by step, and what it changes |
| [Your workspace](docs/workspace.md) | Understand every file `init` creates, its format, and the recap page |
| [Knowledge graph](docs/knowledge-graph.md) | See how a paper gets into the graph, and how entities, links, and duplicate checks work |
| [Architecture](docs/architecture.md) | See the components, what each one writes, and the design decisions |
| [Security](docs/security.md) | Know what protects you from a malicious paper, and what doesn't |
| [Command reference](docs/reference.md) | Run the scripts yourself, with every option and exit code |
| [Troubleshooting](docs/troubleshooting.md) | Fix a message you didn't expect |
| [Contributing](CONTRIBUTING.md) | Change the plugin, and run its tests |

## Develop

CI runs linters and formatters, complexity limits, static analysis, a secret scan, unit tests on Linux with Python 3.9, 3.12, and 3.13 and on Windows with 3.13, 100% coverage, and behaviour scenarios. Mutation tests run locally. [CONTRIBUTING.md](CONTRIBUTING.md) says how to run each check.

## Licence

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Versions 0.1.0 and 0.2.0 were released under MIT, and are also available under Apache 2.0.
