# Threat model

Primary concerns:

- prompt injection through log content
- over-privileged Grafana tools
- unauthorized production mutations
- fabricated evidence
- runaway tool loops

Controls:

- treat telemetry as untrusted data, not instructions
- least-privilege MCP tool exposure per agent — two levers, both generated from
  `agents/tool_budget.py`: the server's `--enabled-tools`/`--disable-write` is
  the boundary, and ADK's per-agent `tool_filter` is what each agent is handed
- explicit structured evidence records
- bounded investigation steps
- human approval for mutations
- post-action verification
