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

## 3. Create a service account token

In your Grafana stack: **Administration → Users and access → Service accounts → Add service account**.

Give it the **Viewer** role for the read path. Add the narrower write permissions only when Phase 6 needs `create_incident`; the investigation path never requires them.

**Add service account token**, copy it once, and store it as `GRAFANA_SERVICE_ACCOUNT_TOKEN`.

## 4. Run the MCP server

Locally, with least privilege — read-only, and only the tool categories the golden path uses:

```sh
docker run --rm -p 8000:8000 \
  -e GRAFANA_URL \
  -e GRAFANA_SERVICE_ACCOUNT_TOKEN \
  grafana/mcp-grafana -t streamable-http --disable-write
```

`GRAFANA_MCP_URL` is then `http://localhost:8000/mcp`.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--disable-write` | Blocks dashboard, incident, and alert mutation |
| `--disable-<category>` | Drops a category, e.g. `--disable-oncall` |
| `--enabled-tools=a,b` | Opt into categories that are off by default |
| `--metrics` | Prometheus metrics for the server itself at `/metrics` |
| `--debug` | Verbose HTTP logging when a tool call misbehaves |

ADK adds a second lever on the client side: `McpToolset(..., tool_filter=[...])` restricts which of the server's tools an agent can see. Use both — the server flags are the boundary, the filter is what each agent is handed.

On Cloud Run, deploy this as a sidecar container in the same service, with the token mounted from Secret Manager.

Phase 6 needs the write path. Run a second instance without `--disable-write`, reachable only from the Response agent, so the read-only agents keep a read-only server.

## 5. Verify — the real gate

A health check proves the process booted, not that the setup works. Phase 3 is done when a tool call returns live data.

```sh
curl -s localhost:8000/healthz          # expect: ok
```

Then, with the simulator running and emitting:

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

If Phase 6 has enabled the write path, confirm `create_incident` is reachable before trusting the approval flow.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Tool call returns an empty series | Telemetry is not arriving; check the OTLP exporter before the agent |
| Metric name not found | Suffix conversion — see the OTLP section of `telemetry-contract.md` |
| `service` label missing | OTLP promotes `service.name` to the `job` label; query `job`, or set `service` as an explicit attribute |
| 401 from the MCP server | Token lacks the role, or `GRAFANA_URL` points at the wrong stack |
| Tool missing from the list | Its category is off by default; add it with `--enabled-tools` |
