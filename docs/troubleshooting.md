# Troubleshooting

Find the message you saw. Each entry says what it means and what to do.

## Installing and setting up

**The skills don't appear, or Claude doesn't use the plugin's rules.**
Run `/reload-plugins` to load a plugin you just installed or updated, then start a new session in the workspace. The plugin gives Claude its rules when a session starts, and only in a folder that has `research/user-facts.md`, or inside one, so run `/paper-research:init` first. Check that the plugin shows as installed with `/plugin`. The hooks run `python3`, then `python`: if neither is on your `PATH`, nothing loads.

**Claude follows two sets of paper-research rules, or the old ones.**
The workspace was set up by version 0.3.0 or earlier, which wrote its rules into `CLAUDE.md`. Delete the block between the `paper-research:begin` and `paper-research:end` lines, and the `permissions.ask` and `autoMode.soft_deny` entries that version added to `.claude/settings.json`. The plugin now brings its rules and prompts itself.

**Claude Code asks before every fetch from `arxiv.org`, `export.arxiv.org`, `api.semanticscholar.org`, `huggingface.co`, `github.com`, or `api.github.com`, even in auto mode.**
That's intended, so you see the address of each fetch from the sites papers come from. "Don't ask again" doesn't stick, because the plugin's hook asks each time. The plugin's own scripts download papers through the shell, so this affects only Claude's own page reads.

**Claude Code asks before Claude changes `lessons.md` or `profile.md`, with a reason from the paper-research plugin.**
That's intended. The plugin loads these files into every session, so each edit needs your approval. Check that the change is one you asked for, then approve it. A prompt that says the plugin `couldn't tell which file or address` means the tool call was malformed: approve it only if you asked for it.

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
Semantic Scholar limits requests from anyone without an API key, and `search` most of all, so without a key the script doesn't retry a refused search. Set `SEMANTIC_SCHOLAR_API_KEY` in your environment (request one at semanticscholar.org). Until then, Claude finds candidates with arXiv search and looks up their citation counts in one `batch` call, which retries, and says so. Such a list covers only arXiv papers, and only those its queries found. Other requests to Semantic Scholar can be refused too, so some details and citation links may be missing. Ask again later.

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

**`graph`: `can't link ...: <relation> goes from ... to ..., not ...`.**
The relation can't join those two types of entity, such as a concept `authored-by` an author. Use the relation that fits, or link the right entities. The types each relation joins are in the [graph schema](graph-schema.md#relation-types). Nothing was written.

**`graph`: `a new <type> needs its first link`.**
Every entity but a paper is added with a link to where it came from, in the same `add` command: `--link-from` or `--link-to`, with `--source` and `--status`. Nothing was written.

**`validate`: `found ... with no links` or `found ... with no authors`.**
Not an error in the graph, which still loads, though `validate` exits with 1 until they are fixed. An entity other than a paper should be linked to the paper it came from, or removed if it was added by mistake. A paper should have its authors, or a reason it has none, given with `update --no-authors`. Claude fixes these after each extraction.

**`"..." matches more than one entity, so use an id`.**
Two entities share that name. Claude uses an id. If you're running a command yourself, copy an id from the message.

**A paper shows `nothing extracted yet` on the recap page.**
Its status is `done`, but the graph holds only its authors and citation links, so it was finished without being extracted. Ask Claude to extract it, or discuss it with `read`. A paper still waiting to be read shows nothing: it is extracted when you read it.

## The recap page

**Nothing happens when I click a link, or the Graph tab is blank.**
You opened the page in an editor's preview. Open `research/recap/recap.html` in a browser instead.

**`No data found`.**
The data file is missing. Ask Claude to refresh the recap, then reload the page.

**The page is out of date.**
It doesn't refresh itself. Reload it after a session. If it still looks wrong, ask Claude to refresh the recap first.

**Claude keeps going after it seems done, to log questions and refresh the recap.**
That's intended. The plugin's `Stop` hook saw that research files changed since the page was written, so it stopped Claude once to catch up. It never asks twice in a turn.

**`The graph can't be shown: ...`.**
The graph files are invalid. The rest of the page still works. See the graph entries above.

**`The drawing library didn't load`.**
`cytoscape-3.30.4.min.js` is missing from `research/recap/`. Ask Claude to refresh the recap, which copies it back.

## Still stuck

Ask Claude to turn on the debug log (the `debug` skill), repeat what failed, and show you the log. It records each command, each request to arXiv or Semantic Scholar with its status, and each decision of the approval hook with its reason. To watch it live in Grafana, see [Telemetry](telemetry.md).

Run the failing command yourself with `--help` or `--dry-run`, and read the message. Every script says what's wrong in words and exits with a code described in the [command reference](reference.md). If it looks like a bug, open an issue with the full message, the command, and your operating system. Remove anything private from it first.
