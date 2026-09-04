# ReelOps

**ReelOps** is an agentic production reliability platform for modern film/media workflows — a Gemini + Google ADK multi-agent control plane for film-production operations.

## Product thesis

ReelOps observes a simulated film-production pipeline through Grafana Cloud telemetry, investigates anomalies via Grafana MCP, predicts downstream schedule impact, recommends bounded remediation, requires human approval for consequential actions, and verifies recovery.

## Who it is for

VFX/post-production supervisors, production operations managers, and technical production leads.

## Core problem

Film production is a distributed workflow. Failures in ingest, VFX, rendering, review, asset delivery, QC, or infrastructure propagate into schedule risk, and operators usually discover them only once the impact is visible. ReelOps turns production telemetry into proactive production decisions.

## Golden scenario

**Render capacity degradation → VFX queue growth → Scene 42 editorial deadline risk → human-approved recovery → verification.**

## Architecture

```text
Control Tower UI
      |
      v
Google ADK Supervisor
      |
  +---+----------+----------+----------+---+
  |              |          |          |   |
Sentinel    Investigator  Impact   Response Verify
  |              |          |          |   |
  +--------------+----------+----------+---+
                     |
               Grafana Cloud MCP
              /       |       \
        Prometheus   Loki     Tempo/Sift
                     |
              Production telemetry
                     |
              Production Simulator
                     |
                 Firestore
```

## Where things live

Engineering constraints, working rules, and the build order live in `AGENTS.md`. Design specs live in `docs/`; a directory earns its own doc once it has code and a convention the code cannot show.

## Current status

Architecture scaffold only. Implementation starts with the simulator + telemetry contract, then the Sentinel/Investigator loop, then impact/response/verification, then UI and deployment.

## Hackathon track

Agentic Cinema — Grafana track.
