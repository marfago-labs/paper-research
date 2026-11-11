# Duplicate-detection pairs

The frozen pairs of the duplicate-detection evaluation, built by `build_dataset.py` as `SPEC.md` section 3 describes. Don't edit these files by hand: rebuild them, and say why in the commit.

| File | Content |
|---|---|
| `pairs.jsonl` | One pair per line: its kind, its label (`same` or `different`), its type, source and split, the existing entity (gold id, name, aliases, ids), and the new name (gold id, name, ids). Messy pairs also name the change made |
| `audit.jsonl` | Jev's answer for each second name it judged, with its probabilities, model snapshot, tokens and cost. The builder reads it; `build_dataset.py --audit` adds to it |
| `manifest.json` | When and how the pairs were built: seed, targets, pairs by split, kind and type, pool sizes, queries, licences, what the audit removed, and the SHA-256 of `pairs.jsonl` and of each cached source response |

The source responses are kept, not committed, in `evals/dedup/.cache/sources`. With that folder and the same seed, `build_dataset.py` rebuilds exactly these pairs; without it, it downloads the sources again, and they will have changed.

## Sources and licence

| Types | Source | Licence |
|---|---|---|
| author | [dblp computer science bibliography](https://dblp.org/) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| tool, model | [Wikidata](https://www.wikidata.org/) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| model | The [Hugging Face Hub](https://huggingface.co/models) API: repository ids of the most downloaded models, no model content | Repository ids only |
| method, dataset | The [Papers with Code archive](https://huggingface.co/datasets/pwc-archive/files) of 2025-07-28 | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |

The files mix these sources, so they are shared under **CC BY-SA 4.0**, with the method and dataset names attributed to Papers with Code. The rest of the repository keeps its own licence.
