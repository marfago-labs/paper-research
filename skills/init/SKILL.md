---
name: init
description: Set up a folder as a paper-research workspace by creating the starter research files. Use when the user runs /paper-research:init or starts a new paper workspace. Not for Claude Code's own /init.
---

# Set up the workspace

Run from the workspace root. `<skills>` is the folder that contains this skill's base directory.

1. Run `python <skills>/init/scripts/init.py`. It creates each starter file in `research/` that's missing and adds missing lines to `.gitignore`. It never changes a research file that exists, and never touches `CLAUDE.md` or `.claude/`, so you can run it yourself without asking.
2. Tell the user which files it created, from the `created` and `updated` lines. If there are none, the workspace was already set up.
3. After those lines it prints the plugin's rules and the user's lessons. Follow them for the rest of this session. From the next session on, the plugin loads them on its own, and keeps them up to date when the plugin is updated.

## What the plugin does in a workspace

A folder is a workspace once it has `research/user-facts.md`. In a workspace, the plugin's hooks:

- give Claude the rules and `research/lessons.md` at the start of every session, and again after the conversation is compacted;
- ask the user before any edit to `research/lessons.md` or `research/profile.md`, and before any fetch from `arxiv.org`, `export.arxiv.org`, `api.semanticscholar.org`, `huggingface.co`, `github.com`, or `api.github.com`;
- check when a turn ends that the recap page is up to date.

Nothing is written to the user's settings. If the user wants the strongest protection for shell commands, point them to the sandbox section of the plugin's security page, which has the settings to add and says how `/sandbox` turns it on. Don't change their settings yourself.
