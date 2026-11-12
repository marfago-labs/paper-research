---
name: graph
description: Query and change the workspace's knowledge graph of papers, authors, concepts, methods, models, datasets, tools, and insights, with duplicate checks on every change. Use when another skill adds to the graph, or when the user asks how things connect, what is in the graph, or to fix duplicates.
---

# Knowledge graph

Run from the workspace root. `<skills>` is the folder that contains this skill's base directory, so the script is `<skills>/graph/scripts/graph.py`.

`research/graph/entities.jsonl` and `research/graph/relations.jsonl` are the source of truth, with one JSON object per line. `research/pins.md` keeps the facts, and the graph shows how things connect.

## Data

- **Entity:** `id` (`type:slug`, using the arXiv ID as the slug for arXiv papers), `type`, `name`, `aliases`, and optional `url`, `note`, `ids`, and `distinct_from`. Types: paper, author, concept, method, model, dataset, tool, organisation, insight.
- **Standing:** a paper can have `standing`: its `citations`, `influential` citations, `venue`, and `year` from Semantic Scholar, and the date they were `checked`. Only `cites` and `standing` write it, from Semantic Scholar output, so never make the numbers up. A paper Semantic Scholar has no data for gets only `checked`, so it isn't asked about again for a month.
- **External ids:** `ids` maps `s2`, `arxiv`, `doi`, `hf`, `github`, or `orcid` to an identifier. Two entities of the same type with the same external id are the same thing. Add ids whenever you know them, especially Semantic Scholar ids for authors, because names alone can't tell two people apart.
- **Distinct:** `distinct_from` lists entities that look alike but were checked to be different, so the duplicate checks stop flagging them.
- **Relation:** `from`, `rel`, `to`, `source`, `status`. Relations: uses, evaluates-on, builds-on, proposes, cites, authored-by, contradicts, related-to, derived-from.
- **Status:** `verified` means checked against the source, and `inferred` is your own reading. Never mark an inference as verified.

## Commands

- **Read:** `validate`, `stats`, `search <text>`, `neighbours <entity>`, `path <a> <b>`, `dupes`, `islands`.
- **Write:** `add`, `update`, `link`, `unlink`, `merge`, `remove`, `cites`, and `standing`. Run any of them with `--help` for its options.
- **Citation counts and links:** `standing <file>` reads saved `s2.py batch` output. It saves each paper's counts and, if the output was made with `--with-references`, adds a `cites` link from each paper to every paper in the graph that it cites. `standing-due <file>` writes the ids of papers whose counts are missing or old to a file, for `s2.py batch --ids-file`. It changes nothing in the graph. Links only join papers that are already in the graph, so run `standing` again after the graph grows.

```bash
python <skills>/graph/scripts/graph.py add --type dataset --name "Terminal-Bench 2.1" --alias TB-2.1 --url https://arxiv.org/abs/2601.11868
python <skills>/graph/scripts/graph.py link paper:2611.05306 evaluates-on "Terminal-Bench 2.1" --source "ARXIV:2611.05306, §2.2" --status verified
python <skills>/graph/scripts/graph.py cites paper:2611.05306 <saved s2.py output>
```

## Rules

- **Only through the script:** never edit the JSONL files by hand. Every write takes a lock, checks for duplicates, and validates the whole graph before saving. If a command says another one is running, wait and try again.
- **Use ids for ambiguous names:** if a name matches more than one entity, the script lists their ids. Use the id.
- **Duplicates:** `add` refuses an entity with the same name or external id as an existing one. It exits with 3 when it finds possible duplicates: a similar name, or a name that is the other's alias. Pass the other names you know with `--alias` when you add, such as an acronym or its expansion, since nothing else links them. On exit 3, decide: if it's the same thing, `update` the existing entity with the new name as an alias. If it's different, run `add` again with `--distinct`. If you can't tell, ask the user. If an alias is refused because another entity already uses it (`SAM` for two methods), decide the same way: if they are the same thing, `merge` them; if they are different, mark them with `update --distinct` and then add the alias. `dupes` lists possible duplicates across the whole graph, and `merge` folds one entity into another.
- **Extraction:** every paper read or skimmed gets its entities and citation links straight away, as "Extract into the graph" in the `read` skill describes. `islands` lists papers with only author, citation, or insight links.
- **After any change:** refresh the recap with the `recap` skill, which also draws the graph.
- **Connection questions:** use `neighbours` and `path`, and cite each connection's source.
