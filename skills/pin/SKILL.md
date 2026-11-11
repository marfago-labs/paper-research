---
name: pin
description: Save a fact, such as a concept, finding, method, tool, or dataset, to research/pins.md with its source. Use when the user runs /pin or says "pin that" or "save this" about a fact from a paper or discussion. For takeaways and practices to copy, use /insight.
argument-hint: <text>
---

# Pin something

1. Work out what to pin from the text given, or from the current discussion. If it's unclear which item the user means, ask.
2. Check `research/pins.md` for an existing entry, and update that instead of adding a duplicate.
3. Add one entry to `research/pins.md` in the format described at the top of that file. Keep it to one fact in one or two sentences.
4. Choose the status honestly:
   - `verified`: checked against the source text.
   - `from-skim`: taken from an abstract or a skim, not checked.
   - `user-note`: the user's own idea or statement.
5. Reply with the saved entry only.

For a tool, dataset, or model, include its link. Check that it exists first with the Hugging Face MCP server or `gh` when that's possible.
