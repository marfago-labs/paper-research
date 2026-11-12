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
6. Reply with the paper-list table under [Listing papers](#listing-papers), with a `Route` column after `Note`. Here `Note` is the one-line reason for the route. Say so if a link could not be read, and mark its row `unread-link` rather than guessing what it says.

The route is a suggestion, so change it if the user disagrees.

## Listing papers

Whenever you list papers to the user, use one table with the columns `Published | Title | ID | Citations | Topic | Note`, in that order. `Published` is the publication date as `YYYY-MM-DD`, from `published` in `arxiv` or `publicationDate` in `scholar`, or `unknown`; never guess it. `ID` is the paper's `link` from `arxiv` or `scholar`, such as `[ARXIV:2611.14326](https://arxiv.org/abs/2611.14326)`, copied as it is so that it stays a link, or the link itself for anything else, such as a blog post or a repository. `Citations` is `citationCount` from one `scholar` `batch` call for all the listed papers, made for every list, so the counts are all from the same moment. Write `-` only when Semantic Scholar has no count. If the call fails, write `?` and say so below the table, or, for a paper in the graph, use the saved count that `graph.py search <id>` shows, with the date it was checked. `Topic` is two to five words. `Note` is one sentence: the main result, or why the paper matters to this user, not details such as the venue, page count, or code. A skill may add its own columns after `Note`. Put the total, caveats, and suggestions below the table, not in it.
