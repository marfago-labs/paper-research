# Knowledge graph

The graph records what papers use, build on, and are evaluated on, and how those things connect to each other. It's how Claude can answer "which papers use Terminal-Bench?" or "how does this paper connect to that one?" from your own reading, with a source for every connection.

It lives in two files, `research/graph/entities.jsonl` and `research/graph/relations.jsonl`, with one JSON object per line. The files are the source of truth. Pins keep the facts, and the graph shows how things connect.

## Entities

Each entity has an `id` of the form `type:slug`, a `type`, a `name`, a list of `aliases`, and optionally a `url`, a `note`, external `ids`, and a `distinct_from` list.

| Type | What it is | Example id |
|---|---|---|
| `paper` | A paper or post. arXiv papers use the arXiv ID as the slug. | `paper:2611.05306` |
| `author` | A person | `author:peter-belcak` |
| `concept` | An idea | `concept:semantic-state-space-model` |
| `method` | A technique | `method:retrieval-augmented-generation` |
| `model` | A trained model | `model:qwen-3-coder-next` |
| `dataset` | A dataset or benchmark | `dataset:terminal-bench-2-1` |
| `tool` | Software | `tool:mini-swe-agent` |
| `organisation` | A lab or company | `organisation:nvidia` |
| `insight` | A logged takeaway | `insight:review-agent-read-only` |

### External ids

Names are unreliable, especially for people, so an entity can carry stable identifiers in `ids`: `s2` (Semantic Scholar), `arxiv`, `doi`, `hf` (Hugging Face), `github`, or `orcid`. Two entities of the same type with the same external id are the same thing. Entities of different types may share one, such as a Hugging Face model and dataset with the same `org/name`. Claude records Semantic Scholar ids for papers and authors whenever it has them.

## Relations

A relation connects two entities and says where it comes from.

| Field | Meaning |
|---|---|
| `from`, `rel`, `to` | The connection. `rel` is one of `uses`, `evaluates-on`, `builds-on`, `proposes`, `cites`, `authored-by`, `contradicts`, `related-to`, `derived-from`. |
| `source` | Where it comes from, such as `ARXIV:2611.05306, §2.2`. |
| `status` | `verified` if it was checked against the source, or `inferred` if it's Claude's own reading. An inference is never marked verified. |

## How papers get in

- **`add` saves a paper and its authors** with their Semantic Scholar ids, and adds `authored-by` links and any citation links to papers you already have.
- **`read` extracts the rest, immediately,** without waiting for you to ask: the datasets, models, methods, tools, and concepts the paper uses, evaluates on, builds on, or proposes. It links each one to an existing entity when there is one, and adds a new entity when there isn't.
- **Citation links come from Semantic Scholar.** For each paper it fetches the references and the citing papers, and adds a `cites` link wherever the other paper is also in your graph. These are marked `verified`.

A paper with only its authors and citations in the graph hasn't been extracted yet. The recap page lists those under **Needs graph extraction**, and `graph.py islands` prints them. The page also lists any paper whose full text is saved in `research/fulltext/` but that `papers.md` doesn't list, because Claude read it without running `read`.

## Duplicates

The graph checks for duplicates itself, because by the time it has a few hundred entities, asking Claude to remember to search first isn't enough.

Adding an entity is refused or held back when it matches an existing one of the **same type**. The check is deliberately simple: it refuses only what needs no judgement, and holds anything that looks alike so that Claude can judge it.

| Situation | Result |
|---|---|
| Same external id | Refused, pointing to the existing entity |
| Same name, ignoring case, spaces, dashes, and underscores (`GPT-4` and `gpt 4`) | Refused |
| Same name, but both have an external id of the same kind with different values | Held back for a decision, exit code 3 |
| The new name is the other's alias, or the other way round | Held back |
| A similar name | Held back |

**Similar** means the two names share at least half of the shorter one's three-letter sequences, once accents, punctuation, and symbols are ignored. That one measure catches versions (`Terminal-Bench 2.0` and `2.1`), accents (`Jürgen` and `Jurgen`), initials (`J. Smith` and `John Smith`), reordered names (`Chang Ming-Wei`), and one name inside another (`MMLU` and `MMLU-Pro`). It also holds some names that are different, such as `C` and `C++`, which Claude then marks as distinct. If `add` holds too often or too rarely, the threshold is `SIMILARITY` in `graph.py`.

**Acronyms and other names** can't be recognised from spelling: nothing in `RAG` says `Retrieval-Augmented Generation`. So when Claude adds an entity, it passes the other names it knows with `--alias`, such as the acronym or the expansion, and the check finds the existing entity through them.

Ids are made from the name and only have to be unique. If one is taken, `add` uses the next free one, such as `tool:c-2`, so an id never decides whether two things are the same. Pass `--slug` to choose an id yourself.

When something is held back, Claude decides, or asks you if it can't tell:

- **It's the same thing:** it adds the new name as an alias of the existing entity.
- **It's different:** it adds the entity again, marking it as distinct from each candidate. That decision is saved in `distinct_from`, so the pair isn't flagged again.

Two different entities of different types may share a name, such as a paper and the model it introduces. Two people with the same name can both exist, but only when marked distinct, and Claude then refers to them by id.

You can ask Claude to check the whole graph at any time (`graph.py dupes`) and to merge two entities that turn out to be the same (`merge`), which moves every connection across. To stay fast on a large graph, `dupes` skips three-letter sequences that more than 50 entities of the same type share, so it can miss a pair that `add` would hold. An empty `dupes` report isn't proof that there are no duplicates.

## Safe changes

All changes go through `graph.py`, which:

- **Takes a lock,** so two windows working on the same graph at once don't lose each other's changes. The lock is released by the operating system if a command crashes.
- **Validates the whole graph before saving,** and refuses the change if it would make it invalid.
- **Saves crash-safely.** Both files are written in full, marked complete, then swapped in. If a save is interrupted, the next command finishes it or discards it.

Don't edit the JSONL files by hand: a mistake there makes every command refuse to load the graph.

## Asking questions

Ask Claude in plain words. It uses these, and cites the source of each connection:

- **What's connected to X:** `neighbours`, with a depth.
- **How two things connect:** `path`, the shortest chain between them.
- **What's in the graph:** `stats`, `search`.

The recap page's Graph tab is the visual version: search, filter by type, and click an entity to see its connections and where each one comes from.

For every option of every command, see the [command reference](reference.md#graph).
