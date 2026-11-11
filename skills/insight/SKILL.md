---
name: insight
description: Log a takeaway worth remembering (a practice to copy, lesson, caution, or idea) to research/insights.md and connect it to its source papers in the knowledge graph. Use when the user runs /insight, or says "log this", "log these rules", "remember this insight", or "I want to keep this" about a conclusion rather than a plain fact.
argument-hint: <insight or "the rules above">
---

# Log an insight

An insight is a conclusion worth acting on or remembering, such as a practice to copy. Use the `pin` skill for facts, such as what a paper measured or which dataset it used.

## Steps

1. Work out what to log from the text given or the current discussion. Log one idea per entry, so a list of three rules becomes three entries. If it's unclear which items the user means, ask.
2. Search `research/insights.md` and run `python <skills>/graph/scripts/graph.py search <keywords>`, from the workspace root. `<skills>` is the folder that contains this skill's base directory. If the idea is already logged, add the new source to that entry instead of creating a duplicate.
3. Check the evidence against the source text, not a summary of it, including a summary from an earlier chat. Cite the section, figure, or appendix. If you can't check it, say so and use `unverified`.
4. Add the entry to `research/insights.md`, creating the file with a `# Insights` heading if it doesn't exist. Use the format below.
5. Connect it in the graph, following the `graph` skill:
   - Add an entity with `graph.py add --type insight`, using the slug from the entry's `id` and its title as `--name`.
   - For each source paper, add the paper if it's missing, then `link` the insight `derived-from` the paper. Give the section as `source`. Use status `verified` only if you checked it against the text, and `inferred` otherwise.
   - Use `related-to` for any tools, methods, or other insights it clearly connects to.
6. Reply with the saved titles, what you checked, and anything the source didn't support.

## Entry format

```markdown
## Short title stating the takeaway

- **ID:** `insight:short-slug`
- **Kind:** `practice`, `lesson`, `caution`, or `idea`
- **Insight:** What to do or remember, in one or two sentences.
- **Why:** The evidence or reasoning, in one or two sentences.
- **Sources:** `ARXIV:<id>`, section or figure. Use `none` if it comes only from the user.
- **Evidence:** `verified` (checked against the source), `unverified`, or `none`.
- **User's view:** What the user said about it, in their terms. Use `not stated` if they haven't said.
- **Tags:** Short topic tags.
- **Added:** YYYY-MM-DD
```

## Rules

- **Keep the user's view separate:** record agreement only if the user expressed it. It's useful context, not evidence.
- **Report differences:** if the source doesn't support part of the insight, change the wording to match the source and tell the user, or log that part as the user's own view.
- **Keep sources honest:** a claim from your own reasoning isn't a finding from the paper, so mark it as reasoning under **Why**.
