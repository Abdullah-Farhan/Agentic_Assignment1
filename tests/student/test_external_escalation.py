from __future__ import annotations

import json

import pytest

from incidentzero.agent.controller import AgentController
from incidentzero.approval.gateway import AlwaysApproveGateway
from incidentzero.domain.models import ModelReply, ToolCall
from incidentzero.environment.engine import SimulationEnvironment
from incidentzero.model.scripted import ScriptedModelClient
from incidentzero.telemetry.budget import BudgetManager
from incidentzero.telemetry.trace import TraceRecorder
from incidentzero.tools.registry import ToolRegistry


class EvidenceDrivenExternalModel(ScriptedModelClient):
    """Choose observations from the ticket, then escalate after failed verification."""

    def __init__(self) -> None:
        super().__init__()
        self.proposals: list[str] = []

    def structured(self, messages, schema_name, schema):
        return {
            "hypothesis": "The customer-facing failure may be outside the managed platform; verify before changing service state.",
            "rationale_summary": "Observe the affected service, verify objective recovery, and escalate if local recovery is not demonstrated.",
            "steps": [
                {"step_id": "observe", "objective": "Gather current evidence from the suspected service.", "success_signal": "Fresh service evidence is available."},
                {"step_id": "verify", "objective": "Check objective recovery criteria.", "success_signal": "Verification is true or escalation is justified by evidence."},
            ],
        }

    def decide(self, messages, tools):
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        if not tool_messages:
            incident = json.loads(messages[-1]["content"].split(": ", 1)[1])
            service = incident["data"]["suspected_service"]
            call = ToolCall("health", "get_service_health", {"service": service})
        elif len(tool_messages) == 1:
            first = json.loads(tool_messages[-1]["content"])
            service = first["data"]["service"]
            call = ToolCall("logs", "get_logs", {"service": service, "limit": 10})
        elif '"tool": "verify_recovery"' not in tool_messages[-1].get("content", ""):
            call = ToolCall("verify", "verify_recovery", {})
        else:
            evidence_ids = [
                json.loads(message["content"]).get("evidence_id")
                for message in tool_messages
            ]
            evidence_ids = [evidence_id for evidence_id in evidence_ids if evidence_id]
            call = ToolCall(
                "escalate",
                "escalate_incident",
                {
                    "reason": "Objective recovery is not met and the remaining failure is outside managed local remediation.",
                    "evidence_ids": evidence_ids,
                },
            )
        self.proposals.append(call.name)
        return ModelReply(content="Evidence-based next step.", tool_calls=[call])


@pytest.mark.student
@pytest.mark.parametrize("student_id", ["DYNAMIC-2", "DYNAMIC-6", "DYNAMIC-14"])
def test_external_cases_escalate_without_internal_remediation(student_id, tmp_path):
    """External cases end safely from observations, not from a fixed success script."""
    environment = SimulationEnvironment(student_id, "hidden-external")
    registry = ToolRegistry(environment)
    incident = registry.execute("get_incident", {})
    assert "outside the managed platform" in incident["data"]["title"]

    model = EvidenceDrivenExternalModel()
    controller = AgentController(
        model=model,
        tools=registry,
        approval=AlwaysApproveGateway(),
        budget=BudgetManager(max_llm_calls=10, max_tool_calls=10),
        trace=TraceRecorder(tmp_path / f"{student_id}.jsonl"),
    )

    outcome = controller.run()

    assert outcome.status == "escalated"
    assert "verify_recovery" in model.proposals
    assert model.proposals[-1] == "escalate_incident"
    assert not {"restart_service", "scale_service", "clear_cache", "rollback_deployment"}.intersection(model.proposals)
    assert set(outcome.evidence_ids).intersection(controller.state.evidence_ids)


@pytest.mark.student
def test_escalation_without_observed_evidence_is_rejected(tmp_path):
    environment = SimulationEnvironment("DYNAMIC-2", "hidden-external")
    controller = AgentController(
        model=EvidenceDrivenExternalModel(),
        tools=ToolRegistry(environment),
        approval=AlwaysApproveGateway(),
        budget=BudgetManager(max_llm_calls=2, max_tool_calls=2),
        trace=TraceRecorder(tmp_path / "rejected.jsonl"),
    )
    call = ToolCall("escalate", "escalate_incident", {"reason": "Escalation needs observed evidence before it is safe.", "evidence_ids": ["EV-NOT-OBSERVED"]})

    result = controller._execute_tool_call(call)

    assert result["status"] == "validation_error"
    assert controller.state.status == "running"