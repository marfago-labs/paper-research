---
name: next
description: Recommend what to read next from the user's list and newly found papers, matched to their preferences. Use when the user runs /next or asks what to read.
argument-hint: "[topic]"
---

# Recommend what to read

1. Read `research/profile.md`, `research/papers.md`, and `research/user-facts.md`, looking for topics the user keeps returning to. If the user gave a topic, focus on it.
2. Gather candidates:
   - **Your list:** papers with status `read`.
   - **Similar to rated papers:** `scholar` `recommend`, using papers rated 4–5 as `--like` and 1–2 as `--dislike`. Skip this until something is rated 4–5.
   - **New on arXiv:** search the topics in `research/profile.md` with the `arxiv` skill, using `--sort new` and `--since` for recent work and `--category` to stay on topic.
   - **Community interest:** https://huggingface.co/papers, read with the built-in web fetch.
3. Remove anything already in `research/papers.md` with a status other than `read`.
4. Pick 1–2 papers, unless the user asks for more. Weigh fit with the profile first, then quality signals such as citations for the paper's age, venue, and available code.
5. Rate each pick's standing in the academic community, using `scholar` `batch` and `authors`:
   - **Evidence to show:** citations and influential citations with the paper's age, the venue and whether it's peer-reviewed, and the highest author h-index with that author's name.
   - **Rating:** `High`, `Medium`, `Low`, or `Too early`. It's your judgement from that evidence, so don't present it as a calculated score.
   - **New papers:** citations mean little in the first few months, so rate from the authors and venue, or use `Too early` if they don't settle it.
   - **Keep it separate:** this measures attention and standing, not whether the paper is correct or fits the user. If the data isn't available, say so rather than estimating.
   - **One set of counts:** use the counts from this `batch` call for both the `Citations` column and the rating, never an older saved count. If the call fails, follow the paper-list rule: write `?` and say so, or, for a pick in the graph, use the saved count that `graph.py search <id>` shows, with the date it was checked, for both. Save the `batch` output to a file and run `graph.py standing <file>`, so the counts are kept for the picks already in the graph.
6. Show the picks as the paper-list table under [Listing papers](#listing-papers), with `Standing` and `Source` after `Note`. `Note` says why it matches this user, and one reason to be cautious if there is one. `Standing` is the academic rating with its evidence. `Source` is `your list` or `new`.
7. About 1 in 5 recommendations should be outside the usual topics. Label it `outside your usual topics`, and keep the other pick on target.

Don't add new papers to `research/papers.md` unless the user accepts them. If a source fails, say so and continue with the others.

## Listing papers

Whenever you list papers to the user, use one table with the columns `Published | Title | ID | Citations | Topic | Note`, in that order. `Published` is the publication date as `YYYY-MM-DD`, from `published` in `arxiv` or `publicationDate` in `scholar`, or `unknown`; never guess it. `ID` is the paper's `link` from `arxiv` or `scholar`, such as `[ARXIV:2611.14326](https://arxiv.org/abs/2611.14326)`, copied as it is so that it stays a link, or the link itself for anything else, such as a blog post or a repository. `Citations` is `citationCount` from one `scholar` `batch` call for all the listed papers, made for every list, so the counts are all from the same moment. Write `-` only when Semantic Scholar has no count. If the call fails, write `?` and say so below the table, or, for a paper in the graph, use the saved count that `graph.py search <id>` shows, with the date it was checked. `Topic` is two to five words. `Note` is one sentence: the main result, or why the paper matters to this user, not details such as the venue, page count, or code. A skill may add its own columns after `Note`. Put the total, caveats, and suggestions below the table, not in it.
