# Duplicate-detection evaluation: specification

Status: the pairs (`build_dataset.py`, `data/pairs.jsonl`) and the evaluation (`evaluate.py`) are built; the hand check
of the labels (`hand_check.py`) is filled in and scored (`analysis.ipynb`, section 3). It replaces the stream evaluation (`replay.py`, an earlier `evaluate.py`, the stream files), whose
headline rates were near 1.0 by construction: most repeats used a name already in the graph, the second names kept
were those a search by spelling finds, and wrong merges could come from only a few homonym pairs.

## 1. What it measures

`graph.py add` checks a new entity against the graph and gives one of three outcomes:

| Outcome | When | What happens |
|---|---|---|
| refuse | Same external id, or the same name after case and separators (`GPT-4` = `gpt 4`), unless the ids conflict | Nothing is saved. Claude is told to `update` the existing entity, or to `add --distinct` |
| ask | The name equals an existing entity's alias, or the two main names score at least `SIMILARITY` (0.5) on trigram similarity, or the same name with conflicting ids | Nothing is saved. Claude sees the candidates and decides |
| add | No candidate | Saved as a new entity |

The evaluation gives `graph.py` **pairs**: an existing entity and a new name, known to be the same thing or different
things. It records the outcome and whether it was right. Nothing else is involved: no stream of papers, no growing
graph, no model. The same pairs are replayed under different settings, so a change shows as the pairs whose outcome
changed.

| Pair is | refuse | ask | add |
|---|---|---|---|
| the same thing | right | right: the true entity is shown | **missed duplicate** |
| different things | **wrong merge** | **needless ask** | right |

A refusal hands the decision to Claude as an ask does, but in firmer words, so it counts as a wrong merge when the
two are different: the worst case. Whether Claude then decides well is out of scope.

## 2. Pairs

Each row of `data/pairs.jsonl` is one pair:

```json
{"kind": "same name", "label": "different", "type": "author", "split": "dev", "source": "dblp",
 "existing": {"gold": "dblp:17/36-1", "name": "Jing Chen", "aliases": [], "ids": {"orcid": "0000-..."}},
 "new": {"gold": "dblp:17/36-5", "name": "Jing Chen", "ids": {}}}
```

`existing` is put alone in an empty graph and `new` is added. `ids` hold the entity's real ids where the source has
them (ORCID for authors, GitHub for tools, Hugging Face for models), and every pair is replayed twice: with ids and
with names only.

| Kind | Label | Existing → new | Example | Target per split |
|---|---|---|---|---|
| similar name | same | first name → another of its names | `Tyler Phillips` → `Tyler B. Phillips` | 500 |
| known alias | same | first name with its other names as aliases → one of them | `Apache Airflow` (alias `Airflow`) → `Airflow` | 200 |
| messy | same | a name → the same name as text extracted from a PDF (section 3) | `Low-Rank Adaptation` → `Low-Rank Adap- tation` | 240 (20 per kind) |
| dissimilar name | same | first name → a name that shares no word and has an edit ratio below 0.6 | `data build tool` → `dbt` | 300 |
| look-alike | different | a seed → a different entity found by the look-alike rules (section 3) | `Yan Xia` → `Yingjie Xia`, `Llama-3.2-1B` → `Llama-3.2-1B-Instruct` | 500 |
| same name | different | an entity → a different entity with the same name | `Jing Chen` → `Jing Chen` | 300 |
| alias collision | different | an entity with aliases → a different entity named like one of them | `Jie S. Li` (alias `Jie Li`) → `Jie Li`; `Attic` (alias `Borg`) → `Borg` | 300 |

A target is a most: a kind with fewer candidates gives all it has. Within a kind the types take turns, so a type
with few candidates gives all of them and the others share the rest. Each entity is in at most one pair of a kind,
so that the pairs of a kind are independent: many DBLP people named `Jie Li` collide with the one `Jie S. Li` who
also published as `Jie Li`, and only one of them is paired with him.

Dissimilar names are reported apart and never mixed into another figure: a search by spelling can't find them, and
chasing them is out of scope. They are kept so that the scope is measured, not assumed.

Curated sources rarely give two different things the same name: of 923 Python tools in Wikidata, 1 pair shares a
main name and 4 share a name or an alias; models and Papers with Code methods have none, and most of the 19 Papers
with Code datasets that share a name are the same dataset entered twice (`20-newsgroups`, `20newsgroups`). So same-name
pairs outside authors are few, and their rates are reported with their counts. Same-name and alias-collision pairs
are only formed within DBLP and Wikidata, whose editors merge duplicates: in Papers with Code most records with the
same name are one dataset entered twice, and on the Hub a repository of the same name in another account is mostly a
copy of the same weights, so neither can say that two records are two things.

## 3. How pairs are made

### Sources

| Types | Source | Licence |
|---|---|---|
| author | DBLP: the people whose DBLP id starts with `17/` or `27/`, with every name they published under and their ORCID; homonyms are different DBLP persons with the same name, leaving out placeholder profiles (`AmbiguousCreator`) | CC0 |
| tool | Wikidata: Python software, with aliases and GitHub repository | CC0 |
| model | Wikidata: items of the large language model and machine learning model classes, with aliases; and the Hugging Face Hub: the repository names of the most downloaded models, as different things from one another | CC0; Hub metadata (repository ids only) |
| method, dataset | The Papers with Code archive of 2025-07-28: short and full names, without spam (a name of at most 40 characters, a full name of at most 120, no question, cited by at least two papers) | CC BY-SA 4.0 |

### Look-alikes

Found by rules, never by the detector's score, so the pairs don't only hold what the detector already sees: people
with the same surname and first initial; names sharing a word of four letters or more; members of one family, the
same name without its numbers (`Terminal-Bench 2.0` and `2.1`). A key shared by more than 200 entities is too
common to mean anything and is not used. A look-alike must have a different name, since identical names are
same-name pairs, and comes from the seed's own source, so that two records are known to be two things.

### Similar and dissimilar names

A second name is **similar** when it shares a whole word with the first or their edit ratio is at least 0.6,
compared in the detector's loose form. This decides only the kind of a pair, not whether it is kept.

### Messy names

Twelve changes, as names look in text extracted from PDFs, each applied to names it fits: case and spacing, another
dash, decomposed Unicode, a citation marker (`GPT-4 [12]`), a word split at a line break, trailing punctuation, a
ligature (`Eﬃcient`), a footnote mark (`Lei Li¹`), a possessive, quotation marks, an invisible character (a soft
hyphen or zero-width space), and another of its names in brackets (`Deep Graph Infomax (DGI)`).

### Labels

- **Same thing** comes from the sources' own names for one entity. DBLP's variants are curated by its editors. The
  others, similar or not, are judged by Jev, a decision model, at build time only (`audit_labels.py`), and a second name is dropped
  when Jev puts at most `MAX_SAME` probability on "same thing". Jev's answers and their cost are kept in
  `data/audit.jsonl`. Only names not yet judged are asked, and only after the cost has been estimated and approved.
- **Different things** are different records of one source: DBLP persons, Wikidata items, Hugging Face
  repositories, Papers with Code records, and only within one source. A repository and its copy in another format
  (`Llama-2-7b`, `Llama-2-7b-hf`) count as two things: the Hub lists them apart.
- **A hand check** of 200 name pairs estimates the label error rate and sets `MAX_SAME`. It is filled in: at 0.2, the names it removes were the same thing 3 times in 19, above the 10% allowed, so the scorer suggests no threshold and 0.2 stays as a known compromise.
  `hand_check.py make` writes a blind sheet, `hand-check.csv`: 100 of Jev's answers, 20 from each fifth of the
  probability it gave to "same thing" (including the names it rejected), and 100 pairs, 25 from each of the four kinds
  whose label a person can judge from the names (similar name, dissimilar name, known alias, look-alike). The sheet
  shows the type and the two names, not the first name's aliases (a known-alias pair's second name is one of them), the label, the kind, or Jev's answer. A person writes `same`, `different`, or
  `unsure`, and `hand_check.py score` reports how often the person judged the same thing in each band, how often a kind's
  label disagrees with the person, and the highest `MAX_SAME` at which the names it would remove were the same thing at
  most 10% of the time. Same-name and alias-collision pairs are not in the sheet: two people called `Jing Chen` can't be
  told apart by reading.

### Split

Dev and test, by entity: pairs that share an entity, directly or through other pairs, go to the same split, so no
entity is in pairs of both. Each group of such pairs goes to the split where its kinds have fewer pairs so far, so a
kind of a handful of pairs is shared evenly too. CI reports dev; test is read only when a change is judged.

## 4. Report

For each run (ids, names only), by kind and by kind and type, with counts (`evaluate.py`):

| Rate | Over | Counts as bad |
|---|---|---|
| Missed duplicates | same-thing pairs | add |
| Wrong merges | different-thing pairs | refuse |
| Needless asks | different-thing pairs | ask |

Each rate has a 95% Wilson interval: pairs are independent, so a binomial interval is right and no bootstrap is
needed. No rate is averaged over kinds or types: the kinds are filled to targets, not in the proportions of real use,
so an overall figure would mean nothing.

### Settings

`graph.py` has no option for these: its threshold is the constant `SIMILARITY`, fixed at 0.5, and its alias rule is
code. The evaluation imports `graph.py` and overrides them in its own process, so other settings can be tried on the
pairs without changing `graph.py`. A setting that wins is adopted by editing `graph.py` afterwards.

- `--threshold`: the similarity threshold, `graph.SIMILARITY` (0.5 today). Several values give one report each.
- `--alias-rule ask|refuse`: what a name equal to an alias does (ask today; refuse is the change of section 5).

With more than one setting, the report also lists the pairs whose outcome changed from the first setting, in both
directions. That list, not a single number, is what a change is judged on.

### Choosing the threshold

The threshold only decides between ask and add: a similarity score never refuses, so it can't cause a wrong merge.
It trades missed duplicates (similar-name and messy pairs) against needless asks (look-alike pairs). Each pair's score
is computed once, so the sweep covers every threshold from 0.30 to 0.90 in steps of 0.05 at no extra cost, and the
report shows the curve of the two rates.

The sweep is run with names only, since ids can only add refusals and so never lower the missed-duplicate rate of a
similar spelling (`evaluate.py --sweep`). The chosen threshold is the **highest one whose missed-duplicate rate on
similar-name pairs stays at or below a limit**: the fewest needless asks that still finds nearly every similar spelling. A limit is used rather than a sum
of the two rates, because the kinds are filled to targets, not in the proportions of real use, so the rates can't be
added. It is chosen on dev and confirmed on test, so it isn't tuned to the pairs that judge it. The look-alike rate
follows the look-alike rules, so the choice inherits their bias.

The limit is an open decision (section 8).

### Examples

1. Threshold 0.5 → 0.6, on dev with names only, in the committed pairs: 111 look-alike pairs go from ask to add (fewer
   needless asks), and 26 similar-name pairs go from ask to add (more missed duplicates). The list shows which, so the trade can be read pair
   by pair.
2. Alias rule ask → refuse, on dev with names only: all 200 known-alias pairs go from ask to refuse (both right; refusing saves Claude a
   choice), and every alias-collision pair goes from ask to refuse (a wrong merge each).
3. Same-name pairs on dev, names only: all 165 refuse, a wrong merge each, since nothing tells two `Jing Chen`s apart by
   name. With ids, 79 of them, those where both people have an ORCID, are asked instead, and 86 are still refused.

## 5. First change to judge

A name equal to another entity's alias is refused, like an equal name, instead of asked about. Judged by the
known-alias pairs (asks saved) against the alias-collision and same-name pairs (wrong merges added), on test, before
`graph.py` changes.

## 6. Where it runs

`build_dataset.py` builds the pairs once, by hand. It keeps every DBLP, Wikidata, and Hub response in its cache
(`--cache`, by default `.cache/sources` beside it), so with the same cache and seed a rebuild gives the same pairs; the manifest records a hash of each cached
file and of `pairs.jsonl`. The cache is not committed, and the sources change, so a rebuild without it gives other
pairs. CI never downloads anything, and the files in `data/` are frozen:
rebuilt, never edited, with the reason in the commit. CI runs the evaluation on dev at the default settings on every
push and writes the report to the job summary. It only reports; it never fails the build.

## 7. Known limits

- One existing entity per pair: the evaluation can't show asks growing as a graph fills up with look-alikes.
- Look-alike rates depend on the look-alike rules; they compare settings, they don't predict real use.
- Same-name pairs outside authors are few (section 2), and so are same-thing model pairs: the Hub lists no other
  names for a repository.
- Claude's decisions after an ask or a refusal are not measured.

## 8. Open decisions

| Decision | Proposal |
|---|---|
| Limit on missed duplicates when choosing the threshold | 5% of similar-name pairs |
| `MAX_SAME`, below which Jev's "same thing" drops a second name | 0.2 until the hand check of 200 pairs sets it |
