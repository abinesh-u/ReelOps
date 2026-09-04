# Control Tower UI

Primary views:

- Production health
- Active risk
- Evidence chain
- Recommendation + approval
- Recovery verification

Design principle: control-tower workflow first; chat is secondary.

## Main screen

Makes eight things immediately obvious:

```text
PROJECT HEALTH · PIPELINE STATE · ACTIVE RISK · ROOT CAUSE
DOWNSTREAM IMPACT · RECOMMENDED ACTION · APPROVAL STATE · RECOVERY STATE
```

## Investigation view — evidence chain

```text
1. Metric anomaly
2. Worker health degradation
3. Log pattern
4. Trace slowdown
5. Production dependency
6. Schedule constraint
7. Risk prediction
8. Recommended response
9. Verification result
```

A judge should understand the system from this view alone, without reading a prompt transcript.
