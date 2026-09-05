"""Shared helper for live agent tests: did the model actually call a tool?

Leading underscore so pytest does not collect this as a test module.

A schema-valid final answer is not proof the model did any work — it could
have fabricated a value that happens to satisfy the schema. The live tests
that use this helper assert against the event stream, not just the final
state, to catch that failure mode.
"""

from collections.abc import Iterable

from google.adk.events.event import Event


def called_tool(events: Iterable[Event], name: str) -> bool:
    """True if any event in the run carries a function call named `name`."""
    return any(call.name == name for event in events for call in event.get_function_calls())
