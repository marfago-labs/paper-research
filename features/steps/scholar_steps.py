"""Steps for the Semantic Scholar features. The API is replaced by scripted answers."""

import contextlib
import io
import json
import shlex
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

import s2


def start(context, patcher):
    patcher.start()
    context.patches.append(patcher)


@given("Semantic Scholar answers can be scripted")
def scholar_scripted(context):
    context.s2_answers = []
    context.s2_calls = []
    context.s2_sleeps = []
    cache = tempfile.TemporaryDirectory()
    context.s2_cache = cache
    context.patches.append(SimpleNamespace(stop=cache.cleanup))

    def fake_open(request, timeout=None):
        context.s2_calls.append(request)
        answer = context.s2_answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode("utf-8"))

    start(context, mock.patch.object(s2, "CACHE_DIR", Path(cache.name)))
    start(context, mock.patch.object(s2.OPENER, "open", fake_open))
    start(context, mock.patch.object(s2, "pace"))
    start(context, mock.patch.object(s2.time, "sleep", lambda seconds: context.s2_sleeps.append(seconds)))


@given("Semantic Scholar answers with HTTP {code:d}")
def scholar_http_error(context, code):
    context.s2_answers.append(
        urllib.error.HTTPError("https://api.semanticscholar.org/x", code, "error", {}, io.BytesIO(b"slow down"))
    )


@given('Semantic Scholar then answers with the paper "{title}"')
def scholar_paper(context, title):
    context.s2_answers.append({"paperId": "abc", "title": title})


@given("Semantic Scholar then answers with an unknown paper")
def scholar_unknown(context):
    context.s2_answers.append([None])


@given("Semantic Scholar then answers with something unexpected")
def scholar_odd(context):
    context.s2_answers.append({"error": "surprise"})


@given('a file "{name}" of {count:d} arXiv ids')
def scholar_ids_file(context, name, count):
    ids = "".join(f"2401.{n:05d}\n" for n in range(1, count + 1))
    (context.workspace / name).write_text(ids, encoding="utf-8")


@given("Semantic Scholar then answers with {count:d} unknown papers")
def scholar_unknown_many(context, count):
    context.s2_answers.append([None] * count)


def run_s2(context, argv):
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = s2.main(argv)
    out.seek(0)
    err.seek(0)
    context.result = SimpleNamespace(code=code, out=out.read(), err=err.read())


@when("I run scholar {command}")
def run_scholar(context, command):
    run_s2(context, shlex.split(command))


@when('I look up the papers listed in "{name}"')
def run_scholar_batch_file(context, name):
    run_s2(context, ["batch", "--ids-file", str(context.workspace / name)])


@when('I look up the papers listed in "{name}" with their references')
def run_scholar_batch_references(context, name):
    run_s2(context, ["batch", "--ids-file", str(context.workspace / name), "--with-references"])


@then("every request asked for the reference lists")
def scholar_asked_references(context):
    asked = [urllib.parse.unquote(request.full_url) for request in context.s2_calls]
    assert asked and all("references.paperId" in url for url in asked), asked


@then("{count:d} results are printed")
def scholar_result_count(context, count):
    assert len(json.loads(context.result.out)) == count, context.result.out[:200]


@then("Semantic Scholar was asked {count:d} times")
def scholar_calls(context, count):
    assert len(context.s2_calls) == count, len(context.s2_calls)


@then("the script waited before asking again")
def scholar_waited(context):
    assert context.s2_sleeps and all(delay > 0 for delay in context.s2_sleeps), context.s2_sleeps


@then('the printed paper is titled "{title}"')
def scholar_title(context, title):
    assert json.loads(context.result.out)["title"] == title, context.result.out


@then('the first printed result says "{text}"')
def scholar_first(context, text):
    assert text in json.dumps(json.loads(context.result.out)[0]), context.result.out


@then("every request went to the Semantic Scholar API host")
def scholar_host(context):
    assert context.s2_calls and all(r.full_url.startswith("https://api.semanticscholar.org/") for r in context.s2_calls)


@then("no request carried an API key")
def scholar_no_key(context):
    assert all(r.get_header("X-api-key") is None for r in context.s2_calls)
