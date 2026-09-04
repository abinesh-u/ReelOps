from typing import Literal, TypedDict


Severity = Literal["low", "medium", "high", "critical"]


class AnomalyContract(TypedDict):
    anomaly: bool
    severity: Severity
    service: str
    signal: str
    current: float
    baseline: float
    confidence: float


class RootCauseContract(TypedDict):
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
