---
name: graph
description: Query and change the workspace's knowledge graph of papers, authors, concepts, methods, models, datasets, tools, and insights, with duplicate checks on every change. Use when another skill adds to the graph, or when the user asks how things connect, what is in the graph, or to fix duplicates.
---

# Knowledge graph

Run from the workspace root. `<skills>` is the folder that contains this skill's base directory, so the script is `<skills>/graph/scripts/graph.py`.

`research/graph/entities.jsonl` and `research/graph/relations.jsonl` are the source of truth, with one JSON object per line. `research/pins.md` keeps the facts, and the graph shows how things connect.

## Data

- **Entity:** `id` (`type:slug`, using the arXiv ID as the slug for arXiv papers), `type`, `name`, `aliases`, and optional `url`, `note`, `no_authors` (why a paper has no author to record, set with `--no-authors`), `ids`, and `distinct_from`. Types: paper, author, concept, method, model, dataset, tool, organisation, insight.
- **Standing:** a paper can have `standing`: its `citations`, `influential` citations, `venue`, and `year` from Semantic Scholar, and the date they were `checked`. Only `cites` and `standing` write it, from Semantic Scholar output, so never make the numbers up. A paper Semantic Scholar has no data for gets only `checked`, so it isn't asked about again for a month.
- **External ids:** `ids` maps `s2`, `arxiv`, `doi`, `hf`, `github`, or `orcid` to an identifier. Two entities of the same type with the same external id are the same thing. Add ids whenever you know them, especially Semantic Scholar ids for authors, because names alone can't tell two people apart.
- **Distinct:** `distinct_from` lists entities that look alike but were checked to be different, so the duplicate checks stop flagging them.
- **Relation:** `from`, `rel`, `to`, `source`, `status`. Relations: uses, evaluates-on, builds-on, proposes, cites, authored-by, contradicts, compared-with, related-to, derived-from. Each joins only some entity types: `authored-by` goes from a paper, method, model, dataset, or tool to an author or organisation, `cites` from a paper to a paper, `evaluates-on` from a paper, method, model, or tool to a dataset, and `proposes` from a paper, author, or organisation to a concept, method, model, dataset, or tool. `uses`, `builds-on`, `contradicts` (from the work that disagrees to the one it contradicts), `compared-with` (from the work that is measured to its baseline or the system it is measured against, never the reverse), and `derived-from` join any types except authors and organisations, and `related-to` joins anything. `link` refuses other pairs and says which types fit, so pick the right relation or entity instead, and `validate` lists older links that break this rule.
- **Status:** `verified` means checked against the source itself, `reported` means checked against a source that only reports another study's result, such as a survey quoting a figure, and `inferred` is your own reading. Never mark an inference as verified, nor a second-hand claim: a claim is `verified` only once you have checked it in the study that made it. A verified or reported link's source must name the document it was checked against: `ARXIV:` or `DOI:` with the section, a `paper:` id with a comma and a section, a link, or `Semantic Scholar`. It must start the source: a reason that only mentions an id is refused. When you later check a reported or inferred claim in the study itself, `link` it again as `verified` with that study as the source: `link` upgrades a weaker status, replacing the source, and never downgrades one. For a reported link, name the study it quotes after it, such as `ARXIV:<survey>, Table 2, quoting ARXIV:<study>`. `link` refuses anything else as verified or reported, and `validate` lists older links that break this rule. `validate` also lists any entity other than a paper with no links, to be linked to the paper it came from or removed, and any paper with no `authored-by` link and no `no_authors` reason, whose authors are to be added as the `add` skill does. It shows each `no_authors` reason too, and a paper's reason is dropped when it gets an author.

## Commands

- **Read:** `validate`, `stats`, `search <text>` (a paper also shows its saved citation count and when it was checked), `neighbours <entity>`, `path <a> <b>`, `dupes`, `islands`.
- **Write:** `add`, `update`, `link`, `unlink`, `merge`, `remove`, `cites`, and `standing`. Run any of them with `--help` for its options.
- **Citation counts and links:** `standing <file>` reads saved `s2.py batch` output. It saves each paper's counts and, if the output was made with `--with-references`, adds a `cites` link from each paper to every paper in the graph that it cites. `standing-due <file>` writes the ids of papers whose counts are missing or old to a file, for `s2.py batch --ids-file`. It changes nothing in the graph. Links only join papers that are already in the graph, so run `standing` again after the graph grows.

```bash
python <skills>/graph/scripts/graph.py add --type dataset --name "Terminal-Bench 2.1" --alias TB-2.1 --url https://arxiv.org/abs/2601.11868 --link-from paper:2401.00007 evaluates-on --source "ARXIV:2401.00007, §2.2" --status verified
python <skills>/graph/scripts/graph.py link paper:2401.00007 uses "Terminal-Bench 2.1" --source "ARXIV:2401.00007, §4" --status verified
python <skills>/graph/scripts/graph.py cites paper:2401.00007 <saved s2.py output>
```

## Rules

- **Only through the script:** never edit the JSONL files by hand. Every write takes a lock, checks for duplicates, and validates the whole graph before saving. If a command says another one is running, wait and try again.
- **First link with `add`:** every entity but a paper is added with its first link in the same command: `--link-from <entity> <rel>` when the other entity starts the link, such as the paper that proposes it, or `--link-to <rel> <entity>` when the new one starts it, such as an insight derived-from a paper, with `--source` and `--status` as for `link`. `add` refuses a new entity without one, and a refused link saves neither. A paper may be added alone, to wait in the reading list. Add any further links with `link`.
- **Use ids for ambiguous names:** if a name matches more than one entity, the script lists their ids. Use the id.
- **Versions are separate entities:** each version of a benchmark, dataset, or model is its own entity, such as `LiveCodeBench v6` and `MRCR v2`, never another version's alias, because results measured on different versions can't be compared. Link versions with `derived-from`.
- **Duplicates:** `add` refuses an entity with the same name or external id as an existing one. It exits with 3 when it finds possible duplicates: a similar name, or a name that is the other's alias. Two papers with different arXiv ids aren't held for a similar name, so add a paper with its arXiv id. Pass the other names you know with `--alias` when you add, such as an acronym or its expansion, since nothing else links them. On exit 3, decide: if it's the same thing, `update` the existing entity with the new name as an alias. If it's different, run `add` again with `--distinct`. If you can't tell, ask the user. Decide each candidate on its own, and never mark candidates distinct in bulk or with a script. If an alias is refused because another entity already uses it (`SAM` for two methods), decide the same way: if they are the same thing, `merge` them; if they are different, mark them with `update --distinct` and then add the alias. `dupes` lists possible duplicates across the whole graph, and `merge` folds one entity into another.
- **Extraction:** every paper read or skimmed gets its entities and citation links straight away, as "Extract into the graph" in the `read` skill describes. `islands` lists papers with only author, citation, or insight links, or links that only point at them: another paper that builds on a paper doesn't extract it.
- **After any change:** refresh the recap with the `recap` skill, which also draws the graph.
- **Connection questions:** use `neighbours` and `path`, and cite each connection's source.
