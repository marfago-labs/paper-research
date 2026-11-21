"""Steps shared by every feature: command results and files."""

from behave import then


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


@then('the error mentions "{text}"')
def error_mentions(context, text):
    assert text in context.result.err, f"{text!r} not in error:\n{context.result.err}"


@then('the file "{name}" contains "{text}"')
def file_contains(context, name, text):
    content = (context.workspace / name).read_text(encoding="utf-8")
    assert text in content, f"{text!r} not in {name}:\n{content}"
