"""The Phase 4 gate: a real Gemini call, through ADK, with a tool and an
`output_schema` on the same agent.

Opt-in with `REELOPS_LIVE_MODEL=1`, kept separate from `REELOPS_LIVE_MCP=1` —
a Vertex-auth failure and an MCP-server failure are different dependencies,
and conflating the flags would make a failure ambiguous about which one broke.

When the flag *is* set, incomplete configuration fails rather than skips, for
the same reason `tests/live/test_grafana_live.py` does: a gate that quietly excuses
itself is the same bug as an empty series reading as a healthy system.

This test exists to settle two things before any agent code is built on top
of them:

- Vertex auth actually works from this repo. No Gemini call has ever been
  made from it before this test.
- `output_schema` and `tools` on one `LlmAgent` actually drive a tool call,
  not just a schema-valid response. The installed `google-adk==2.8.0` source
  documents the combination as supported (`LlmAgent.output_schema`'s own
  docstring, and `models/_capabilities.py::gemini_output_schema_and_tools`),
  but supported is not the same as *used*: `_output_schema_processor.py`
  itself warns the schema constraint can become "best-effort" when tools are
  configured alongside it. A model that skips the tool and fabricates a
  schema-valid answer would pass a check that only inspects the final value —
  so this test also inspects the event stream for an actual function call.
"""

import os

import pytest
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.function_tool import FunctionTool
from google.genai import types
from pydantic import BaseModel

from agents.config import ModelSettings
from tests._adk_events import called_tool

pytestmark = pytest.mark.skipif(
    os.getenv("REELOPS_LIVE_MODEL") != "1",
    reason="live gate; set REELOPS_LIVE_MODEL=1 to make a real Gemini/Vertex call",
)


def get_the_number() -> int:
    """Returns a specific number the caller needs, and cannot know otherwise."""
    return 42


class SmokeResult(BaseModel):
    answer: int


def test_live_model_settings_are_complete() -> None:
    """Fail, do not skip: the flag was set, so the operator intends to run the gate."""
    ModelSettings().require_vertex()


@pytest.mark.asyncio
async def test_output_schema_and_tools_together_actually_call_the_tool() -> None:
    settings = ModelSettings()
    settings.require_vertex()

    agent = LlmAgent(
        name="smoke_test_agent",
        model=settings.gemini_model,
        instruction=(
            "Call get_the_number to find the number, then report it as your "
            "final answer. Do not guess the number without calling the tool."
        ),
        tools=[FunctionTool(get_the_number)],
        output_schema=SmokeResult,
        output_key="smoke_result",
    )

    events = []
    async with InMemoryRunner(agent=agent, app_name="reelops-smoke") as runner:
        session = await runner.session_service.create_session(
            app_name="reelops-smoke", user_id="reelops"
        )
        message = types.Content(role="user", parts=[types.Part(text="What is the number?")])
        async for event in runner.run_async(
            user_id="reelops", session_id=session.id, new_message=message
        ):
            events.append(event)

        final = await runner.session_service.get_session(
            app_name="reelops-smoke", user_id="reelops", session_id=session.id
        )
        raw = final.state["smoke_result"]

    # Assertion 1: the final state validates against the schema.
    result = SmokeResult.model_validate(raw)
    assert result.answer == 42

    # Assertion 2, the load-bearing one: the model actually called the tool
    # rather than fabricating a schema-valid answer. A response that only
    # passes assertion 1 is exactly the silent-fabrication failure this test
    # exists to catch.
    assert called_tool(events, "get_the_number"), (
        "the final answer validated against the schema, but get_the_number was "
        "never called — the model fabricated a schema-valid response instead "
        "of using the tool. See the fallback pattern in the Phase 4 plan: drop "
        "output_schema from the tool-holding agent and add a second, tool-less "
        "agent to re-emit the result through the schema."
    )
