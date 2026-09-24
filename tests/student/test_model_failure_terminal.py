from __future__ import annotations

import pytest

from incidentzero.agent.controller import AgentController
from incidentzero.approval.gateway import AlwaysApproveGateway
from incidentzero.model.errors import PermanentModelError
from incidentzero.model.scripted import ScriptedModelClient
from incidentzero.environment.engine import SimulationEnvironment
from incidentzero.telemetry.budget import BudgetManager
from incidentzero.telemetry.trace import TraceRecorder
from incidentzero.tools.registry import ToolRegistry


class MalformedGroqResponseModel(ScriptedModelClient):
    def decide(self, messages, tools):
        raise PermanentModelError("tool call validation failed for get_metrics<|channel|>commentary")


@pytest.mark.student
def test_malformed_provider_tool_call_aborts_without_crashing(tmp_path):
    environment = SimulationEnvironment("CLI-TEST", "public-a")
    controller = AgentController(
        model=MalformedGroqResponseModel(),
        tools=ToolRegistry(environment),
        approval=AlwaysApproveGateway(),
        budget=BudgetManager(max_llm_calls=3, max_tool_calls=5),
        trace=TraceRecorder(tmp_path / "model-failure.jsonl"),
    )

    outcome = controller.run()

    assert outcome.status == "aborted"
    assert "get_metrics<|channel|>commentary" in outcome.summary
    assert controller.state.status == "aborted"