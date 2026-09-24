from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from incidentzero.domain.models import AgentPlan


@dataclass
class AgentState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    plan: AgentPlan | None = None
    plan_revision: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    latest_world_version: int | None = None
    last_tool_results: list[dict[str, Any]] = field(default_factory=list)
    repeated_actions: dict[str, int] = field(default_factory=dict)
    action_fingerprints: dict[str, int] = field(default_factory=dict)
    status: str = "running"
    pending_action: dict[str, Any] | None = None
    approval_denials: list[str] = field(default_factory=list)
    stale_events: list[dict[str, Any]] = field(default_factory=list)
    latest_verification_evidence_id: str | None = None
    hypothesis_history: list[str] = field(default_factory=list)
    llm_budget_used: int = 0
    tool_budget_used: int = 0

    def observe_result(self, result: dict[str, Any]) -> None:
        evidence = result.get("evidence_id")
        if evidence:
            self.evidence_ids.append(evidence)
        version = result.get("world_version")
        if isinstance(version, int):
            self.latest_world_version = version
        if result.get("status") == "stale_precondition":
            self.stale_events.append({"status": result.get("status"), "tool": result.get("tool"), "world_version": version})
        if result.get("status") == "approval_denied":
            self.approval_denials.append(str(result.get("tool") or "unknown_tool"))
        if result.get("status") == "ok" and result.get("tool") == "verify_recovery":
            data = result.get("data") or {}
            if isinstance(data, dict) and data.get("criteria_met"):
                self.latest_verification_evidence_id = evidence
        self.last_tool_results.append(result)
        self.last_tool_results = self.last_tool_results[-8:]
