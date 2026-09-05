"""Offline cover for the Pydantic contracts sentinel/investigator emit.

`AnomalyContract`/`RootCauseContract` are `output_schema=` on a real
`LlmAgent`, so their JSON schema must be something Vertex's structured-output
mode can actually generate — no `Any`-typed field, which is exactly the trap
`agents/state.py`'s `Evidence.value: Any` would have been if reused here.
"""

from agents.contracts import AnomalyContract, RootCauseContract


def test_anomaly_contract_round_trips() -> None:
    payload = {
        "anomaly": True,
        "severity": "high",
        "service": "render-farm",
        "signal": "render_workers_available",
        "current": 7.0,
        "baseline": 12.0,
        "confidence": 0.82,
        "evidence": ['render_workers_available{project="x"}: observed=7 vs baseline=12'],
    }
    contract = AnomalyContract.model_validate(payload)
    assert contract.model_dump() == payload


def test_root_cause_contract_round_trips() -> None:
    payload = {
        "category": "worker_degradation",
        "service": "render-farm",
        "confidence": 0.75,
        "evidence": ["worker_timeout events observed in Loki"],
    }
    contract = RootCauseContract.model_validate(payload)
    assert contract.model_dump() == payload


def test_anomaly_contract_schema_has_no_untyped_fields() -> None:
    """A cheap regression guard: an `Any`-typed field breaks Vertex structured
    output. `additionalProperties` on the model's own schema, or a bare `{}`
    sub-schema for a property, are the shape an `Any` field takes.
    """
    schema = AnomalyContract.model_json_schema()
    for name, prop in schema["properties"].items():
        assert prop != {}, f"{name!r} has an untyped (Any-like) schema"


def test_root_cause_contract_schema_has_no_untyped_fields() -> None:
    schema = RootCauseContract.model_json_schema()
    for name, prop in schema["properties"].items():
        assert prop != {}, f"{name!r} has an untyped (Any-like) schema"
