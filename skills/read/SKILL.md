---
name: read
description: Read, summarize, analyze, discuss, and critique a paper with the user, or skim it for useful items, then extract it into the knowledge graph, propose pins, and ask for a rating. Use when the user runs /read or wants to read, summarize, analyze, review, discuss, go through, or skim a specific paper, or several.
argument-hint: <paper> [skim]
---

# Read a paper

Run commands from the workspace root. `<skills>` is the folder that contains this skill's base directory.

## Get the paper

- **arXiv:** save it with the `arxiv` skill's `fetch` and read the Markdown by section. If there's no HTML version, use its `pdf` and the Read tool.
- **Other PDFs:** save to `research/pdfs/` and read with the Read tool, including figures when they matter.
- **Web pages:** use the built-in web fetch. When exact wording or numbers matter, ask it for the verbatim text of the section, and say so if the result looks summarised.

If the full text isn't available, say so and state what you are working from. If the paper isn't in `research/papers.md`, add it first, following the `add` skill.

## Deep read

1. Check `research/pins.md` and `research/papers.md` for related material.
2. Use `scholar` `paper --citations --references` to find follow-ups, replications, or contradicting work when that would help. Use the Hugging Face MCP server to check models and datasets the paper mentions.
3. Look for associated artifacts: code repos, notebooks, datasets, model weights, demos, and raw results.
   - Check the paper's links, footnotes, and availability statements, then its Hugging Face page, then search GitHub and Hugging Face by title and authors.
   - For each one, record whether it's official or third-party, its licence, its last update, and what it contains compared with what reproducing the paper would need.
   - Record popularity: stars and forks for GitHub repos, downloads and likes for Hugging Face repos. Give the repo's age too, because a new repo can't have many stars yet. Popularity is not evidence of quality.
4. Open with the full analysis, without waiting to be asked:
   - The question, the approach, the main results, and why it matters to this user.
   - An "Artifacts" section with what step 3 found. If nothing turned up, say so and say where you looked. Count missing artifacts in the critique.
   - A critique: baselines, metrics, sample sizes, statistics, threats to validity, and whether the evidence supports the claims.
   - Your own position on the paper, and how it relates to anything already in the notes.
5. Extract the paper into the graph straight away, following "Extract into the graph" below, and add the short report to the end of the analysis.
6. End with 2–3 specific questions worth discussing, then continue the discussion. Take a position and push back when the evidence supports it. When a takeaway worth keeping comes up, propose it in one line, and log it with the `insight` skill if the user agrees.

## Skim

Use this when the user says `skim`, or the paper's route is `skim`. Read the full text if available and give a short summary plus candidate pins. Then extract it into the graph, following "Extract into the graph" below. Don't run a discussion unless the user asks for one.

## Extract into the graph

Do this for every paper you read or skim, without waiting to be asked, so no paper is left with only its authors. When you read several papers, extract each one before you reply. Don't offer to save "the strongest few" instead. Change the graph only with `<skills>/graph/scripts/graph.py` commands, following the `graph` skill.

1. **The paper:** make sure it's in the graph, as the `add` skill does, and give it its Semantic Scholar id with `update --id s2=<paperId>` if it has none.
2. **What to extract:** the datasets, models, methods, tools, and key concepts the paper uses, evaluates on, builds on, or proposes. Skip passing mentions. Use the paper's own names, and keep exact versions, such as Terminal-Bench 2.0 rather than Terminal-Bench. Pass every other name you know for it with `--alias`, such as its acronym or expansion (`RAG`, `Retrieval-Augmented Generation`) or a common short name (`sklearn`): the duplicate check can only find an existing entity through a name it shares.
3. **Link first:** run `add` for each one, and act on the result:
   - **Added:** it's new.
   - **Already in the graph:** reuse that entity. If the paper uses a different name for it, add the name with `update --alias`.
   - **Possible duplicates (exit 3):** decide for each candidate. If it's the same thing, reuse it and add the alias. If it's different, run `add` again with `--distinct` for each candidate. If you can't tell, ask the user rather than guess.
   - **Ids:** add external ids when you know them, such as `hf=` for Hugging Face repos and `github=` for code.
4. **Relations:** `link` the paper to each entity, with the section as `--source`. Use `--status verified` only when you checked it in the text, and `inferred` for your own reading. Link two entities to each other only when the paper says how they connect.
5. **Citations:** run `python <skills>/scholar/scripts/s2.py batch <ID> --with-references` and save its output to a file in a temporary folder, then run `graph.py standing <file>`. That is one request. It saves the paper's citation counts and links the paper to every paper in the graph that it cites. If either step fails, say so in this reply: give the error line, and say this paper has no citation counts or links yet. Carry on with the other papers, because one failure says nothing about the next. When you finish, offer to retry the ones that failed, and say that a free Semantic Scholar API key (`SEMANTIC_SCHOLAR_API_KEY`) prevents most rate-limit errors. Zero links added is normal, because links only connect papers that are already in the graph.
6. **Duplicates:** run `graph.py dupes`. Resolve any new pair with `merge` or `update --distinct`, asking the user when it isn't clear.
7. **Report in two or three lines:** how many entities were added, which existing entities it now links to, how many citation links were found, and any duplicate decisions you made. The user can ask you to undo any of it with `remove` or `unlink`.

## Finish

1. Propose pins and any insights not yet logged as a short list, and save only those the user accepts, following the `pin` and `insight` skills.
2. Add anything new from the discussion to the graph the same way as the extraction, and mention it in one line.
3. Ask for a rating from 1 to 5.
4. Update the paper's row in `research/papers.md`.
5. If the session shows a lasting preference, propose a change to `research/profile.md`. Change it only if the user approves.
