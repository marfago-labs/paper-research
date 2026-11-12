#!/usr/bin/env python3
"""Read-only command-line client for the Semantic Scholar API.

Standard library only. Prints JSON to stdout and errors to stderr.
Exit codes: 0 success, 1 API or network failure, 2 invalid input.
Set SEMANTIC_SCHOLAR_API_KEY to use a personal API key (optional).
"""

import argparse
import contextlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_ROOT = "https://api.semanticscholar.org"
GRAPH = "/graph/v1"
RECOMMENDATIONS = "/recommendations/v1"

PAPER_FIELDS = (
    "paperId,externalIds,title,abstract,year,venue,publicationDate,"
    "citationCount,influentialCitationCount,openAccessPdf,authors.name,url"
)
DETAIL_FIELDS = PAPER_FIELDS + ",tldr"
LINK_FIELDS = "isInfluential,paperId,externalIds,title,year,citationCount,authors"
# Only the ids of the papers a paper cites: enough to link it to the papers already in the graph.
REFERENCE_FIELDS = "references.paperId,references.externalIds"

AUTHOR_FIELDS = "name,hIndex,citationCount,paperCount"

MAX_BATCH = 500  # the most IDs the batch endpoint takes in one request
# With reference lists a response is far larger, and the endpoint answers at most 10 MB, so ask for fewer papers.
REFERENCE_BATCH = 100
MIN_INTERVAL = 1.1  # seconds between requests; a new API key allows 1 per second
MAX_ATTEMPTS = 5
TIMEOUT = 30
DEADLINE = 90  # seconds for one command's request, retries included, to stay inside tool time limits
MAX_BYTES = 20_000_000
RETRYABLE = {429, 500, 502, 503, 504}
CACHE_DIR = None  # the workspace's .cache, found from the current folder when None
STATE_NAME = "s2-last-request"
LOCK_WAIT = 60


class ApiError(Exception):
    pass


class PartialBatch(ApiError):
    """A later request of a long batch failed. The papers fetched before it are kept, so they aren't lost."""

    def __init__(self, message, results):
        super().__init__(message)
        self.results = results


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so requests and the API key never leave API_ROOT."""

    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


ARXIV_ID_FORMS = (
    re.compile(r"(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I),
    re.compile(
        r"https?://(?:www\.)?(?:arxiv\.org/(?:abs|pdf|html)|huggingface\.co/papers)/"
        r"(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?(?:[?#].*)?",
        re.I,
    ),
    re.compile(
        r"(?:arxiv:|https?://(?:www\.)?arxiv\.org/(?:abs|pdf|html)/)?([a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?(?:\.pdf)?/?",
        re.I,
    ),
)


def arxiv_id(value):
    """The arXiv ID in an arXiv ID or link, or a Hugging Face paper link. None if it isn't one."""
    for form in ARXIV_ID_FORMS:
        match = form.fullmatch(value)
        if match:
            return match.group(1)
    return None


def with_prefix(value):
    """A DOI, DOI link, or other link, with the prefix Semantic Scholar expects. Anything else as it is."""
    match = re.fullmatch(r"https?://(?:dx\.)?doi\.org/(.+)", value, re.I)
    if match:
        return f"DOI:{urllib.parse.unquote(match.group(1))}"
    if re.fullmatch(r"10\.\d{4,9}/\S+", value):
        return f"DOI:{value}"
    if re.match(r"https?://", value, re.I):
        return f"URL:{value}"
    return value


def normalize_id(raw):
    """Turn an arXiv/HF/DOI link or a bare arXiv ID into a Semantic Scholar ID."""
    value = raw.strip()
    arxiv = arxiv_id(value)
    if arxiv:
        return f"ARXIV:{arxiv}"
    value = with_prefix(value)
    if not value or re.search(r"[\s\x00-\x1f]", value) or ".." in value.split("/"):
        raise ValueError(f"invalid paper ID: {raw!r}")
    return value


def paper_path(paper_id, suffix=""):
    return f"{GRAPH}/paper/{urllib.parse.quote(paper_id, safe=':/')}{suffix}"


def retry_delay(retry_after, attempt):
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), 60)
    return min(2 ** (attempt + 1), 30)


if sys.platform == "win32":
    import msvcrt

    def try_lock(handle):
        """Try to take an exclusive operating-system lock on the file. True if it was taken."""
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def unlock(handle):
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def try_lock(handle):
        """Try to take an exclusive operating-system lock on the file. True if it was taken."""
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def unlock(handle):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(path, wait, busy_message):
    """Hold a lock on a file for the block. The system drops it if the process dies, so it can't go stale."""
    deadline = time.monotonic() + wait
    with open(path, "a+b") as handle:
        while not try_lock(handle):
            if time.monotonic() > deadline:
                raise ApiError(busy_message)
            time.sleep(0.1)
        try:
            yield
        finally:
            unlock(handle)


def find_workspace():
    """The workspace root: the current folder or the nearest parent that has a research/ folder."""
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        if (folder / "research").is_dir():
            return folder
    raise ValueError("no research/ folder here or in a parent folder; run the init skill in your workspace first")


def cache_dir():
    return CACHE_DIR if CACHE_DIR is not None else find_workspace() / ".cache"


def pace(wait=LOCK_WAIT):
    """Space requests across every process using this script, not just this one."""
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    state = folder / STATE_NAME
    with file_lock(folder / f"{STATE_NAME}.lock", wait, "other requests are still queued; try again shortly"):
        try:
            last = float(state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = 0.0
        delay = MIN_INTERVAL - (time.time() - last)
        if delay > 0:
            time.sleep(min(delay, MIN_INTERVAL))
        state.write_text(repr(time.time()), encoding="utf-8")


def build_request(method, path, params, body):
    url = API_ROOT + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json", "User-Agent": "paper-research-s2/1.0"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    return urllib.request.Request(url, data=data, headers=headers, method=method)


def read_json(req, path, started):
    """One request, with the time left before the deadline and the size cap, decoded from JSON."""
    remaining = DEADLINE - (time.monotonic() - started)
    with OPENER.open(req, timeout=max(1, min(TIMEOUT, remaining))) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ApiError(f"response from {path} is larger than {MAX_BYTES} bytes")
    try:
        return json.loads(body)
    except ValueError:
        raise ApiError(f"response from {path} was not valid JSON") from None


def delay_before_retry(err, path, attempt):
    """How long to wait before retrying after err. Raises if it shouldn't be retried."""
    last_attempt = attempt == MAX_ATTEMPTS - 1
    if not isinstance(err, urllib.error.HTTPError):
        if last_attempt:
            raise ApiError(f"network failure calling {path}: {err}") from None
        return retry_delay(None, attempt)
    detail = err.read(300).decode("utf-8", "replace")
    retry_after = err.headers.get("Retry-After") if err.headers else None
    err.close()
    if err.code not in RETRYABLE or last_attempt:
        raise ApiError(f"HTTP {err.code} from {path}: {detail}") from None
    return retry_delay(retry_after, attempt)


def request(method, path, params=None, body=None):
    req = build_request(method, path, params, body)
    started = time.monotonic()
    attempt = -1
    while True:
        attempt += 1
        waited = time.monotonic() - started
        if waited >= DEADLINE:
            raise ApiError(f"gave up on {path} after about {DEADLINE} seconds")
        pace(min(LOCK_WAIT, DEADLINE - waited))
        try:
            return read_json(req, path, started)
        except (urllib.error.URLError, TimeoutError) as err:
            delay = delay_before_retry(err, path, attempt)
        if time.monotonic() - started + delay > DEADLINE:
            raise ApiError(f"gave up on {path} after about {DEADLINE} seconds of retries")
        time.sleep(delay)


def check_range(name, value, low, high):
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")


def cmd_search(args):
    check_range("--limit", args.limit, 1, 100)
    check_range("--offset", args.offset, 0, 9999)
    params = {
        "query": args.query,
        "fields": PAPER_FIELDS,
        "limit": args.limit,
        "offset": args.offset,
    }
    if args.year:
        params["year"] = args.year
    if args.min_citations is not None:
        params["minCitationCount"] = args.min_citations
    return request("GET", f"{GRAPH}/paper/search", params)


def linked_papers(paper_id, edge, key, limit):
    params = {"fields": LINK_FIELDS, "limit": limit}
    response = request("GET", paper_path(paper_id, f"/{edge}"), params)
    papers = []
    for item in response.get("data") or []:
        paper = item.get(key) or {}
        papers.append({**paper, "isInfluential": item.get("isInfluential")})
    return papers


def cmd_paper(args):
    check_range("--limit", args.limit, 1, 1000)
    paper_id = normalize_id(args.id)
    result = request("GET", paper_path(paper_id), {"fields": DETAIL_FIELDS})
    if args.citations:
        result["citations"] = linked_papers(paper_id, "citations", "citingPaper", args.limit)
    if args.references:
        result["references"] = linked_papers(paper_id, "references", "citedPaper", args.limit)
    return result


def read_ids(file):
    """The ids in a file, separated by whitespace, so a long list never has to pass through the command line."""
    try:
        return Path(file).read_text(encoding="utf-8").split()
    except OSError as err:
        raise ValueError(f"can't read {file}: {err}") from None


def batch_request(ids, with_references=False):
    """One request for a batch of ids, as a record for each, with their reference lists if asked."""
    fields = f"{PAPER_FIELDS},{REFERENCE_FIELDS}" if with_references else PAPER_FIELDS
    papers = request("POST", f"{GRAPH}/paper/batch", {"fields": fields}, {"ids": ids})
    if not isinstance(papers, list):
        raise ApiError("unexpected response from the batch endpoint")
    return [
        {"requestedId": requested, **paper} if paper else {"requestedId": requested, "error": "not found"}
        for requested, paper in zip(ids, papers)
    ]


def cmd_batch(args):
    if len(args.ids) > MAX_BATCH:
        raise ValueError(f"batch accepts at most {MAX_BATCH} IDs on the command line; use --ids-file for more")
    ids = [normalize_id(value) for value in [*args.ids, *(read_ids(args.ids_file) if args.ids_file else [])]]
    if not ids:
        raise ValueError("give at least one ID, or a file of them with --ids-file")
    size = REFERENCE_BATCH if args.with_references else MAX_BATCH
    papers: list[dict] = []
    for start in range(0, len(ids), size):
        try:
            papers += batch_request(ids[start : start + size], args.with_references)
        except ApiError as err:
            if not papers:
                raise
            raise PartialBatch(f"{err} ({len(papers)} of {len(ids)} papers were fetched first)", papers) from None
    return papers


def cmd_recommend(args):
    body = {
        "positivePaperIds": [normalize_id(value) for value in args.like],
        "negativePaperIds": [normalize_id(value) for value in args.dislike],
    }
    check_range("--limit", args.limit, 1, 500)
    params = {"fields": PAPER_FIELDS, "limit": args.limit}
    return request("POST", f"{RECOMMENDATIONS}/papers", params, body)


def cmd_authors(args):
    for author_id in args.ids:
        if not re.fullmatch(r"[0-9]+", author_id):
            raise ValueError(f"invalid author ID: {author_id!r}")
    authors = request("POST", f"{GRAPH}/author/batch", {"fields": AUTHOR_FIELDS}, {"ids": args.ids})
    if not isinstance(authors, list):
        raise ApiError("unexpected response from the author batch endpoint")
    return [
        author if author else {"authorId": requested, "error": "not found"}
        for requested, author in zip(args.ids, authors)
    ]


def build_parser():
    parser = argparse.ArgumentParser(description="Read-only Semantic Scholar client.")
    commands = parser.add_subparsers(dest="command", required=True)

    search = commands.add_parser("search", help="find papers by keyword")
    search.add_argument("query")
    search.add_argument("--year", help="e.g. 2025, 2024-2025 or 2025-")
    search.add_argument("--min-citations", type=int)
    search.add_argument("--limit", type=int, default=10, help="default 10, API maximum 100")
    search.add_argument("--offset", type=int, default=0)
    search.set_defaults(func=cmd_search)

    paper = commands.add_parser("paper", help="details for one paper")
    paper.add_argument("id", help="arXiv ID or link, DOI, or Semantic Scholar ID")
    paper.add_argument("--citations", action="store_true", help="include citing papers")
    paper.add_argument("--references", action="store_true", help="include cited papers")
    paper.add_argument("--limit", type=int, default=20, help="maximum per citation list")
    paper.set_defaults(func=cmd_paper)

    batch = commands.add_parser("batch", help="details for many papers, 500 to a request")
    batch.add_argument("ids", nargs="*")
    batch.add_argument("--ids-file", help="file of IDs separated by whitespace, for more than fit on the command line")
    batch.add_argument(
        "--with-references",
        action="store_true",
        help=f"also fetch each paper's reference list, {REFERENCE_BATCH} papers to a request",
    )
    batch.set_defaults(func=cmd_batch)

    recommend = commands.add_parser("recommend", help="recommendations from example papers")
    recommend.add_argument("--like", nargs="+", required=True)
    recommend.add_argument("--dislike", nargs="*", default=[])
    recommend.add_argument("--limit", type=int, default=20, help="default 20, API maximum 500")
    recommend.set_defaults(func=cmd_recommend)

    authors = commands.add_parser("authors", help="h-index and citation totals for authors")
    authors.add_argument("ids", nargs="+", help="Semantic Scholar author IDs")
    authors.set_defaults(func=cmd_authors)
    return parser


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except ApiError as err:
        print(f"error: {err}", file=sys.stderr)
        if isinstance(err, PartialBatch):
            print(json.dumps(err.results, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
