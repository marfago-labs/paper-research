# Architecture

The plugin is a set of skills, five standard-library Python scripts, four hooks, and a static page. It has no server and no database: everything it keeps is a plain file in your workspace.

```mermaid
flowchart LR
    subgraph session["Claude Code session"]
        claude["Claude"]
        perms["Claude Code permissions"]
    end

    subgraph plugin["Plugin"]
        skills["Skills<br/>add, next, read, pin, insight,<br/>graph, recap, scholar, arxiv, init, debug"]
        hooks["Hooks<br/>hooks/hooks.json<br/>SessionStart, PreToolUse, Stop"]
        subgraph scripts["Scripts (Python standard library)"]
            arxivpy["arxiv.py"]
            s2py["s2.py"]
            graphpy["graph.py"]
            recappy["recap.py"]
            initpy["init.py"]
        end
    end

    subgraph workspace["Workspace"]
        notes["research/*.md<br/>papers, pins, insights,<br/>user facts, profile, lessons"]
        graphfiles["research/graph/<br/>entities.jsonl, relations.jsonl"]
        fulltext["research/fulltext/<br/>research/pdfs/"]
        page["research/recap/<br/>recap.html, recap-data.js"]
    end

    arxivhost["arXiv<br/>arxiv.org, export.arxiv.org"]
    s2host["Semantic Scholar API<br/>api.semanticscholar.org"]
    hf["Hugging Face MCP server<br/>(optional)"]
    browser["Your browser"]

    perms -. enforce .-> claude
    claude -->|"follows"| skills
    skills -->|"run"| scripts
    claude -->|"edits"| notes
    claude -. "models, datasets" .-> hf
    arxivpy -->|"HTTPS, read only"| arxivhost
    s2py -->|"HTTPS, read only"| s2host
    arxivpy -->|"saves cleaned Markdown"| fulltext
    graphpy -->|"locked, validated writes"| graphfiles
    recappy -->|"reads"| notes
    recappy -->|"reads"| graphfiles
    recappy -->|"reads"| fulltext
    recappy -->|"writes"| page
    initpy -->|"starter files"| notes
    hooks -->|"init.py --hook rules, lessons:<br/>rules and lessons into context"| claude
    hooks -->|"init.py --hook guard:<br/>ask before edits and fetches"| perms
    hooks -->|"recap.py --stop-hook"| recappy
    page --> browser
```

## Components

| Component | What it does | What it writes |
|---|---|---|
| **Skills** (`skills/*/SKILL.md`) | Instructions Claude follows for each task: which script to run, what to check, and what to tell you. They hold the judgement; the scripts hold the rules a script can check. | Nothing themselves. Claude edits the Markdown files in `research/` as a skill says. |
| **`arxiv.py`** | Searches arXiv, reads a paper's metadata, saves its HTML version as Markdown, or downloads its PDF. Removes scripts, hidden text, and invisible characters. | `research/fulltext/`, `research/pdfs/`, and request-pacing state in `.cache/`. With `--out`, a JSON file in `research/` or a temporary folder. |
| **`s2.py`** | Queries Semantic Scholar: search, paper details, citations, references, batch lookups, and recommendations. Read only. | Request-pacing state in `.cache/`. With `--out`, a JSON file in `research/` or a temporary folder. |
| **`graph.py`** | The only way to change the knowledge graph. Checks duplicates, relation types, and sources, validates the whole graph, and saves under a lock, crash-safely. | `research/graph/entities.jsonl` and `relations.jsonl`. |
| **`recap.py`** | Builds the recap page's data from your research files and the graph. With `--stop-hook`, decides whether Claude should refresh the page before ending a turn. | `research/recap/`. Nothing with `--stop-hook`. |
| **`init.py`** | Sets up a workspace. With `--hook`, gives Claude the rules and lessons when a session starts, and decides whether an edit or a fetch needs your approval. | The starter files in `research/`, and `.gitignore` entries. Nothing with `--hook`. |
| **Hooks** (`hooks/hooks.json`) | Two `SessionStart` hooks print the rules and `research/lessons.md` into Claude's context. A `PreToolUse` hook asks you before an edit to `lessons.md` or `profile.md` and before a fetch from the paper sites. A `Stop` hook runs `recap.py --stop-hook` and stops Claude once if the recap is out of date. All act only in a workspace, and never fail a session. | Nothing. |
| **`debuglog.py`** | Records what the scripts and hooks do, while `research/.debug` exists. Every other script imports it. Also turns the log on and off, and prints it. | `research/.debug.log`, at most 2 MB, then `.debug.log.1`. Nothing while the log is off. |
| **Recap page** (`skills/recap/page/`) | A fixed page with all its rendering in `recap-lib.js`, and the graph drawn with a vendored copy of Cytoscape.js. It loads only files next to it, so it works offline. | Nothing. |

## Trust boundaries

- **Paper text is untrusted.** The plugin's scripts are the main way in: `arxiv.py` and `s2.py` contact fixed hosts, refuse redirects elsewhere, cap each response, and remove hidden text and invisible characters. Pages Claude fetches itself, PDFs, and other tools' results are not cleaned. Claude is told to treat all of it as data.
- **Your notes stay local.** No script sends your notes, only search queries and paper ids. The rules tell Claude not to send them either, and the optional sandbox limits shell commands to arXiv and Semantic Scholar.
- **The plugin's instruction files are protected.** Claude Code asks before its file tools edit `lessons.md` or `profile.md`, through the plugin's hook. `CLAUDE.md` and `.claude/` are left to Claude Code's own protection.

[Security](security.md) says which of these are enforced and which are only instructions.

## How a paper gets into the graph

See [Knowledge graph](knowledge-graph.md#how-papers-get-in) for the steps, with a diagram.

## Design decisions

- **Semantic Scholar (2026-11-05):** a read-only standard-library script with a fixed host and an optional API key from `SEMANTIC_SCHOLAR_API_KEY`, not an MCP server. Without a key, `search` is heavily rate-limited.
- **arXiv (2026-11-07):** a standard-library script, not an MCP server. It reads arXiv's HTML version as Markdown, and falls back to the PDF read by Claude Code's Read tool, so it needs no PDF converter.
- **Distribution (2026-11-07):** a Claude Code plugin.
- **Rules and approval prompts from hooks (2026-11-17):** plugins can't carry permission rules or `CLAUDE.md` content, so `init` used to write both into the workspace, and the user had to run that step, because auto mode stops Claude from changing its own permissions. Now `SessionStart` hooks give Claude the rules and lessons, and a `PreToolUse` hook returns an approval prompt, as Claude Code's documentation recommends for plugins. Nothing is written to `CLAUDE.md` or the settings, an update needs no step, and the prompts cover only the plugin's own files and the paper sites, so another plugin sees them only when it uses those. The lessons have their own hook because Claude Code keeps only 10,000 characters of each hook's output. The sandbox stays a setting the user adds, because a plugin can't turn it on.
- **Stop hook (2026-11-15):** one `Stop` hook, because rules in `CLAUDE.md` to refresh the recap and log questions were dropped after long chains of skills. It only reads the research files, asks at most once a turn, and lets the turn end on any error.
- **Graph storage:** two JSONL files changed only through `graph.py`, which locks, checks for duplicates, validates, and saves crash-safely. Names and external ids are unique within a type, not across types.
- **Recap page:** a fixed page copied into the workspace, with all rendering in `recap-lib.js` so it can be tested in Node.
