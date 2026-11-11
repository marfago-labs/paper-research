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
6. For each pick, give the title, publication date, link, why it matches this user, its academic rating with the evidence, and one reason to be cautious if there is one. Say whether it is on their list or newly found.
7. About 1 in 5 recommendations should be outside the usual topics. Label it `outside your usual topics`, and keep the other pick on target.

Don't add new papers to `research/papers.md` unless the user accepts them. If a source fails, say so and continue with the others.
