#!/usr/bin/env python3
"""Write the data for the recap page from the research files. Standard library only.

Reads papers.md, the saved full texts, pins.md, insights.md, user-facts.md, and the graph files, and writes
recap-data.js into the research folder. The page itself, recap.html next to this
script, is fixed and never generated. Missing files are treated as empty.
Exit codes: 0 success, 2 usage error.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
# pragma: no mutate below: graph.py is the only module of its name on the path, so its position changes nothing.
sys.path.insert(0, str(CODE_DIR.parents[1] / "graph" / "scripts"))  # pragma: no mutate
import graph  # noqa: E402

PAGE_DIR = CODE_DIR.parent / "page"
PAGE_FILES = ("recap.html", "recap-lib.js", "cytoscape-3.30.4.min.js", "cytoscape-LICENSE.txt")
RESEARCH_DIR = "research"
OUTPUT_DIR = "recap"
DATA_FILE = "recap-data.js"
PAPER_ID = re.compile(r"ARXIV:\d{4}\.\d{4,5}|DOI:10\.\d{4,9}/[^\s`,;)<]*[^\s`,;)<.]")


def read_text(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def split_row(line):
    """Split a Markdown table row, keeping escaped pipes inside cells."""
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [cell.strip().replace("\\|", "|") for cell in cells]


def paper_url(paper_id):
    if paper_id.startswith("ARXIV:"):
        return f"https://arxiv.org/abs/{paper_id[6:]}"
    if paper_id.startswith("DOI:"):
        return f"https://doi.org/{paper_id[4:]}"
    return paper_id if paper_id.startswith(("http://", "https://")) else ""


def parse_papers(text):
    papers = []
    header = None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = split_row(line)
        if header is None:
            header = [cell.lower() for cell in cells]
        elif set("".join(cells)) - set("-: "):  # anything but dashes, colons, and spaces: not a separator row
            paper = dict(zip(header, cells))
            paper["id"] = paper.get("id", "").strip("<>")
            paper["url"] = paper_url(paper["id"])
            papers.append(paper)
    return papers


def parse_pins(text):
    pattern = re.compile(r"^- \*\*\[(?P<type>[^\]]+)\] (?P<title>.+?):\*\* (?P<body>.*)$")
    pins = []
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            pin = match.groupdict()
            added = re.search(r"Added: (\d{4}-\d{2}-\d{2})", pin["body"])
            pin["added"] = added.group(1) if added else ""
            pins.append(pin)
    return pins


def parse_insights(text):
    insights = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, rest = block.partition("\n")
        fields = {
            key.lower().replace("'", "").replace(" ", "_"): value
            for key, value in re.findall(r"^- \*\*([^:*]+):\*\* (.*)$", rest, flags=re.M)
        }
        insight = {"title": title.strip(), **fields}
        insight["id"] = insight.get("id", "").strip("`")
        insight["kind"] = insight.get("kind", "").strip("`")
        insight["papers"] = sorted(set(PAPER_ID.findall(insight.get("sources", ""))))
        insights.append(insight)
    return insights


def parse_questions(text):
    questions = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split("|", 3)]
        if len(parts) > 3 and parts[1] == "question":  # split at most 3 times, so > 3 means exactly 4 parts
            questions.append({"added": parts[0], "text": parts[3]})
    return questions


def load_graph(directory):
    """Return the graph for the page, or the reason it can't be shown."""
    if not (directory / "entities.jsonl").exists():
        return {"entities": [], "relations": [], "error": ""}
    try:
        with graph.locked(directory):
            entities, relations = graph.checked_load(directory)
    except graph.GraphError as err:
        return {"entities": [], "relations": [], "error": str(err)}
    return {"entities": entities, "relations": relations, "error": ""}


def graph_status(papers, graph_data):
    """Mark each listed paper as extracted, unextracted (only author or citation links), or missing.

    A paper in the graph also gets its saved standing, and how many papers in the graph cite it.
    """
    if graph_data["error"]:
        return
    entities, relations = graph_data["entities"], graph_data["relations"]
    index = paper_index(entities)
    by_id = {e["id"]: e for e in entities}
    waiting = {e["id"] for e in graph.islands(entities, relations)}
    cited_by = Counter(r["to"] for r in relations if r["rel"] == "cites")
    for paper in papers:
        found = index.get(paper_key(paper["id"]))
        if not found:
            paper["graph"] = "missing"
        else:
            paper["collection"]["cited_by"] = cited_by[found]
            paper.update(graph_facts(by_id[found], found in waiting))


def graph_facts(entity, waiting):
    """What the graph says about a paper in it: whether anything was extracted, and its saved standing."""
    facts = {"graph": "unextracted" if waiting else "extracted"}
    if "standing" in entity:
        facts["standing"] = entity["standing"]
    return facts


def collection_counts(papers, pins, insights):
    """How often each paper comes up in the user's own notes: insights and pins that cite it."""
    in_pins = Counter(paper_id for pin in pins for paper_id in set(PAPER_ID.findall(pin["body"])))
    in_insights = Counter(paper_id for insight in insights for paper_id in insight["papers"])
    for paper in papers:
        paper["collection"] = {"cited_by": 0, "insights": in_insights[paper["id"]], "pins": in_pins[paper["id"]]}


def paper_index(entities):
    """Graph paper ids by external id, and by url."""
    papers = [e for e in entities if e["type"] == "paper"]
    index = {key: e["id"] for e in papers for key in graph.external_keys(e)}
    index.update((("url", e["url"]), e["id"]) for e in papers if e.get("url"))
    return index


def paper_key(paper_id):
    """The key to look up a papers.md ID in paper_index."""
    kind, _, value = paper_id.partition(":")
    return (kind.lower(), value.casefold()) if kind in ("ARXIV", "DOI") else ("url", paper_id)


ARXIV_NUMBER = re.compile(
    r"(?:arxiv:|https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?$", re.IGNORECASE
)


def arxiv_number(paper_id):
    """The arXiv number in a papers.md id, whatever its form (ARXIV:, arXiv:, a vN suffix, an abs or pdf link)."""
    match = ARXIV_NUMBER.match(paper_id.strip())
    return match.group(1) if match else None


def unlisted_fulltext(research, papers):
    """Papers with saved full text that papers.md doesn't list, so the page can flag them like any other gap.

    Only arXiv numbers like 2404.16130 are matched, so a saved old-style id such as hep-th/9901001 is not flagged.
    """
    listed = {arxiv_number(paper["id"]) for paper in papers}
    found = []
    for path in sorted((research / "fulltext").glob("*.md")):
        if re.fullmatch(r"\d{4}\.\d{4,5}", path.stem) and path.stem not in listed:
            paper_id = f"ARXIV:{path.stem}"
            title = f"{paper_id} (full text saved, not in papers.md)"
            found.append({"id": paper_id, "url": paper_url(paper_id), "title": title})
    return found


def build_data(research, now=None):
    papers = parse_papers(read_text(research / "papers.md"))
    papers += unlisted_fulltext(research, papers)
    pins = parse_pins(read_text(research / "pins.md"))
    insights = parse_insights(read_text(research / "insights.md"))
    collection_counts(papers, pins, insights)
    graph_data = load_graph(research / "graph")
    graph_status(papers, graph_data)
    return {
        "generated": now or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "papers": papers,
        "pins": pins,
        "insights": insights,
        "questions": parse_questions(read_text(research / "user-facts.md")),
        "graph": graph_data,
    }


def to_script(data):
    """Encode the data as a script the page loads with a script tag."""
    text = json.dumps(data, ensure_ascii=False, indent=1)
    return f"// Generated by the recap skill. Don't edit.\nwindow.RECAP_DATA = {text};\n"


def build_parser():
    parser = argparse.ArgumentParser(description="Write the data for the recap page.")
    parser.add_argument("--workspace", type=Path, default=Path("."), help="workspace root (default: here)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    research = args.workspace / RESEARCH_DIR
    if not research.is_dir():
        print(f"error: research folder not found: {research}", file=sys.stderr)
        return 2
    data = build_data(research)
    folder = research / OUTPUT_DIR
    folder.mkdir(exist_ok=True)
    for name in PAGE_FILES:
        (folder / name).write_bytes((PAGE_DIR / name).read_bytes())
    (folder / DATA_FILE).write_text(to_script(data), encoding="utf-8")
    print(f"wrote {folder / DATA_FILE}")
    if data["graph"]["error"]:
        print(f"warning: graph not shown: {data['graph']['error']}", file=sys.stderr)
    print(f"open {(folder / 'recap.html').resolve()}")
    return 0


if __name__ == "__main__":  # pragma: no mutate (`is` and `<=` agree for the names a module can have)
    sys.exit(main())
