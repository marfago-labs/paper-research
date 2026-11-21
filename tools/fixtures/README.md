# Recorded replies

Real replies from arXiv and Semantic Scholar, recorded by `tools/record_responses.py` for
`tools/test_recorded_responses.py`.

| File | Source | Licence | Changes |
|---|---|---|---|
| `arxiv-2303.11366.html` | arXiv HTML of [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366), Shinn et al. | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Cut after section 2; email addresses replaced with `author@example.org`. |
| `arxiv-feed.xml` | arXiv API reply for 2303.11366 and [2107.03374](https://arxiv.org/abs/2107.03374) | arXiv metadata, [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | None. |
| `s2-batch.json` | [Semantic Scholar](https://www.semanticscholar.org) API batch reply for the two papers and one unknown id | Semantic Scholar data, used with attribution under the [API License Agreement](https://www.semanticscholar.org/product/api/license) | Each paper keeps 3 of its references, including the one to 2107.03374; reindented. |
