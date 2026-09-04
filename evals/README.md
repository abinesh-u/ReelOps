# Evaluation

Track at minimum:

- time-to-detect
- root-cause accuracy
- downstream impact prediction error
- time-to-recovery
- Grafana MCP tool-call count
- failed tool calls
- unnecessary escalation rate

## What each metric means

| Metric | Definition |
| --- | --- |
| Time to detect | fault injected → anomaly detected |
| Root-cause accuracy | agent root cause ↔ scenario ground truth |
| Impact prediction error | predicted delay ↔ simulated/observed delay |
| Time to recovery | approved action → recovered state |
| Tool efficiency | MCP call count, tool failures, investigation duration, unnecessary calls, reported confidence |

Ground truth per scenario lives in `scenarios.yaml`. Preserve structured evidence from each run so a result can be re-scored later.

ReelOps is judged as an agentic system, not on UI polish.
