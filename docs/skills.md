# Skills

The plugin is a set of skills. Claude chooses one from what you say, and you can also name one directly, for example `/paper-research:read`. Each skill below says what triggers it, what it does, and which files it changes.

| Skill | Use it to |
|---|---|
| [add](#add) | Save links and decide what to do with each |
| [next](#next) | Get recommendations |
| [read](#read) | Analyse and discuss a paper |
| [pin](#pin) | Save a fact |
| [insight](#insight) | Save a takeaway |
| [graph](#graph) | Query or change the knowledge graph |
| [recap](#recap) | Refresh the recap page |
| [scholar](#scholar-and-arxiv) and [arxiv](#scholar-and-arxiv) | Look things up (used by the others) |
| [init](#init) | Set up or update a workspace |

## Links without a command

- **One link, nothing else:** Claude runs `read` on it straight away.
- **Several links, or "for later" or "save this":** Claude runs `add` on them.

## add

**Triggers:** you paste several links, say "for later", or ask to save something.

**Does:**

1. Skips links already in `research/papers.md`, and tells you which.
2. Looks up each paper on Semantic Scholar in one request. For other links it reads the page, or checks a repository with `gh`.
3. Gives each link a route, based on your profile:
   - `read`: worth a deep read.
   - `skim`: useful parts can be pulled out without a full read.
   - `archive`: keep it searchable, with no plan to read it.
4. Adds one row per link to `research/papers.md`.
5. Adds each paper and its authors to the knowledge graph, with the citation links between papers you already have.
6. Replies with the paper-list table (publication date, title, linked ID, citations, topic, and a one-line reason), plus the route.

A link Claude can't read is saved as `unread-link` instead of guessed at. The route is a suggestion, so tell Claude if you disagree.

**Changes:** `research/papers.md`, the graph.

## next

**Triggers:** "what should I read next?", or `next` with a topic.

**Does:**

1. Reads your profile, your paper list, and the questions you've asked, to find what you keep coming back to.
2. Gathers candidates from your own list, from Semantic Scholar's recommendations based on papers you rated 4 or 5, from new arXiv papers on your topics, and from Hugging Face's daily papers.
3. Drops anything you already have, and picks one or two, or more if you ask.
4. Shows the picks in the paper-list table: **publication date**, title, linked ID, citations, topic, why it matches you and a caution, its academic standing, and whether it's on your list or new.
5. Rates each pick's standing in the research community as `High`, `Medium`, `Low`, or `Too early`, with the evidence: citations for its age, venue, and the highest author h-index. This is Claude's judgement from that evidence, not a calculated score, and it says nothing about whether the paper is correct.

About one in five picks is outside your usual topics, and is labelled so.

**Changes:** nothing, until you accept a paper.

## read

**Triggers:** you paste one link, or ask to discuss, go through, or skim a paper. Add `skim` for a short summary without a discussion.

**Does:**

1. **Gets the paper.** For arXiv, it saves the HTML version as Markdown, which keeps section headings, tables, and maths, and reads it by section so it can cite the section a claim comes from. If there's no HTML version, it downloads the PDF and reads it directly. Other PDFs are saved in `research/pdfs/`, and web pages are fetched.
2. **Looks for artifacts:** code repositories, notebooks, datasets, model weights, and demos. For each it records whether it's official, its licence, its last update, and its popularity (stars, forks, downloads) with the repository's age. Popularity is not evidence of quality.
3. **Analyses.** It gives the question, approach, results, and why it matters to you, then a critique of the baselines, metrics, sample sizes, and threats to validity, and its own position.
4. **Extracts into the graph, straight away.** It adds the datasets, models, methods, tools, and concepts the paper uses, links them to what's already in your graph, finds citation links to your other papers, and checks for duplicates. It reports in two or three lines, and you can ask it to undo any of it. See [Knowledge graph](knowledge-graph.md#how-papers-get-in).
5. **Discusses.** It ends with two or three questions and pushes back when the evidence supports it.
6. **Finishes.** It proposes pins and insights for you to accept, asks for a rating from 1 to 5, and updates the paper's row.

Everything it says about a paper cites the section, page, or figure. If it only had the abstract, it says so.

**Changes:** `research/papers.md`, `research/pins.md`, `research/insights.md`, the graph, `research/fulltext/`, `research/pdfs/`.

## pin

**Triggers:** `pin` with some text, or "pin that" or "save this" about a fact.

**Does:** saves one fact in one or two sentences, with its source, to `research/pins.md`. A tool, dataset, or model gets a link, checked first when possible. If the fact is already pinned, it updates the entry instead of adding a duplicate. It states how far to trust it:

- `verified`: checked against the source text.
- `from-skim`: taken from an abstract or a skim.
- `user-note`: your own idea or statement.

Use `pin` for what a paper says or measured. Use `insight` for what to do about it.

## insight

**Triggers:** `insight` with some text, or "log this" or "I want to keep this" about a conclusion.

**Does:** saves a structured entry in `research/insights.md`, one idea per entry, so a list of three rules becomes three entries. It checks the evidence against the source text, not against a summary, and cites the section. It records your view separately from the evidence, and connects the entry to its source papers in the graph. The entry format is in [Your workspace](workspace.md#insightsmd).

If part of an insight isn't supported by its source, Claude rewords it to match, tells you, or logs that part as your own view.

## graph

**Triggers:** another skill adds to the graph, or you ask how things connect, what's in the graph, or to fix a duplicate.

**Does:** all changes to the knowledge graph go through this skill's script, which takes a lock, checks for duplicates, and validates the whole graph before saving. Claude never edits the graph files directly. See [Knowledge graph](knowledge-graph.md) and the [command reference](reference.md#graph).

## recap

**Triggers:** after any change to your files, or when you ask to see what's been done.

**Does:** copies the recap page into `research/recap/` and writes its data from your files. It prints the page's path. Open it in a browser. See [Your workspace](workspace.md#the-recap-page).

## scholar and arxiv

Read-only clients for [Semantic Scholar](https://www.semanticscholar.org/product/api) and [arXiv](https://info.arxiv.org/help/api/index.html), used by the other skills. You rarely call them yourself. Both contact only their own fixed hosts, space their requests as the services ask, and retry for at most 90 seconds.

- **scholar:** search, paper details with citations and references, batch lookups, recommendations from papers you like and dislike, and author statistics.
- **arxiv:** search with categories, dates, and sorting by newest, metadata for several papers at once, full text as Markdown, and PDF download.

Whenever Claude lists papers, it uses one table: `Published | Title | ID | Citations | Topic | Note`. The ID is a link to the paper, which both clients build. Citations come from one Semantic Scholar request for the whole list: `-` means Semantic Scholar has no count, and `?` means the request failed. The note is one sentence on the main result or why the paper matters to you.

Paper text and abstracts come from outside your workspace. Claude treats them as data, never as instructions.

## init

**Triggers:** `/paper-research:init`, a new workspace, or after updating the plugin. See [Getting started](getting-started.md#set-up-a-workspace).

**Does:** shows what it would change, asks, then creates missing starter files, refreshes the rules block in `CLAUDE.md`, merges settings, and adds `.gitignore` entries. It never overwrites a file in `research/`. With `--sandbox`, it also turns on Claude Code's sandbox for shell commands. See [Security](security.md#the-sandbox).
