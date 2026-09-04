from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    source: str
    tool: str
    summary: str
    value: Any = None


@dataclass
class IncidentState:
    incident_id: str
    project_id: str
    status: str = "new"
    severity: str = "unknown"
    anomaly: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    root_cause: dict[str, Any] = field(default_factory=dict)
    impact: dict[str, Any] = field(default_factory=dict)
    recommendation: dict[str, Any] = field(default_factory=dict)
    approval: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
