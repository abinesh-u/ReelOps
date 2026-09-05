"""The Sentinel agent: is something abnormal right now?

Telemetry reads only (`agents/tool_budget.py`'s `sentinel` entry: Prometheus,
no logs, no traces). Detection only — no incident creation, no state mutation.
`docs/agents.md` has the full responsibility statement.
"""

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.config import GrafanaSettings, ModelSettings
from agents.contracts import AnomalyContract
from agents.grafana_mcp import grafana_toolset
from agents.sentinel.prompts import SENTINEL_INSTRUCTION

SENTINEL_APP_NAME = "reelops-sentinel"
SENTINEL_OUTPUT_KEY = "sentinel_anomaly"


def build_sentinel_agent(
    grafana_settings: GrafanaSettings | None = None,
    model_settings: ModelSettings | None = None,
) -> LlmAgent:
    """Construct the Sentinel `LlmAgent`. Raises before any network call if
    either Grafana or Vertex configuration is incomplete.
    """
    model_settings = model_settings or ModelSettings()
    model_settings.require_vertex()

    return LlmAgent(
        name="sentinel",
        model=model_settings.gemini_model,
        instruction=SENTINEL_INSTRUCTION,
        tools=[grafana_toolset("sentinel", grafana_settings)],
        output_schema=AnomalyContract,
        output_key=SENTINEL_OUTPUT_KEY,
    )


async def run_sentinel(
    project_id: str,
    *,
    grafana_settings: GrafanaSettings | None = None,
    model_settings: ModelSettings | None = None,
) -> AnomalyContract:
    """Run the Sentinel once for `project_id` and return its validated verdict."""
    grafana_settings = grafana_settings or GrafanaSettings()
    agent = build_sentinel_agent(grafana_settings, model_settings)

    async with InMemoryRunner(agent=agent, app_name=SENTINEL_APP_NAME) as runner:
        session = await runner.session_service.create_session(
            app_name=SENTINEL_APP_NAME, user_id="reelops"
        )
        # The Prometheus datasourceUid is deliberately pinned, not discoverable
        # by any tool sentinel holds (agents/config.py) — it must be handed
        # over here, or every query_prometheus call fails and the agent can
        # only, correctly, report that it could not query anything.
        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=f"project_id={project_id}\n"
                    f"prometheus_datasource_uid={grafana_settings.grafana_prom_datasource_uid}"
                )
            ],
        )
        async for _event in runner.run_async(
            user_id="reelops", session_id=session.id, new_message=message
        ):
            pass  # drain the run; the result lives in session state afterward

        final = await runner.session_service.get_session(
            app_name=SENTINEL_APP_NAME, user_id="reelops", session_id=session.id
        )
        raw = final.state[SENTINEL_OUTPUT_KEY]

    return AnomalyContract.model_validate(raw)
