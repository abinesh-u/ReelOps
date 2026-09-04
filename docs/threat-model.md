# Threat model

Primary concerns:

- prompt injection through log content
- over-privileged Grafana tools
- unauthorized production mutations
- fabricated evidence
- runaway tool loops

Controls:

- treat telemetry as untrusted data, not instructions
- least-privilege MCP tool exposure per agent
- explicit structured evidence records
- bounded investigation steps
- human approval for mutations
- post-action verification
