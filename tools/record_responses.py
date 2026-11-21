#!/usr/bin/env python3
"""Record real replies from arXiv and Semantic Scholar into tools/fixtures/, for tools/test_recorded_responses.py.

The scripts' own tests use replies written by hand, which show what the code expects, not what the services send.
This records what they send, through each script's own main(), so the requests are the ones the scripts make.
It uses the network, so CI never runs it. Run it by hand before a release, then run the tests: a failure means a
service changed the shape of its replies. Review the diff of tools/fixtures/ before committing it.

Usage: python tools/record_responses.py
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools" / "fixtures"
for folder in ("arxiv", "scholar"):
    sys.path.insert(0, str(ROOT / "skills" / folder / "scripts"))

import arxiv  # noqa: E402
import s2  # noqa: E402

# Reflexion's title breaks over two lines in its HTML, and it cites HumanEval, so the two make a citation link.
PAPER = "2303.11366"
CITED = "2107.03374"
UNKNOWN = "ARXIV:2611.99999"  # no such paper, so Semantic Scholar answers null for it
REFERENCES_KEPT = 3


def trimmed_page(page):
    """The page up to the end of the paper's second section: real markup, small enough to keep in the repository."""
    end = page.index('<section id="S3"')
    # The authors' addresses are public in the paper, but the repository has no use for them.
    page = re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "author@example.org", page[:end])
    return page + "</article></div></body></html>\n"


def trimmed_batch(records):
    """The batch reply with a few references per paper, keeping the one to the cited paper."""
    for record in records:
        if record and record.get("references"):
            refs = record["references"]
            cited = [r for r in refs if (r.get("externalIds") or {}).get("ArXiv") == CITED]
            record["references"] = (cited + [r for r in refs if r not in cited])[:REFERENCES_KEPT]
    return records


def quietly(main, argv):
    """Run a script's main with its output thrown away, and fail if it fails."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(argv)
    if code:
        out.seek(0)
        raise SystemExit(f"{main.__module__} {' '.join(argv)} failed:\n{out.read()}")


def record_arxiv(folder):
    replies = {}
    real_get = arxiv.get

    def recording_get(url):
        replies[url] = real_get(url)
        return replies[url]

    with mock.patch.object(arxiv, "get", recording_get):
        quietly(arxiv.main, ["paper", PAPER, CITED])
        quietly(arxiv.main, ["fetch", PAPER, "--dir", str(folder), "--force"])
    (feed,) = [data for url, data in replies.items() if url.startswith(arxiv.API)]
    (page,) = [data for url, data in replies.items() if "/html/" in url]
    (FIXTURES / "arxiv-feed.xml").write_bytes(feed)
    (FIXTURES / f"arxiv-{PAPER}.html").write_text(trimmed_page(page.decode("utf-8")), encoding="utf-8")


def record_batch(folder):
    replies = []
    real_open = s2.OPENER.open

    def recording_open(request, timeout=None):
        with real_open(request, timeout=timeout) as response:
            replies.append(response.read())
        return io.BytesIO(replies[-1])

    ids = folder / "ids.txt"
    ids.write_text(f"ARXIV:{PAPER}\nARXIV:{CITED}\n{UNKNOWN}\n", encoding="utf-8")
    with mock.patch.object(s2.OPENER, "open", recording_open):
        quietly(s2.main, ["batch", "--ids-file", str(ids), "--with-references"])
    batch = trimmed_batch(json.loads(replies[-1]))
    (FIXTURES / "s2-batch.json").write_text(json.dumps(batch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    FIXTURES.mkdir(exist_ok=True)
    start = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        (workspace / "research").mkdir()
        os.chdir(workspace)  # the scripts pace their requests with a file in the workspace
        try:
            record_arxiv(workspace)
            record_batch(workspace)
        finally:
            os.chdir(start)
    written = ("arxiv-feed.xml", f"arxiv-{PAPER}.html", "s2-batch.json")
    print(f"recorded {', '.join(written)} in {FIXTURES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
