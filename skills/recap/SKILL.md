---
name: recap
description: Refresh the workspace's recap page, which shows activity, papers, insights, pins, and the knowledge graph in a browser. Use after any change to the research files, or when the user asks to see what has been done so far.
---

# Recap page

Run from the workspace root. `<skills>` is the folder that contains this skill's base directory.

First bring citation counts up to date, without reading the ids yourself, because there can be hundreds. Put two files, `ids.txt` and `counts.json`, in a temporary folder outside the workspace, such as the one Claude Code gives you for scratch files, and call that folder `<tmp>` below. `standing-due` and `--out` refuse any place in the workspace except `research/`, so a bare `ids.txt` run from the workspace root fails.

1. Run `python <skills>/graph/scripts/graph.py standing-due <tmp>/ids.txt`. It writes the ids of papers whose counts are missing or more than 30 days old to the file, and says how many. If it says `no papers due`, go on to the page.
2. Run `python <skills>/scholar/scripts/s2.py batch --ids-file <tmp>/ids.txt --with-references`, saving its output to `<tmp>/counts.json`. It asks for 100 papers at a time. If a later request fails, it still prints the papers it fetched and exits with 1.
3. Run `graph.py standing <tmp>/counts.json` whether or not step 2 succeeded, because after a partial failure the file holds the papers from the requests that worked. If it holds nothing, `standing` says so and changes nothing. It says how many papers it updated, how many citation links it added between papers in the graph, and how many Semantic Scholar had no citation data for. Those are not asked about again for 30 days.
4. `standing` lists the papers without citation data by id and name. Semantic Scholar sometimes knows a paper under another id, so look each one up by its title: `python <skills>/scholar/scripts/s2.py match "<name>" --out <tmp>/match.json`. If the result is the same paper (title, year, and authors agree), run `graph.py update <paper id> --id s2=<paperId>` and then `graph.py standing <tmp>/match.json`, which saves its counts. A match has no reference list, so its citation links are added at the next refresh, 30 days on. If it finds nothing, or a different paper, leave it. Each lookup is one request, so for more than ten such papers, ask the user first. If a lookup fails with a rate limit, stop the lookups for this run: without `SEMANTIC_SCHOLAR_API_KEY` it fails at once instead of waiting, and the papers are tried again in 30 days.

If a step fails, say so and carry on: the page shows the counts it has, and the papers that are still missing are tried again next time.

Then run `python <skills>/recap/scripts/recap.py`. It copies the fixed page into `research/recap/` and writes `recap-data.js` beside it from the research files. It prints the page's path.

- **After any change to the research files:** run it in the same turn. Never edit the page or the data file by hand.
- **If the user asks to see it:** give them the full path it printed, and tell them to open it in a browser, not in an editor preview, which blocks the page's scripts.
- **If it warns that the graph can't be shown:** report the reason, and fix the graph with the `graph` skill.
