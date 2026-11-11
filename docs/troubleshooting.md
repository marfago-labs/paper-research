# Troubleshooting

Find the message you saw. Each entry says what it means and what to do.

## Installing and setting up

**The skills don't appear, or Claude doesn't use the plugin's rules.**
Run `/reload-plugins` to load a plugin you just installed or updated, then start a new session in the workspace. Claude Code reads `CLAUDE.md` when a session starts. Changes to `.claude/settings.json` apply straight away. Check that the plugin shows as installed with `/plugin`.

**Auto mode blocked `init` as "self-modification", and nothing was written.**
That's intended. `init` writes `.claude/settings.json` (permission rules) and `CLAUDE.md` (instructions), which control Claude's own behaviour, so Claude Code won't let Claude write them for you. Run it yourself: type `!` followed by the command `init` showed, for example `! python "<path>/skills/init/scripts/init.py" --workspace "<your folder>"`, or run the same command in a terminal. If `init` printed `no ready-made command`, a path has characters that need shell quoting, so run `python <path>/skills/init/scripts/init.py` from a terminal in the workspace folder. Don't add a permission rule that lets Claude run it, because that gives Claude a standing way to rewrite its own permissions.

**`init`: `... is not valid JSON ... fix it by hand first`.**
Your `.claude/settings.json` has a syntax error, or contains comments. `init` won't guess. Fix the file, then run `init` again. Nothing was changed.

**`init`: `... has an unexpected shape ...`.**
A setting that should be a list or an object is something else, for example `"allow": "all"`. Fix it by hand. The message names the file.

**`init`: `CLAUDE.md has only one of the paper-research markers`.**
The block in `CLAUDE.md` is missing its begin or end line, or they're in the wrong order. Restore both lines, or delete the block entirely and run `init` again.

**`init`: `CLAUDE.md has more than one paper-research block`.**
Delete the extra blocks, leaving one, or none. `init` replaces only a single block.

**`init`: `the plugin's settings template has an allow rule init won't write`, or `an ask rule`.**
The settings template in the installed plugin contains an allow rule, or an ask rule other than approving a file edit or a fetch from a named website. `init` refuses, and nothing was changed. Don't work around it. This may mean the plugin has been tampered with, so reinstall it from a source you trust, or report it.

**Claude Code asks before every fetch from arXiv, Semantic Scholar, Hugging Face, or GitHub, even in auto mode.**
That's intended, so you see the address of each fetch from the sites papers come from. "Don't ask again" doesn't stick, because a project's ask rule wins over your own allow rule. The plugin's own scripts download papers through the shell, so this affects only Claude's own page reads.

**Claude Code asks before Claude changes `lessons.md`, `profile.md`, `CLAUDE.md`, or a file in `.claude/`.**
That's intended. These files steer every session, so `init` makes each edit need your approval. Check that the change is one you asked for, then approve it.

**`gh` commands fail with a network error, with the sandbox on.**
The sandbox only reaches arXiv and Semantic Scholar. Claude can still read GitHub pages with its fetch tool.

## Reading papers

**`arxiv`: `no research/ folder here or in a parent folder; run the init skill`** (exit 2).
You're in a folder that isn't a workspace. Open the workspace, or run `init` first.

**`arxiv`: `no HTML version at ...; use the pdf command instead`** (exit 3).
arXiv has no HTML version of this paper, which is common for older papers. Claude downloads the PDF and reads it instead. Figures are only available that way, too.

**`arxiv`: `HTTP 429`, or a very slow response.**
arXiv is limiting requests. The script spaces its requests by 3 seconds and retries, so wait a minute and ask again. Don't start several searches at once.

**`scholar`: `HTTP 429`.**
Semantic Scholar limits requests from anyone without an API key, and `search` most of all. Set `SEMANTIC_SCHOLAR_API_KEY` in your environment (request one at semanticscholar.org). Until then, Claude uses arXiv search for finding papers, and says so. Other requests to Semantic Scholar can be refused too, so some details and citation links may be missing. Ask again later.

**`scholar`: `gave up ... after about 90 seconds`.**
Semantic Scholar kept refusing. Try again later.

**`error: invalid arXiv ID` or `invalid paper ID`** (exit 2).
The text isn't an arXiv ID, link, DOI, or Semantic Scholar id. Check for a typo or a stray space.

**Citation links are missing for a paper.**
Semantic Scholar was busy when the paper was read, and Claude carried on without them. Ask Claude to add the citation links for that paper again.

## The knowledge graph

**`graph`: `graph folder not found`.**
Run from the workspace root, or after `init`.

**`graph`: `another graph command is still running`.**
Another window is changing the graph. Wait a moment and try again. A command that crashed doesn't leave the lock held.

**`graph`: `change refused, the graph would be invalid`.**
The message lists what's wrong, such as an unknown entity or a missing source. Claude fixes its command and tries again. Nothing was written.

**`graph`: `invalid graph:` followed by errors, on every command.**
Something edited the graph files by hand and broke them. Read the listed errors and fix those lines, or restore the files from git. Don't delete `research/graph/`.

**`add` exits with 3 and says `possible duplicates`.**
Not an error. The new entity looks like an existing one, and Claude decides whether to reuse the old one or confirm they're different. If it can't tell, it asks you. See [Knowledge graph](knowledge-graph.md#duplicates).

**`"..." matches more than one entity, so use an id`.**
Two entities share that name. Claude uses an id. If you're running a command yourself, copy an id from the message.

**A paper shows `only authors or citations in graph` on the recap page.**
It hasn't been extracted. Ask Claude to extract it, or discuss it with `read`.

## The recap page

**Nothing happens when I click a link, or the Graph tab is blank.**
You opened the page in an editor's preview. Open `research/recap/recap.html` in a browser instead.

**`No data found`.**
The data file is missing. Ask Claude to refresh the recap, then reload the page.

**The page is out of date.**
It doesn't refresh itself. Reload it after a session. If it still looks wrong, ask Claude to refresh the recap first.

**`The graph can't be shown: ...`.**
The graph files are invalid. The rest of the page still works. See the graph entries above.

**`The drawing library didn't load`.**
`cytoscape-3.30.4.min.js` is missing from `research/recap/`. Ask Claude to refresh the recap, which copies it back.

## Still stuck

Run the failing command yourself with `--help` or `--dry-run`, and read the message. Every script says what's wrong in words and exits with a code described in the [command reference](reference.md). If it looks like a bug, open an issue with the full message, the command, and your operating system. Remove anything private from it first.
