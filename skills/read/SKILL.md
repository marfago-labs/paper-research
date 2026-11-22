---
name: read
description: Read, summarize, analyze, discuss, and critique a paper with the user, or skim it for useful items, then extract it into the knowledge graph, propose pins, and ask for a rating. Use when the user runs /read or wants to read, summarize, analyze, review, discuss, go through, or skim a specific paper, or several.
argument-hint: <paper> [skim]
---

# Read a paper

Run commands from the workspace root. `<skills>` is the folder that contains this skill's base directory.

## Before you read

When the papers came from a search or a ranking, such as "the top 5 by citations", and not from the user naming them, check each one before reading any of them. Use its title, abstract, and the page count in the `comment` field, which `arxiv` `paper` gives. For a paper found only through Semantic Scholar, there is no page count, so use its title, abstract, and `venue`, and open the full text before you commit to a long read. A citation count ranks candidates, but it doesn't say what a document is or whether it fits the question. Leave out or flag anything that is not a paper, such as a book or lecture notes, or that is from another field than the question, and tell the user which ones and why before you read the rest.

## Get the paper

- **arXiv:** save it with the `arxiv` skill's `fetch` and read the Markdown by section. If there's no HTML version, use its `pdf` and the Read tool.
- **Other PDFs:** save to `research/pdfs/` and read with the Read tool, including figures when they matter.
- **Web pages:** use the built-in web fetch. When exact wording or numbers matter, ask it for the verbatim text of the section, and say so if the result looks summarised.

If `fetch` shows a text far longer than a paper, such as thousands of lines, or one with chapters, stop and ask the user whether to skip it or read it chapter by chapter. For a long work such as a book, read or skim it by chapter, extract each chapter you read, and say which chapters you read. Mark claims about the other chapters as unverified.

If the full text isn't available, say so and state what you are working from. If the paper isn't in `research/papers.md`, add it first, following the `add` skill.

## Deep read

1. Check `research/pins.md` and `research/papers.md` for related material.
2. Use `scholar` `paper --citations --references` to find follow-ups, replications, or contradicting work when that would help. Use the Hugging Face MCP server to check models and datasets the paper mentions.
3. Look for associated artifacts: code repos, notebooks, datasets, model weights, demos, and raw results.
   - Check the paper's links, footnotes, and availability statements, then its Hugging Face page, then search GitHub and Hugging Face by title and authors. A search by title is yours, not a link taken from the paper, so the rule about links in outside content doesn't stop it. A link found in the paper text still needs the user's go-ahead before you open it.
   - If you couldn't search a place, say "not searched" and why, never "none found". "None found" means you searched and nothing turned up.
   - For each one, record whether it's official or third-party, its licence, its last update, and what it contains compared with what reproducing the paper would need.
   - Record popularity: stars and forks for GitHub repos, downloads and likes for Hugging Face repos. Say whether a download count is for all time or for the last 30 days, and give both when the page shows both. Give the repo's age too, because a new repo can't have many stars yet. Popularity is not evidence of quality.
4. Before you show the analysis, check every number in it against the text, such as "9 of 12 benchmarks", by counting the table or reading the passage again. Counts written from memory are often wrong. Then open with the full analysis, without waiting to be asked:
   - The question, the approach, the main results, and why it matters to this user.
   - An "Artifacts" section with what step 3 found. If nothing turned up, say so and say where you looked, and list any place you didn't search. Count missing artifacts in the critique.
   - A line saying what you read: the whole paper, or which sections, such as "sections 1–5, not the appendices". Mark any claim that rests on a part you didn't read as unverified.
   - A critique: baselines, metrics, sample sizes, statistics, threats to validity, and whether the evidence supports the claims.
   - Your own position on the paper, and how it relates to anything already in the notes.
5. Extract the paper into the graph straight away, following "Extract into the graph" below, and add the short report to the end of the analysis.
6. End with 2–3 specific questions worth discussing, then continue the discussion. Take a position and push back when the evidence supports it. When a takeaway worth keeping comes up, propose it in one line, and log it with the `insight` skill if the user agrees.

## Skim

Use this when the user says `skim`, or the paper's route is `skim`. Read the full text if available and give a short summary plus candidate pins. Then extract it into the graph, following "Extract into the graph" below, and set its status in `research/papers.md` to `done`. Don't run a discussion unless the user asks for one.

## Extract into the graph

Do this for every paper you read or skim, without waiting to be asked, so no paper is left with only its authors. When you read several papers, extract each one before you reply. A long work is extracted for the chapters you read. Don't offer to save "the strongest few" instead. Change the graph only with `<skills>/graph/scripts/graph.py` commands, following the `graph` skill.

1. **The paper and its authors:** make sure the paper is in the graph with its authors, as the `add` skill does for authors, and give it its Semantic Scholar id with `update --id s2=<paperId>` if it has none. A paper read without `add` still gets its authors. A work with no author to record, such as an anonymous submission or a post with no byline, gets `update <paper> --no-authors "<reason>"` instead. Never make up an author.
2. **What to extract:** every dataset, benchmark, model, method, tool, and key concept that has a role in the paper: what it proposes, builds on, uses, or evaluates on, the baselines it compares against (`compared-with`, from the paper or its method to the baseline), the models it runs, and the models it uses as judges. A passing mention is a name with no role in this paper, such as one cited only in related work, and is skipped. For a survey, extract its concepts and taxonomy, and the systems it compares in its tables. Use the paper's own names, and keep exact versions, such as Terminal-Bench 2.0 rather than Terminal-Bench. Pass every other name you know for it with `--alias`, such as its acronym or expansion (`RAG`, `Retrieval-Augmented Generation`) or a common short name (`sklearn`): the duplicate check can only find an existing entity through a name it shares.
3. **Link first:** run `add` for each one with its link to the paper as the first link, such as `--link-from <paper> proposes --source "ARXIV:<id>, §3.2" --status verified`, and act on the result:
   - **Added:** it's new.
   - **Already in the graph:** reuse that entity. If the paper uses a different name for it, add the name with `update --alias`.
   - **Possible duplicates (exit 3):** decide for each candidate on its own. If it's the same thing, reuse it and add the alias. If it's different, run `add` again with `--distinct` for each candidate. If you can't tell, ask the user rather than guess. Never mark candidates distinct in bulk, or with a script that does: the check flags many false pairs, and the same shortcut would let a real duplicate through.
   - **Ids:** add external ids when you know them, such as `hf=` for Hugging Face repos and `github=` for code.
4. **Relations:** `link` the paper to each entity that was already in the graph, and add any further links, with the paper and section as `--source`, such as `"ARXIV:<id>, §3.2"`. Choose the status for each link on its own, never one for all: `verified` only when you checked it in the text and the paper made the claim itself, `reported` when the paper only reports another study's result, such as a survey's table of other papers' scores, with that study named in the source (if you later check it in that study, `link` it again as `verified`), and `inferred` for your own reading, such as two papers from the same group, with the reason as its source. Link two entities to each other only when the paper says how they connect.
5. **Citations:** run `python <skills>/scholar/scripts/s2.py batch <ID> --with-references` and save its output to a file in a temporary folder, then run `graph.py standing <file>`. That is one request. It saves the paper's citation counts and links the paper to every paper in the graph that it cites. If either step fails, say so in this reply: give the error line, and say this paper has no citation counts or links yet. Carry on with the other papers, because one failure says nothing about the next. When you finish, offer to retry the ones that failed, and say that a free Semantic Scholar API key (`SEMANTIC_SCHOLAR_API_KEY`) prevents most rate-limit errors. Zero links added is normal, because links only connect papers that are already in the graph.
6. **Check:** run `graph.py validate` and fix anything it lists, such as an entity with no links or a paper with no authors. It lists every such paper in the graph, not only this one, so the first run after papers were saved without authors may add several: fetch them in one `s2.py batch` call. Then run `graph.py dupes`. Resolve any new pair with `merge` or `update --distinct`, asking the user when it isn't clear.
7. **Report in two or three lines:** how many entities were added, which existing entities it now links to, how many citation links were found, any duplicate decisions you made, and any paper you gave a reason instead of authors, with the reason. The user can ask you to undo any of it with `remove` or `unlink`.

## Finish

1. Propose pins and any insights not yet logged as a short list, and save only those the user accepts, following the `pin` and `insight` skills.
2. Add anything new from the discussion to the graph the same way as the extraction, and mention it in one line.
3. Ask for a rating from 1 to 5.
4. Update the paper's row in `research/papers.md`: set its status to `done`, and add the rating and a summary from the full text. The status `read` means still to read, so never use it for a paper you have read.
5. If the session shows a lasting preference, propose a change to `research/profile.md`. Change it only if the user approves.
