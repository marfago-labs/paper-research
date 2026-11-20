# Telemetry

To see what Claude and the plugin do in a session, run a telemetry stack on your own machine and point Claude Code's OpenTelemetry export at it. You see every tool call, hook, skill, and MCP call, with timings and errors, in Grafana. Nothing is sent anywhere else.

This is optional and only for debugging. The plugin works the same without it.

## Start the stack

You need Docker, and the plugin's `telemetry/` folder: the Compose file and a dashboard. Copy the folder to a place of its own. Get it from the repository, or from the plugin as Claude Code installed it, in `~/.claude/plugins/cache/<marketplace>/paper-research/<version>/telemetry/`. Copy it rather than run it there, because that folder changes with every update of the plugin.

Then, in the copy:

```bash
docker compose up -d
```

It runs one container, [`grafana/otel-lgtm`](https://github.com/grafana/docker-otel-lgtm), with an OpenTelemetry collector, Loki for events, Prometheus for metrics, Tempo for traces, and Grafana to read them. Its ports listen only on `127.0.0.1`:

| Port | Use |
|---|---|
| `3000` | Grafana, at http://localhost:3000 |
| `4317` | OTLP over gRPC |
| `4318` | OTLP over HTTP |

The data is kept in a Docker volume, so it survives a restart.

Run these in the same folder:

- **Stop:** `docker compose down`
- **Stop and delete everything recorded:** `docker compose down -v`

## Turn on Claude Code's export

Add this to `~/.claude/settings.json`, merging it with what's there, then start a new session:

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
    "OTEL_LOG_TOOL_DETAILS": "1",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_TRACES_EXPORTER": "otlp"
  }
}
```

It has to go in your user settings or your shell. Claude Code ignores these variables in a project's `.claude/settings.json`, so a repository can't turn telemetry on or choose where it goes.

- `OTEL_LOG_TOOL_DETAILS` adds the file paths, URLs, shell commands, skill names, and MCP server and tool names to each tool event. Without it you see only the tool's name, which isn't enough to debug the plugin.
- The last two lines turn on traces, which are a beta in Claude Code. Leave them out if you only want events and metrics.

To stop the export, remove the block, or set `CLAUDE_CODE_ENABLE_TELEMETRY` to `0`.

## What to look at

Open Grafana at http://localhost:3000. It needs no login.

Three dashboards are already there, linked from each other's top bar:

- **paper-research: usage and security.** Open this one first. It starts with two rows of numbers: **Metrics** (cost, prompts, sessions, model and tool calls, skill and script runs, and calls and cost per prompt) and **Alarms** (failed tool calls and script runs, rejected calls, blocking hooks, risky commands, and sensitive file access, red when above zero). Below them:
  - cost by model, and where the time goes;
  - a paper-research row, as Claude Code recorded it, so it works with debug off: skill runs, time and cost per skill, each skill run, each script's runs, failures and time, and the sessions of each plugin version, to compare releases;
  - cost and model calls per prompt, with the most expensive prompts;
  - a security row: tool decisions, rejected calls, MCP servers and tools, risky shell commands, sensitive files, and web fetches.
- **paper-research: service details.** Model calls (by model and source, errors, tokens, cache hit rate, latency), tools, hooks, recent traces from Tempo, and the latest events.
- **paper-research: plugin debug log.** The plugin's own events: commands and their exit codes, requests to arXiv and Semantic Scholar with rate limits (429) apart from failures, the guard's and the stop hook's decisions, and the size of the session-start text. It stays empty until the debug log is on.

Every panel has a description, and each queries on its own, so an empty panel doesn't affect the rest. Use the time picker at the top for the range: it starts at the last 6 hours. The per-prompt panels include background calls such as session titles, so use the **Model call source** box at the top to narrow them: a regular expression on `query_source`, where `sdk` is the main conversation.

For anything else, use **Explore**.

- **Events (Loki):** `{service_name="claude-code"}`. Each event has an `event_name`:
  - `tool_decision` and `tool_result`: every tool call, whether it was allowed or asked, and how it ended. This is where a fetch, an edit to `research/`, or a call to an MCP server shows up.
  - `hook_execution_complete`: each hook the plugin runs, named like `PreToolUse:Write` or `Stop`, with its duration and how many blocked.
  - `skill_activated`: which of the plugin's skills Claude used.
  - `mcp_server_connection`: which MCP servers the session connected to.
  - `api_request` and `api_error`: the model calls, with tokens, cost, and errors.
- **Traces (Tempo):** search for `claude_code.interaction`. Each prompt is one trace, with its model calls, tool calls, and hooks as child spans, and the time spent waiting for your approval.
- **Metrics (Prometheus):** search for `claude_code_`, such as session, token, and cost counts.

Events arrive within about five seconds. Metrics are sent once a minute by default. Events are stored by their `service_name`, with each attribute attached to the event, so filter with `{service_name="claude-code"} | event_name="tool_result"`.

The full list of events and attributes is in Claude Code's [monitoring documentation](https://code.claude.com/docs/en/monitoring-usage).

## The plugin's own events

Claude Code's events show what Claude did. To see what the plugin's scripts and hooks decided, turn on the plugin's debug log: ask Claude to turn debug on (the `debug` skill), or run `python <skills>/debug/scripts/debuglog.py on` in the workspace. While it is on, each script and hook records its events in `research/.debug.log`, and, when the stack above is running and `OTEL_EXPORTER_OTLP_ENDPOINT` is set as shown, also sends them to it. Turn it off the same way when you're done: it is off by default, and it never turns itself off.

The events have `service_name="paper-research"` in Loki, with the `event_name` and `source` attributes:

- `command`: each run of a script, with its `command`, `exit` code, and `duration_ms`.
- `http`: each request to arXiv or Semantic Scholar, with `host`, `path`, `status` (`network error` if the server didn't answer), and `duration_ms`. A search's query string is never recorded.
- `guard`: each decision of the approval hook, with the `tool`, `decision` (`ask` or `pass`), and `reason`.
- `rules`, `lessons`, `stop_hook`: what the session-start hooks loaded, and whether the Stop hook blocked.

For example, `{service_name="paper-research"} | event_name="http" | status!="200"` lists every request that was refused or failed. The plugin sends only to an address on this machine, and the local file doesn't need Docker.

## Privacy

- Everything stays in the container on your machine. The ports don't listen on your network, and Grafana opens without a login, so don't change the port bindings.
- Your prompts and Claude's replies are not recorded unless you set `OTEL_LOG_USER_PROMPTS`. Leave it unset.
- With `OTEL_LOG_TOOL_DETAILS`, the events hold file paths, URLs, and shell commands, which show what you read and searched for. Your Claude account's email address is attached to every event when you sign in with your account.
- Delete the data with `docker compose down -v` when you're done debugging.
