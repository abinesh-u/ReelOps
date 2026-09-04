# Infrastructure

Target deployment:

- Cloud Run for web/API and agent runtime where practical
- Google ADK for orchestration
- Gemini for reasoning
- Firestore for production-domain state
- Secret Manager for credentials
- Grafana Cloud MCP for runtime observability access

Keep infrastructure intentionally small for the hackathon; do not introduce Kubernetes unless a demonstrated requirement emerges.
