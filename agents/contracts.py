from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]


class AnomalyContract(BaseModel):
    """Sentinel's output. A Pydantic model, not a TypedDict: ADK's `output_schema`
    requires one — see `agents/sentinel/agent.py`.
    """

    anomaly: bool
    severity: Severity
    service: str
    signal: str
    current: float
    baseline: float
    confidence: float
    evidence: list[str] = Field(
        description="One entry per query that supports this verdict, formatted as "
        "'<PromQL expr>: observed=<value> vs baseline=<value>'."
    )


class RootCauseContract(BaseModel):
    """Investigator's output. A Pydantic model for the same reason as `AnomalyContract`."""

    category: str
    service: str
    confidence: float
    evidence: list[str]


class ImpactContract(TypedDict):
    affected_entities: list[str]
    deadline: str
    predicted_delay_minutes: float
    downstream_stages: list[str]
    risk_level: Severity


class RecommendationContract(TypedDict):
    action_type: str
    target: str
    rationale: str
    requires_human_approval: bool
