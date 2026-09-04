# Grafana Cloud setup

Phase 3 of the build order. Exit criterion: an agent completes a real MCP tool call against live telemetry.

Two decisions this runbook makes, and why:

- **Self-hosted `mcp-grafana`, not the hosted Cloud MCP server.** The hosted server at `https://mcp.grafana.com/mcp` authenticates with an interactive OAuth 2.1 flow, which a headless agent on Cloud Run cannot complete. The open-source server takes a service account token and — decisively — exposes `--enabled-tools` / `--disable-write`, the only mechanism that enforces the least-privilege rule in `../AGENTS.md`.
- **OTLP for all three signals.** One endpoint and one credential for metrics, logs, and traces, with no Alloy or scrape target to run. OTLP metrics land in Mimir and stay queryable with PromQL.

---

## 1. Create the stack

Sign up at [grafana.com](https://grafana.com/auth/sign-up/create-user) and create a stack. The free tier covers everything ReelOps needs: Mimir metrics, Loki logs, Tempo traces, and IRM for incidents and on-call.

IRM bills by *active* user — anyone on an on-call schedule or escalation chain, or who changes an alert group. Keep the demo on your own account.

Note the stack URL (`https://<stack>.grafana.net`). It becomes `GRAFANA_URL`.

## 2. Get OTLP credentials

In the Cloud portal, open your stack and click **Configure** on the **OpenTelemetry** tile. It generates the endpoint and an authentication token, and prints the environment variables ready to paste.

Copy the endpoint from that tile rather than composing it by hand — the hostname varies by region and by when the region was created.

Into `.env`:

```sh
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=<from the OpenTelemetry tile>
OTEL_EXPORTER_OTLP_HEADERS=<from the OpenTelemetry tile>   # Basic <base64 instanceID:token>
OTEL_SERVICE_NAME=reelops-simulator
```

`OTEL_EXPORTER_OTLP_HEADERS` carries a credential. It belongs in `.env` and Secret Manager, never in a commit.

Then start the simulator with export on:

```sh
TELEMETRY_ENABLED=true uv run python -m simulator
```

Without a stack yet, `TELEMETRY_CONSOLE=true` prints the same records to stdout,
and `uv run pytest tests/test_telemetry.py` asserts the export path in memory.

## 3. Import the dashboard

`dashboards/reelops-render.json` covers the five golden-scenario signals plus
the log panel. In Grafana: **Dashboards → New → Import → Upload JSON file**, then
pick your Prometheus and Loki data sources when prompted.

Its panel queries are the reference PromQL and LogQL. Phase 4's agents are
written against them, so a query that works here is a query an agent can use.

## 4. Create a service account token

In your Grafana stack: **Administration → Users and access → Service accounts → Add service account**.

Give it the **Viewer** role for the read path. Add the narrower write permissions only when Phase 6 needs `create_incident`; the investigation path never requires them.

**Add service account token**, copy it once, and store it as `GRAFANA_SERVICE_ACCOUNT_TOKEN`.

Viewer may not be enough, and the failure is a 403 that surfaces later as an
opaque MCP error. mcp-grafana queries through
`/api/datasources/uid/<uid>/resources/api/v1/query`, which needs
`datasources:read` — carried by the fixed role *Data sources reader*, not by
basic Viewer. Probe it directly rather than reasoning about it:

```sh
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $GRAFANA_SERVICE_ACCOUNT_TOKEN" \
  "$GRAFANA_URL/api/datasources/uid/$GRAFANA_PROM_DATASOURCE_UID/resources/api/v1/query?query=up"
```

`200` and you are done. `403` — add the fixed role *Data sources reader* to the
service account and probe again; Editor is the last resort. `401` is a bad
token, `404` a wrong UID. Escalating the Grafana role does not widen what agents
can do: `--disable-write` is the enforced boundary.

## 4b. Pin the datasource UIDs

`query_prometheus` and `query_loki_logs` both take `datasourceUid` as a
**required** argument. Discovering it at run time would mean re-enabling the
`datasource` category for one call per run, so the UIDs are pinned in `.env`
instead.

In Grafana: **Connections → Data sources**, open the Prometheus one, and read
the UID out of the URL — `/connections/datasources/edit/<uid>`. Repeat for Loki.

```sh
GRAFANA_PROM_DATASOURCE_UID=<from the URL>
GRAFANA_LOKI_DATASOURCE_UID=<from the URL>
```

## 5. Run the MCP server

Locally, with least privilege — read-only, and only the tool categories the
golden path uses. This is the canonical launch command; nothing else in the repo
repeats it.

```sh
brew install mcp-grafana

GRAFANA_URL="$(grep '^GRAFANA_URL=' .env | cut -d= -f2-)" \
GRAFANA_SERVICE_ACCOUNT_TOKEN="$(grep '^GRAFANA_SERVICE_ACCOUNT_TOKEN=' .env | cut -d= -f2-)" \
mcp-grafana -t streamable-http --disable-write --enabled-tools=incident,loki,oncall,prometheus
```

`GRAFANA_MCP_URL` is then `http://localhost:8000/mcp`.

**The env line is not decoration.** mcp-grafana is a separate process that reads
process environment and never `.env`. And `.env` must not be shell-sourced:
`set -a; . ./.env` exits **0** while silently truncating
`OTEL_EXPORTER_OTLP_HEADERS` to `Authorization=Basic`, because the value
contains a space and bash parses the remainder as a command. The credential
vanishes with no error — measured, not theorised. Prefix-scoped extraction with
`cut -d= -f2-` keeps both the spaces and the `=` inside values.

Useful flags, as `mcp-grafana --help` reports them in 1.3.0:

| Flag | Effect |
| --- | --- |
| `--disable-write` | Drops every create/update tool — see the note below on which |
| `--disable-<category>` | Drops one category, e.g. `--disable-oncall` |
| `--enabled-tools=a,b` | **Restricts** to the listed categories. It narrows; it does not opt in. The default already enables 23 |
| `--disable-query` / `--enable-query` | Withhold or keep the raw-SQL query tools; ReelOps enables neither category |
| `-t stdio\|sse\|streamable-http` | Transport. `-address` moves it off `localhost:8000` |
| `--metrics` | Prometheus metrics for the server itself at `/metrics` |
| `--debug` | Verbose HTTP logging when a tool call misbehaves |

`agents/tool_budget.py` is the machine-readable copy of the budget, and it
generates the `--enabled-tools` value above; a test asserts the two agree.

**Why `sift` is not in that category list.** Measured on 1.3.0 with `sift`
enabled: 31 tools without `--disable-write`, 25 with it. The six the flag
removes are `create_incident`, `update_incident`, `add_activity_to_incident`,
`update_alert_group`, `find_error_pattern_logs` and `find_slow_requests` — the
last two because creating a Sift investigation is a write. So a read-only server
serves neither, and the read path cannot use them however it is filtered. What
remains of the category is read-only but unused, so the category stays off and
log-pattern evidence comes from `query_loki_patterns` instead.

**There is no Tempo category at all** — traces are reachable only through Sift
and the Grafana UI, so Phase 4 must not reach for a Tempo tool.

The command above serves **22 tools**, all seven budgeted read tools among them
and no write tool. `list_alert_groups` and `get_alert_group` arrive as part of
`oncall`; the mutating `update_alert_group` does not, which is what keeps
alert-group mutation off per `AGENTS.md`.

ADK adds a second lever on the client side: `McpToolset(..., tool_filter=[...])` restricts which of the server's tools an agent can see. Use both — the server flags are the boundary, the filter is what each agent is handed.

On Cloud Run, deploy this as a sidecar container in the same service, with the token mounted from Secret Manager.

Phase 6 needs the write path. Run a second instance without `--disable-write`, reachable only from the Response agent, so the read-only agents keep a read-only server.

## 6. Verify — the real gate

A health check proves the process booted, not that the setup works. Phase 3 is done when a tool call returns live data.

```sh
curl -s localhost:8000/healthz          # expect: ok
```

With the simulator running and emitting, the gate is a test rather than a
command to eyeball:

```sh
REELOPS_LIVE_MCP=1 uv run pytest tests/test_grafana_live.py -q
```

It is opt-in by that flag, not by the presence of `GRAFANA_URL` — otherwise an
ordinary `uv run pytest -q` would try to reach a server that is not running. If
the flag is set and the configuration is incomplete, those tests **fail rather
than skip**: a gate that quietly excuses itself is the same bug as an empty
series reading as health.

Five assertions stand between "the call worked" and "the telemetry is live": the
call did not return an error envelope; the result is non-empty; a series carries
at least two datapoints, so it is a stream and not one stale point; its `project`
label matches `PROJECT_ID`, so it is our data and not a neighbour's; and its
newest sample is under five minutes old.

For a quick look at what the server exposes before running the gate:

```sh
uv run python -c "
import asyncio, os
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams

async def main():
    ts = McpToolset(connection_params=StreamableHTTPConnectionParams(url=os.environ['GRAFANA_MCP_URL']))
    tools = await ts.get_tools()
    print(len(tools), 'tools:', sorted(t.name for t in tools)[:10])
    await ts.close()

asyncio.run(main())
"
```

The gate is a PromQL query through the MCP server that returns a **non-empty** series for a metric the simulator actually emitted — `render_queue_depth` is the one to try. An empty result means telemetry is not arriving, and no amount of agent work will fix it.

Phase 2's own gate comes first, and needs no MCP: run a healthy take, inject the
fault, and confirm the dashboard shows queue depth climbing while available
workers drop to 7 and p95 duration rises.

```sh
TELEMETRY_ENABLED=true SIM_SPEED=20 uv run python -m simulator
curl -sX POST localhost:8090/sim/inject/render-worker-degradation \
  -H 'content-type: application/json' -d '{"workers":5}'
```

`SIM_SPEED=20` plays the 90 sim-minute window over 4.5 real minutes, which at
the default 5-second export interval is ~54 points per series — enough for a
readable slope. At `SIM_SPEED=60` the same window yields 18.

Remember the histograms: `render_job_duration_seconds` has no series under its
own name, only `_bucket`/`_sum`/`_count`. See `telemetry-contract.md`.

If Phase 6 has enabled the write path, confirm `create_incident` is reachable before trusting the approval flow.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Tool call returns an empty series | Three causes, in this order: telemetry never arrived (check the OTLP exporter, not MCP — run `list_prometheus_metric_names` first); the simulator is not running now, so the points are older than the window; or the `project` label does not match `PROJECT_ID` |
| Metric name not found | Suffix conversion — see the OTLP section of `telemetry-contract.md` |
| `service` label missing | OTLP promotes `service.name` to the `job` label; query `job`, or set `service` as an explicit attribute |
| LogQL filtering on `project` returns nothing | Metrics label it `project`; **logs label it `project_id`**. The two are not the same key |
| 403 on a query, tools list fine | The service account lacks `datasources:read`. Run the probe in §4 and add the fixed role *Data sources reader* |
| 401 from the MCP server | Token lacks the role, or `GRAFANA_URL` points at the wrong stack |
| Tool missing from the list | Its category is not in `--enabled-tools`, or it is a write tool and `--disable-write` is on. The flag narrows; it does not opt in |
| MCP server starts but every call 401s | It reads process environment, never `.env`. Use the prefix-scoped launch line in §5 |
| Port 8000 already in use | An earlier server is still running, or move this one with `-address localhost:8001` |
