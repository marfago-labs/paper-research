#!/usr/bin/env python3
"""Record what the plugin does, for debugging. Standard library only.

It is off by default. `debuglog.py on` creates research/.debug, and `debuglog.py off` removes it. While the file
exists, the plugin's scripts and hooks append one JSON line per event to research/.debug.log, and, if
PAPER_RESEARCH_OTLP_ENDPOINT (else OTEL_EXPORTER_OTLP_ENDPOINT) points at this machine, send the same event there as
an OpenTelemetry log record. Claude Code removes every OTEL_ variable from the commands and hooks it runs, so in a
session only the plugin's own variable arrives; the OTEL_ one serves scripts run by hand in a terminal.
The log holds at most 2 MB: when it is full it moves to research/.debug.log.1, which replaces the older one.
Two scripts that write at the same moment can lose an event; that is accepted for a debug log.
An event holds names, hosts, statuses, counts, and timings, never notes or search text. A failed command's event
also holds its reason: the first line of its error message, with quoted values, entity ids, paths, the words after
"unrecognized arguments" or "ambiguous option", and query strings left out.

Commands: on, off, status, show [--lines N], clear.
Exit codes: 0 success, 2 usage error.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

RESEARCH = "research"
SWITCH = ".debug"
LOG = ".debug.log"
OLD_LOG = ".debug.log.1"
MAX_BYTES = 2_000_000
MAX_TEXT = 200
SERVICE = "paper-research"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
ENDPOINTS = ("PAPER_RESEARCH_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT")  # the first one set is used
SEND_TIMEOUT = 0.5  # seconds; the collector is on this machine, so it answers at once or not at all
NOTES: dict = {}  # fields that a command adds to its own `command` event
KEPT = 2000  # characters of a command's standard error kept to find why it failed
# A value in quotes, such as a search or an ID that a message repeats, and a URL's query string, which can hold the
# search text. The quotes must stand apart from words, so the apostrophe in "can't" opens nothing.
QUOTED = re.compile(r"""(?<!\w)(['"]).*?\1(?!\w)""")
# A word that holds a value without quotes: an entity id such as insight:keep-it-short, whose slug is the user's own
# words, or a path, which can hold a user name. A URL is kept for its host; QUERY then drops its query string.
# Punctuation that ends the sentence stays.
UNQUOTED = re.compile(r"(?<!\S)(?![a-z][\w+.-]*://)\S*?(?:[/\\]|\w:\w)\S*?(?=[,;:.)]*(?:\s|$))", re.IGNORECASE)
# argparse repeats the extra or ambiguous arguments, values included. The scripts refuse shortened flags, so the
# ambiguous message shouldn't appear; this keeps a parser added without that setting safe.
LEFTOVER = re.compile(r"(unrecognized arguments:|ambiguous option:).*")
QUERY = re.compile(r"\?\S*")


def research_folder(start):
    """research/ in the nearest folder at or above start that has one, or None."""
    try:
        start = Path(start).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return next((place / RESEARCH for place in (start, *start.parents) if (place / RESEARCH).is_dir()), None)


def is_on(research):
    return research is not None and (research / SWITCH).exists()


def clean(value):
    """A value that is safe to write: numbers stay numbers, anything else is text cut to MAX_TEXT characters."""
    if isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_TEXT]


def record(source, name, fields):
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return {"time": now, "source": source, "event": name, **{key: clean(value) for key, value in fields.items()}}


def append(research, line):
    """Add a line to the log, moving a full log aside first."""
    log = research / LOG
    if log.exists() and log.stat().st_size + len(line.encode("utf-8")) > MAX_BYTES:
        os.replace(log, research / OLD_LOG)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(line)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# No proxy: events go to this machine only, whatever HTTP_PROXY says.
OPENER = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))


def otlp_url():
    """Where to send events: the logs address of the first of ENDPOINTS that is set, if it is on this machine, else
    None. localhost becomes 127.0.0.1: on Windows, localhost tries ::1 first and waits out the whole timeout there
    when the collector listens on IPv4 only."""
    endpoint = next((os.environ[name] for name in ENDPOINTS if os.environ.get(name)), "")
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS:
        return None
    host = {"localhost": "127.0.0.1", "::1": "[::1]"}.get(parts.hostname, parts.hostname)
    netloc = f"{host}:{port}" if port else host
    return urlunsplit(("http", netloc, parts.path.rstrip("/") + "/v1/logs", "", ""))


def otlp_body(rec):
    """The event as an OpenTelemetry log record, with the same fields as the line in the log."""
    attributes = [
        {"key": "event.name" if key == "event" else key, "value": {"stringValue": str(value)}}
        for key, value in rec.items()
        if key != "time"
    ]
    resource = {"attributes": [{"key": "service.name", "value": {"stringValue": SERVICE}}]}
    log_record = {
        "timeUnixNano": str(time.time_ns()),
        "severityText": "INFO",
        "body": {"stringValue": rec["event"]},
        "attributes": attributes,
    }
    return {"resourceLogs": [{"resource": resource, "scopeLogs": [{"logRecords": [log_record]}]}]}


def send(url, body):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
    )
    with OPENER.open(request, timeout=SEND_TIMEOUT) as response:
        response.read(1)


def event(source, name, folder=".", **fields):
    """Record one event if debugging is on in the workspace at folder. It never raises, so it can't break a command."""
    research = research_folder(folder)
    if not is_on(research):
        return
    rec = record(source, name, fields)
    with contextlib.suppress(OSError, ValueError):
        append(research, json.dumps(rec) + "\n")
    url = otlp_url()
    if url:
        with contextlib.suppress(OSError, ValueError, http.client.HTTPException):
            send(url, otlp_body(rec))


def fetched(source, url, status, started=None):
    """Record one request to a host: its address without the query, which can hold search text, and its status."""
    parts = urlsplit(url)
    fields = {"host": parts.hostname or "", "path": parts.path, "status": status}
    if started is not None:
        fields.update(timing(started))
    event(source, "http", **fields)


def fetch_failed(source, url, err):
    """Record a request that failed, with its status if the server answered, else `network error`."""
    fetched(source, url, getattr(err, "code", "network error"))


def note(**fields):
    """Add fields, such as the command's name, to the `command` event that run() records."""
    NOTES.update(fields)


class Kept:
    """Standard error that also keeps the first KEPT characters written to it, so a failed command can say why."""

    def __init__(self, stream):
        self.stream = stream
        self.text = ""

    def write(self, text):
        self.text += text[: KEPT - len(self.text)]
        return self.stream.write(text)

    def __getattr__(self, name):  # reconfigure, flush, and the rest go to the real stream
        return getattr(self.stream, name)


def reason(text):
    """Why a command failed: the first line of its standard error that says error:, else its first line, without
    the values that can hold the user's words or search text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    line = next((line[line.index("error:") :] for line in lines if "error:" in line), lines[0] if lines else "")
    line = UNQUOTED.sub("…", QUOTED.sub("'…'", line))
    return QUERY.sub("?…", LEFTOVER.sub(r"\1 …", line))


def run(source, main, argv):
    """Run a script's main, and record its command, exit code, duration, and, if it failed, the reason."""
    NOTES.clear()
    started = time.monotonic()
    kept = Kept(sys.stderr)
    sys.stderr = kept
    try:
        code = main(argv)
    except SystemExit as stop:  # argparse exits this way on a usage error, after printing it
        code = stop.code or 0
        if not isinstance(code, int):  # sys.exit("message") prints its message only after this
            kept.text, code = str(code), 1
        finished(source, started, code, kept.text)
        raise
    except Exception as err:
        event(source, "command", exit="error", error=type(err).__name__, **timing(started), **NOTES)
        raise
    finally:
        sys.stderr = kept.stream
    finished(source, started, code, kept.text)
    return code


def finished(source, started, code, text):
    """Record a command that ended with an exit code, and, if it failed, its reason."""
    why = reason(text) if code else ""
    event(source, "command", exit=code, **timing(started), **({"reason": why} if why else {}), **NOTES)


def timing(started):
    return {"duration_ms": round((time.monotonic() - started) * 1000)}


# --- the command line --------------------------------------------------------------------------------------------


def cmd_on(research):
    (research / SWITCH).write_text(datetime.now(timezone.utc).isoformat(timespec="seconds") + "\n", encoding="utf-8")
    print(f"debug is on since {(research / SWITCH).read_text(encoding='utf-8').strip()}")
    print(f"events go to {research / LOG}{export_note()}")
    return 0


def export_note():
    url = otlp_url()
    return f" and to {url}" if url else ""


def cmd_off(research):
    (research / SWITCH).unlink(missing_ok=True)
    print("debug is off")
    return 0


def log_size(research):
    return sum(path.stat().st_size for path in (research / LOG, research / OLD_LOG) if path.exists())


def cmd_status(research):
    print(f"debug is {'on' if is_on(research) else 'off'}")
    print(f"log: {log_size(research)} bytes of at most {2 * MAX_BYTES}, in {research / LOG}")
    print(f"export: {otlp_url() or 'none (PAPER_RESEARCH_OTLP_ENDPOINT is not set to a local address)'}")
    return 0


def cmd_show(research, lines):
    texts = [(research / name).read_text(encoding="utf-8") for name in (OLD_LOG, LOG) if (research / name).exists()]
    for line in "".join(texts).splitlines()[-lines:]:
        print(line)
    return 0


def cmd_clear(research):
    for name in (LOG, OLD_LOG):
        (research / name).unlink(missing_ok=True)
    print("log cleared")
    return 0


class Parser(argparse.ArgumentParser):
    """A parser that takes whole flags only. A shortened flag is refused rather than guessed, and argparse's message
    for an ambiguous one repeats its value, which the debug log would record. Subcommand parsers are made from the
    parser's own class, so they refuse them too."""

    def __init__(self, **kwargs):
        super().__init__(allow_abbrev=False, **kwargs)


def build_parser():
    parser = Parser(description="Turn the plugin's debug log on or off, and read it.")
    parser.add_argument("--workspace", type=Path, default=Path("."), help="workspace root (default: here)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("on", help="start recording events")
    commands.add_parser("off", help="stop recording events; the log stays")
    commands.add_parser("status", help="say whether it is on, and how big the log is")
    show = commands.add_parser("show", help="print the latest events")
    show.add_argument("--lines", type=int, default=50, help="how many (default: 50)")
    commands.add_parser("clear", help="delete the log")
    return parser


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    research = args.workspace / RESEARCH
    if not research.is_dir():
        print(f"error: research folder not found: '{research}'", file=sys.stderr)
        return 2
    if args.command == "show":
        return cmd_show(research, args.lines)
    return {"on": cmd_on, "off": cmd_off, "status": cmd_status, "clear": cmd_clear}[args.command](research)


if __name__ == "__main__":  # pragma: no mutate (`is` and `<=` agree for the names a module can have)
    sys.exit(main())
