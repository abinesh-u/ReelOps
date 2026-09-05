"""Offline cover for the six things docs/agents.md requires of every agent
prompt: role, allowed tools, evidence requirements, output schema, stop
conditions, and the bar for an unsupported claim.

Tool names are cross-checked against `agents/tool_budget.py` rather than
hardcoded, so a budget change that is not mirrored in the prompt fails here
instead of leaving an agent instructed to call a tool it no longer has.
"""

from agents.investigator.prompts import INVESTIGATOR_INSTRUCTION
from agents.sentinel.prompts import SENTINEL_INSTRUCTION
from agents.tool_budget import tools_for


def test_sentinel_prompt_names_every_budgeted_tool() -> None:
    for tool in tools_for("sentinel"):
        assert tool in SENTINEL_INSTRUCTION


def test_sentinel_prompt_names_no_tool_outside_its_budget() -> None:
    # Loki/Tempo tools must never appear — sentinel cannot call them, and the
    # prompt referencing them would invite either a rejected call or a
    # fabricated claim about evidence it never gathered.
    for forbidden in ("query_loki_logs", "query_loki_patterns", "tempo_"):
        assert forbidden not in SENTINEL_INSTRUCTION


def test_investigator_prompt_names_every_budgeted_tool() -> None:
    for tool in tools_for("investigator"):
        assert tool in INVESTIGATOR_INSTRUCTION


def test_investigator_prompt_disclaims_sift() -> None:
    assert "find_slow_requests" in INVESTIGATOR_INSTRUCTION
    assert "find_error_pattern_logs" in INVESTIGATOR_INSTRUCTION


def test_investigator_prompt_uses_histogram_quantile_not_bare_name() -> None:
    assert "histogram_quantile" in INVESTIGATOR_INSTRUCTION
    assert "render_job_duration_seconds_bucket" in INVESTIGATOR_INSTRUCTION


def test_investigator_prompt_distinguishes_project_and_service_name_labels() -> None:
    """docs/telemetry-contract.md / docs/grafana-setup.md's troubleshooting
    table: metrics label the project `project`; Loki carries `project_id` as
    structured metadata, not a stream label, so {project_id="..."} matches
    nothing — {service_name="..."} is the stream selector to use instead.
    Getting this wrong returns no data, which looks like a healthy system.
    """
    assert '{service_name="reelops-simulator"}' in INVESTIGATOR_INSTRUCTION
    assert "project_id" in INVESTIGATOR_INSTRUCTION
    assert "query_loki_patterns" in INVESTIGATOR_INSTRUCTION
    assert "bare stream selector" in INVESTIGATOR_INSTRUCTION


def test_investigator_prompt_gives_the_correct_traceql_service_attribute() -> None:
    """tests/live/test_grafana_live.py's own trace test uses
    `{resource.service.name="reelops-simulator"}` — the prompt must match it,
    or the investigator's TraceQL search fails with a parse or empty result.
    """
    assert 'resource.service.name="reelops-simulator"' in INVESTIGATOR_INSTRUCTION


def test_investigator_prompt_gives_a_stable_category_vocabulary() -> None:
    """`evals/scenarios.yaml`'s ground_truth.root_cause is `worker_degradation`
    — the prompt must offer that exact token, not leave the model to invent
    a natural-language label like "performance" that no fixed check can match.
    """
    assert "worker_degradation" in INVESTIGATOR_INSTRUCTION


def test_both_prompts_state_role_evidence_stop_and_unsupported_claim_bar() -> None:
    for instruction in (SENTINEL_INSTRUCTION, INVESTIGATOR_INSTRUCTION):
        assert "# Role" in instruction
        assert "# Evidence requirements" in instruction
        assert "# Stop conditions" in instruction
        assert "# Unsupported claims" in instruction


def test_both_prompts_treat_telemetry_as_untrusted_data() -> None:
    for instruction in (SENTINEL_INSTRUCTION, INVESTIGATOR_INSTRUCTION):
        assert "never instructions" in instruction


def test_investigator_prompt_follows_the_evidence_sequence_order() -> None:
    stages = [
        "re-confirm the anomaly metric",
        "service health",
        "log and error patterns",
        "slow renders",
        "fetch one concrete trace",
    ]
    positions = [INVESTIGATOR_INSTRUCTION.index(stage) for stage in stages]
    assert positions == sorted(positions), "evidence sequence stages are out of order"
