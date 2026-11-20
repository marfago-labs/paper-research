#!/usr/bin/env python3
"""Record what the plugin does, for debugging. Standard library only.

It is off by default. `debuglog.py on` creates research/.debug, and `debuglog.py off` removes it. While the file
exists, the plugin's scripts and hooks append one JSON line per event to research/.debug.log, and, if
OTEL_EXPORTER_OTLP_ENDPOINT points at this machine, send the same event there as an OpenTelemetry log record.
The log holds at most 2 MB: when it is full it moves to research/.debug.log.1, which replaces the older one.
Two scripts that write at the same moment can lose an event; that is accepted for a debug log.
An event holds names, hosts, statuses, counts, and timings, never notes or search text.

Commands: on, off, status, show [--lines N], clear.
Exit codes: 0 success, 2 usage error.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

RESEARCH = "research"
SWITCH = ".debug"
LOG = ".debug.log"
OLD_LOG = ".debug.log.1"
MAX_BYTES = 2_000_000
MAX_TEXT = 200
SERVICE = "paper-research"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SEND_TIMEOUT = 0.5  # seconds; the collector is on this machine, so it answers at once or not at all
NOTES: dict = {}  # fields that a command adds to its own `command` event


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
    """Where to send events: the logs address of OTEL_EXPORTER_OTLP_ENDPOINT if that is on this machine, else None."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return None
    if parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS:
        return None
    return endpoint.rstrip("/") + "/v1/logs"


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


def run(source, main, argv):
    """Run a script's main, and record its command, exit code, and duration."""
    NOTES.clear()
    started = time.monotonic()
    try:
        code = main(argv)
    except Exception as err:
        event(source, "command", exit="error", error=type(err).__name__, **timing(started), **NOTES)
        raise
    event(source, "command", exit=code, **timing(started), **NOTES)
    return code


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
    print(f"export: {otlp_url() or 'none (OTEL_EXPORTER_OTLP_ENDPOINT is not set to a local address)'}")
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


def build_parser():
    parser = argparse.ArgumentParser(description="Turn the plugin's debug log on or off, and read it.")
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
        print(f"error: research folder not found: {research}", file=sys.stderr)
        return 2
    if args.command == "show":
        return cmd_show(research, args.lines)
    return {"on": cmd_on, "off": cmd_off, "status": cmd_status, "clear": cmd_clear}[args.command](research)


if __name__ == "__main__":  # pragma: no mutate (`is` and `<=` agree for the names a module can have)
    sys.exit(main())
