---
name: add
description: Save one or many links (papers, blogs, repos, threads) to the reading list and triage each one. Use when the user runs /add, submits links, or asks to save something to read later.
argument-hint: <links>
---

# Add links

Run commands from the workspace root. `<skills>` is the folder that contains this skill's base directory.

Keep this quick. Users often add more links than they can read, so don't read full texts here.

1. Check `research/papers.md` for each link and skip any already listed, telling the user which.
2. Get metadata:
   - **Papers:** make one `scholar` `batch` call for all of them with `--with-references`, and save its output to a file in a temporary folder.
   - **Not found, or not a paper:** read the page with the built-in web fetch, or check a repo with `gh`.
3. Using `research/profile.md`, give each link a route:
   - `read`: worth a deep read.
   - `skim`: useful parts can be extracted without a full read.
   - `archive`: keep it searchable, with no plan to read it.
4. Add one row per link to `research/papers.md` in the format described at the top of that file.
5. Add each paper and its authors to the graph with `<skills>/graph/scripts/graph.py`, following the `graph` skill:
   - **Paper:** `add --type paper`, with `--slug <arXiv ID>` for arXiv papers, the `ARXIV:` or `DOI:` ID as an alias, and `--id s2=<paperId>`.
   - **Authors:** `add --type author --id s2=<authorId>` for each, using the ids from the `batch` result. If the author is already in the graph, reuse them. If someone else has the same name, add the new author with `--distinct`, and they get the next free id, such as `author:wei-zhang-2`. A different Semantic Scholar id on a same-name author is held for a decision rather than refused, but it isn't proof: Semantic Scholar sometimes splits one person across ids.
   - **Links:** `link <paper> authored-by <author> --source "Semantic Scholar" --status verified`.
   - **Citations:** once the papers are in the graph, run `graph.py standing <file>` on the saved `batch` output. It saves each paper's citation counts and links the papers that cite each other. If it fails, say so in your reply.
   - Full extraction of datasets, methods, and the rest waits for the `read` skill.
6. Reply with a short table of title, publication date, route, and a one-line reason. Say so if a link could not be read, and mark its row `unread-link` rather than guessing what it says.

The route is a suggestion, so change it if the user disagrees.
