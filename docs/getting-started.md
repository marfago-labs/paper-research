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

3. It shows what it will create or change, and writes nothing yet. Read the list. It never overwrites a file in `research/`, and it leaves everything outside its own block in `CLAUDE.md` alone.
4. It then gives you a command that starts with `!`, such as `! python "<path>/skills/init/scripts/init.py" --workspace "<your folder>"`. The script prints this command itself, with its own path and your workspace folder, and Claude passes it on unchanged. Check that the path points into the plugin's folder, then paste it into Claude Code to run it. You run this step because `init` writes Claude's own permission rules and instructions, so Claude doesn't, and Claude Code's auto mode would block it if it tried.
5. **Carry on in the same session.** Claude Code reads `CLAUDE.md` only when a session starts, so Claude reads the new rules itself once the write has happened. Every new session in the folder loads them on its own.

What `init` created:

| Path | What it is |
|---|---|
| `research/` | Your notes: facts about you, papers, pins, insights, lessons, and the knowledge graph. See [Your workspace](workspace.md). |
| `CLAUDE.md` | A block of rules for Claude, between two marker comments. Write your own notes outside the block. |
| `.claude/settings.json` | Approval prompts before Claude fetches from the paper sites or edits the files that steer it, and rules for auto mode. See [Security](security.md). |
| `.gitignore` | Entries for generated files and your local settings. |

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

After you update the plugin, run `/paper-research:init` again. It refreshes the rules block in `CLAUDE.md`, and shows you the changes before it writes them.

## Next

- [Skills](skills.md): what each skill does, step by step.
- [Your workspace](workspace.md): every file, and its format.
- [Knowledge graph](knowledge-graph.md): how entities, links, and duplicate checks work.
- [Security](security.md): what protects you from a malicious paper, and what doesn't.
- [Troubleshooting](troubleshooting.md): when something goes wrong.
