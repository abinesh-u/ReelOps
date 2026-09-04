# Demo runbook

1. Start healthy Project Aurora.
2. Show normal render queue and worker availability.
3. Inject render-worker degradation.
4. Let Sentinel detect the anomaly without revealing the fault label.
5. Let Investigator query Grafana through MCP.
6. Show evidence chain: metrics + logs + traces/Sift.
7. Impact Agent joins Scene 42 dependency and editorial deadline.
8. Show predicted delay and recommended recovery.
9. Approve the bounded action.
10. Show Grafana incident/audit entry.
11. Verification Agent confirms queue and latency recovery.

The demo should be reproducible from a single command once implementation is complete.

## 3-minute timing

```text
0:00  Healthy production
0:15  Incident appears
0:30  Agent detects it
0:55  Agent investigates Grafana telemetry
1:25  Root cause established
1:45  Downstream schedule risk revealed
2:05  Response proposed
2:20  Human approves
2:35  Recovery occurs
2:50  Verification confirms recovery
3:00  Value proposition
```

Spend the time showing the system doing the work; keep architecture diagrams to a beat.
