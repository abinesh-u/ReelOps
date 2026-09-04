# Production simulator

Simulates the minimum distributed workflow required for the golden scenario:

`VFX → Render Queue → Render Workers → Editorial Review`

The simulator must emit metrics, structured logs, and OpenTelemetry traces without exposing ground-truth fault labels to the agents.
