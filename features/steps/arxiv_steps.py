"""Steps for the arXiv features. The network is replaced by an in-memory arXiv."""

import contextlib
import io
import json
import os
import shlex
import urllib.parse
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

import arxiv

FEED_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
    'xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
)


def entry(ident, title, date):
    return (
        f"<entry><id>http://arxiv.org/abs/{ident}v1</id><title>{title}</title>"
        f"<published>{date}T10:00:00Z</published><updated>{date}T10:00:00Z</updated>"
        "<summary>An abstract.</summary><author><name>Ann Author</name></author>"
        '<arxiv:primary_category term="cs.AI"/><category term="cs.AI"/></entry>'
    )


def article(sections):
    filler = "word " * 250
    body = "".join(f"<section><h2>{name}</h2><p>{filler}</p></section>" for name in sections)
    return f'<html><body><article class="ltx_document"><h1>A paper</h1>{body}</article></body></html>'


def stored_file(files, url, ident):
    """The fake arXiv's copy of a paper's HTML or PDF, or a 404 like the real one."""
    if ident not in files:
        raise arxiv.NotFound(url)
    return files[ident]


def install_fake_arxiv(context):
    context.papers = []
    context.html = {}
    context.pdfs = {}
    context.requested = []

    def fake_get(url):
        context.requested.append(urllib.parse.unquote_plus(url))
        for kind, files in (("html", {k: v.encode() for k, v in context.html.items()}), ("pdf", context.pdfs)):
            if f"/{kind}/" in url:
                return stored_file(files, url, url.rsplit(f"/{kind}/", 1)[1])
        entries = "".join(entry(*paper) for paper in context.papers)
        total = f"<opensearch:totalResults>{len(context.papers)}</opensearch:totalResults>"
        return f"{FEED_HEAD}{total}{entries}</feed>".encode()

    patcher = mock.patch.object(arxiv, "get", fake_get)
    patcher.start()
    context.patches.append(patcher)


@given("arXiv is reachable")
def arxiv_reachable(context):
    install_fake_arxiv(context)


@given('arXiv knows the paper {ident} titled "{title}" submitted on {date}')
def arxiv_knows(context, ident, title, date):
    context.papers.append((ident, title, date))


@given('arXiv has an HTML version of {ident} with the sections "{sections}"')
def arxiv_html(context, ident, sections):
    context.html[ident] = article([name.strip() for name in sections.split(",")])


@given('arXiv has an HTML version of {ident} that hides the text "{text}"')
def arxiv_html_hidden(context, ident, text):
    page = article(["1 Introduction"])
    context.html[ident] = page.replace("</article>", f'<p style="display:none">{text}</p></article>')


@then("the output warns that the paper contains hidden text")
def hidden_warning(context):
    result = printed(context)
    assert result["hiddenTextRemoved"] == 1, result
    assert "prompt-injection" in result["warning"], result["warning"]


@given("arXiv has no HTML version of {ident}")
def arxiv_no_html(context, ident):
    context.html.pop(ident, None)


@given("arXiv serves a PDF for {ident}")
def arxiv_pdf(context, ident):
    context.pdfs[ident] = b"%PDF-1.5 a pretend paper"


@given("arXiv serves something that is not a PDF for {ident}")
def arxiv_fake_pdf(context, ident):
    context.pdfs[ident] = b"<html>sorry</html>"


@when("I run arxiv {command}")
def run_arxiv(context, command):
    argv = [part.replace("WORKSPACE", str(context.workspace)) for part in shlex.split(command)]
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = arxiv.main(argv)
    out.seek(0)
    err.seek(0)
    context.result = SimpleNamespace(code=code, out=out.read(), err=err.read())


def printed(context):
    return json.loads(context.result.out)


@then('the request sent to arXiv contained "{text}"')
def request_contained(context, text):
    assert any(text in url for url in context.requested), context.requested


@then("the search found {count:d} papers")
def search_found(context, count):
    assert len(printed(context)["papers"]) == count, printed(context)


@then('paper {number:d} of the results is "{title}" published {date}')
def result_title(context, number, title, date):
    paper = printed(context)["papers"][number - 1]
    assert (paper["title"], paper["published"]) == (title, date), paper


@then('the saved text lists the sections "{sections}"')
def saved_sections(context, sections):
    headings = [s["heading"] for s in printed(context)["sections"]]
    for name in (n.strip() for n in sections.split(",")):
        assert name in headings, headings


@then("the output warns that paper text is untrusted")
def untrusted_warning(context):
    assert "untrusted" in printed(context)["warning"]


@then('the result for {ident} says "{text}"')
def result_says(context, ident, text):
    found = [p for p in printed(context) if ident in (p.get("id"), p.get("requestedId"))]
    assert found and text in json.dumps(found[0]), printed(context)


@given('I am in the folder "{folder}" of a workspace')
def in_subfolder(context, folder):
    (context.workspace / "research").mkdir(exist_ok=True)
    (context.workspace / folder).mkdir(parents=True)
    os.chdir(context.workspace / folder)


@given("I am in a folder with no workspace")
def in_no_workspace(context):
    os.chdir(context.workspace)
