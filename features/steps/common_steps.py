"""Steps shared by every feature: command results and files."""

import json

from behave import then, when


@then("the command succeeds")
def command_succeeds(context):
    assert context.result.code == 0, f"exit {context.result.code}\n{context.result.out}\n{context.result.err}"


@then("the command fails")
def command_fails(context):
    assert context.result.code not in (0, None), f"expected a failure\n{context.result.out}"


@then("the command exits with code {code:d}")
def command_exit_code(context, code):
    assert context.result.code == code, f"exit {context.result.code}, wanted {code}\n{context.result.err}"


@then('the output mentions "{text}"')
def output_mentions(context, text):
    text = text.replace('\\"', '"')
    assert text in context.result.out, f"{text!r} not in output:\n{context.result.out}"


@then('the output does not mention "{text}"')
def output_does_not_mention(context, text):
    assert text not in context.result.out, f"{text!r} found in output:\n{context.result.out}"


@then('the error mentions "{text}"')
def error_mentions(context, text):
    assert text in context.result.err, f"{text!r} not in error:\n{context.result.err}"


@then("nothing is written to the error output")
def no_error_output(context):
    assert context.result.err.strip() == "", context.result.err


@then('the file "{name}" exists')
def file_exists(context, name):
    assert (context.workspace / name).exists(), f"{name} is missing"


@then('the file "{name}" does not exist')
def file_missing(context, name):
    assert not (context.workspace / name).exists(), f"{name} exists"


@then('the file "{name}" contains "{text}"')
def file_contains(context, name, text):
    content = (context.workspace / name).read_text(encoding="utf-8")
    assert text in content, f"{text!r} not in {name}:\n{content}"


@then('the file "{name}" does not contain "{text}"')
def file_lacks(context, name, text):
    content = (context.workspace / name).read_text(encoding="utf-8")
    assert text not in content, f"{text!r} found in {name}"


@then('the JSON file "{name}" has "{path}" equal to {value}')
def json_value(context, name, path, value):
    data = json.loads((context.workspace / name).read_text(encoding="utf-8"))
    for key in path.split("."):
        data = data[key]
    assert data == json.loads(value), f"{path} is {data!r}"


@when('I write "{text}" to the file "{name}"')
def write_file(context, text, name):
    target = context.workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace("\\n", "\n"), encoding="utf-8")


@then('line {number:d} of "{name}" is "{text}"')
def line_is(context, number, name, text):
    text = text.replace('\\"', '"')
    lines = (context.workspace / name).read_text(encoding="utf-8").splitlines()
    assert lines[number - 1] == text, repr(lines[number - 1])
