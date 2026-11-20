# Getting started

This page takes you from nothing to your first paper discussion.

## What you need

- **Claude Code**, with plugin support.
- **Python 3.9 or later.** The plugin's scripts use only Python's standard library, so there is nothing to `pip install`.
- **Git**, if you install from a repository.

Optional:

- **A Semantic Scholar API key.** Without one, Semantic Scholar's search is heavily rate-limited, and the `scholar` skill falls back to arXiv search. Set it in your environment as `SEMANTIC_SCHOLAR_API_KEY`. Never paste it into a chat or a file.
- **The Hugging Face MCP server.** When it's available, the `read` skill uses it to check models and datasets a paper mentions, and the `pin` skill to check a link before saving it. Everything else works without it.

## Install

Add the repository as a marketplace, then install the plugin. In a terminal:

```bash
claude plugin marketplace add marfago-labs/paper-research
claude plugin install paper-research@paper-research
```

Or start `claude` in a terminal and run the same two commands with a leading `/plugin`, as in `/plugin marketplace add marfago-labs/paper-research`. The `/plugin` command isn't available in the VS Code chat panel, so use the terminal there, then run `/reload-plugins` in the chat panel so it loads the plugin's skills.

To install from a folder on your machine, use its path instead of `marfago-labs/paper-research`.

## Set up a workspace

A workspace is a folder where you do your paper reading. Everything the plugin learns about you and your papers is saved there as plain files.

1. Open the folder in Claude Code. An empty folder is fine, and so is one you already use.
2. Run the setup skill:

   ```text
   /paper-research:init
   ```

3. Claude runs it and tells you which files it created. It only creates files that are missing: it never overwrites a file in `research/`, and never touches `CLAUDE.md` or your settings.
4. **Carry on in the same session.** Claude reads the plugin's rules straight away. Every new session in the folder gets them from the plugin on its own.

What `init` created:

| Path | What it is |
|---|---|
| `research/` | Your notes: facts about you, papers, pins, insights, lessons, and the knowledge graph. See [Your workspace](workspace.md). |
| `.gitignore` | Entries for generated files and your local settings. |

From then on, the plugin's hooks give Claude its rules at the start of each session, and ask you before Claude edits your lessons or profile or fetches from the paper sites. See [Security](security.md).

## Your first paper

Paste a link into the chat, with nothing else:

```text
https://arxiv.org/abs/2303.11366
```

Claude starts the `read` skill. You get:

1. The question the paper asks, its approach and main results, and why it matters to you.
2. What code, data, and models come with it, how popular they are, and what's missing.
3. A critique: baselines, metrics, sample sizes, and whether the evidence supports the claims.
4. A short report of what Claude added to your knowledge graph, such as `Added 6 entities, linked to 3 existing ones`.
5. Two or three questions worth discussing.

Then talk about it. When a takeaway comes up that's worth keeping, Claude proposes it in one line, and logs it if you agree. When you finish, Claude asks for a rating from 1 to 5.

Other things to try:

| Say | What happens |
|---|---|
| Paste several links, or say "save these for later" | The `add` skill saves them and suggests whether to read, skim, or archive each. |
| "What should I read next?" | The `next` skill recommends papers matched to your interests. |
| "Pin that dataset" | The `pin` skill saves the fact with its source. |
| "Log that as an insight" | The `insight` skill saves the takeaway and connects it to its source paper. |
| "Show me the recap" | The `recap` skill refreshes a page that shows everything so far. |

## See what you have

Ask Claude to refresh the recap, then open `research/recap/recap.html` **in a browser**, not in an editor preview, which blocks the page's scripts. It has tabs for activity, papers, insights, pins, and the knowledge graph. See [Your workspace](workspace.md#the-recap-page).

## Update the plugin

There's nothing to do after an update: the rules and approval prompts come with the plugin. Run `/reload-plugins`, then start a new session so the new rules load.

If you set up a workspace with version 0.3.0 or earlier, remove what that version's `init` wrote, or the old rules load as well: the block between the `paper-research:begin` and `paper-research:end` lines in `CLAUDE.md`, and the `permissions.ask` and `autoMode.soft_deny` entries it added to `.claude/settings.json`. Keep any `sandbox` settings you want.

## Next

- [Skills](skills.md): what each skill does, step by step.
- [Your workspace](workspace.md): every file, and its format.
- [Knowledge graph](knowledge-graph.md): how entities, links, and duplicate checks work.
- [Security](security.md): what protects you from a malicious paper, and what doesn't.
- [Troubleshooting](troubleshooting.md): when something goes wrong.
