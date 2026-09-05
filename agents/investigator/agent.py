"""The Investigator agent: why is it happening?

Evidence sequence: metric anomaly -> service health -> log/error patterns ->
slow renders -> traces -> root-cause hypothesis. The only agent given traces
(`agents/tool_budget.py`'s `investigator` entry). `docs/agents.md` has the
full responsibility statement.
"""

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.config import GrafanaSettings, ModelSettings
from agents.contracts import AnomalyContract, RootCauseContract
from agents.grafana_mcp import grafana_toolset
from agents.investigator.prompts import INVESTIGATOR_INSTRUCTION

INVESTIGATOR_APP_NAME = "reelops-investigator"
INVESTIGATOR_OUTPUT_KEY = "investigator_root_cause"


def build_investigator_agent(
    grafana_settings: GrafanaSettings | None = None,
    model_settings: ModelSettings | None = None,
) -> LlmAgent:
    """Construct the Investigator `LlmAgent`. Raises before any network call if
    either Grafana or Vertex configuration is incomplete.
    """
    model_settings = model_settings or ModelSettings()
    model_settings.require_vertex()

    return LlmAgent(
        name="investigator",
        model=model_settings.gemini_model,
        instruction=INVESTIGATOR_INSTRUCTION,
        tools=[grafana_toolset("investigator", grafana_settings)],
        output_schema=RootCauseContract,
        output_key=INVESTIGATOR_OUTPUT_KEY,
    )


async def run_investigator(
    project_id: str,
    anomaly: AnomalyContract,
    *,
    grafana_settings: GrafanaSettings | None = None,
    model_settings: ModelSettings | None = None,
) -> RootCauseContract:
    """Run the Investigator once against the Sentinel's flagged anomaly."""
    grafana_settings = grafana_settings or GrafanaSettings()
    agent = build_investigator_agent(grafana_settings, model_settings)

    async with InMemoryRunner(agent=agent, app_name=INVESTIGATOR_APP_NAME) as runner:
        session = await runner.session_service.create_session(
            app_name=INVESTIGATOR_APP_NAME, user_id="reelops"
        )
        # The Sentinel's numbers are model-produced, untrusted context, not
        # ground truth — the prompt's own first evidence-sequence step is to
        # re-query this metric rather than take it on faith. The three
        # datasourceUids are, like Sentinel's, deliberately pinned and not
        # discoverable by any tool this agent holds (agents/config.py).
        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        f"project_id={project_id}\n"
                        f"prometheus_datasource_uid={grafana_settings.grafana_prom_datasource_uid}\n"
                        f"loki_datasource_uid={grafana_settings.grafana_loki_datasource_uid}\n"
                        f"tempo_datasource_uid={grafana_settings.grafana_tempo_datasource_uid}\n"
                        f"sentinel flagged: service={anomaly.service} "
                        f"signal={anomaly.signal} severity={anomaly.severity} "
                        f"current={anomaly.current} baseline={anomaly.baseline}\n"
                        "Confirm this independently before treating it as fact, "
                        "then follow the evidence sequence."
                    )
                )
            ],
        )
        async for _event in runner.run_async(
            user_id="reelops", session_id=session.id, new_message=message
        ):
            pass  # drain the run; the result lives in session state afterward

        final = await runner.session_service.get_session(
            app_name=INVESTIGATOR_APP_NAME, user_id="reelops", session_id=session.id
        )
        raw = final.state[INVESTIGATOR_OUTPUT_KEY]

    return RootCauseContract.model_validate(raw)
