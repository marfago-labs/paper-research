---
name: debug
description: Turn the plugin's debug log on or off, and read it, to see what its scripts and hooks did and why. Use when the user asks to debug the plugin, to see what it did or why something happened, to turn debug on or off, or to show the debug log.
---

# Debug log

Run from the workspace root. `<skills>` is the folder that contains this skill's base directory. The log is off unless the user turns it on, so never turn it on yourself.

Run `python <skills>/debug/scripts/debuglog.py COMMAND`:

- `on`: start recording. It creates `research/.debug`, and says where the events go.
- `off`: stop recording. The log stays, so it can still be read.
- `status`: say whether it is on, how big the log is, and whether events are also sent to a local OpenTelemetry collector.
- `show [--lines N]`: print the latest events, 50 by default.
- `clear`: delete the log.

While it is on, every script and hook adds one JSON line per event to `research/.debug.log`: each command with its exit code and duration, each request to arXiv or Semantic Scholar with its host, path, and status, each decision of the approval hook with its reason, and what the session-start hooks loaded. Each of the two log files holds at most 2 MB: when the log is full it moves to `.debug.log.1`, which replaces the older one, so the events never take more than 4 MB. If `PAPER_RESEARCH_OTLP_ENDPOINT` points at this machine, the same events also go there.

To answer "why did that happen?", run `show`, read the events around it, and tell the user what you found. Say which events you read.

The events hold names, hosts, statuses, counts, and timings, never notes or search text. When the user has finished, ask whether to turn it off, and do so if they agree.
