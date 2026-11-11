"""Steps for the Semantic Scholar features. The API is replaced by scripted answers."""

import contextlib
import io
import json
import shlex
import tempfile
import urllib.error
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


@when("I run scholar {command}")
def run_scholar(context, command):
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = s2.main(shlex.split(command))
    out.seek(0)
    err.seek(0)
    context.result = SimpleNamespace(code=code, out=out.read(), err=err.read())


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
