import pytest

from incidentzero.agent.controller import AgentController
from incidentzero.approval.gateway import AlwaysApproveGateway, AlwaysDenyGateway
from incidentzero.environment.engine import SimulationEnvironment
from incidentzero.model.scripted import ScriptedModelClient
from incidentzero.telemetry.budget import BudgetManager
from incidentzero.telemetry.trace import TraceRecorder
from incidentzero.tools.registry import ToolRegistry


@pytest.fixture
def controller_factory(tmp_path):
    def build(model_decisions=None, structured_outputs=None, approval=AlwaysApproveGateway()):
        env = SimulationEnvironment("STUDENT-TEST", "public-a")
        registry = ToolRegistry(env)
        trace = TraceRecorder(tmp_path / "trace.jsonl")
        model = ScriptedModelClient(decisions=model_decisions, structured_outputs=structured_outputs)
        return AgentController(model=model, tools=registry, approval=approval, budget=BudgetManager(max_llm_calls=10, max_tool_calls=10), trace=trace)
    return build


@pytest.mark.student
def test_controller_rejects_close_without_verify_evidence(controller_factory):
    model = ScriptedModelClient(decisions=[])
    env = SimulationEnvironment("STUDENT-TEST", "public-a")
    registry = ToolRegistry(env)
    trace = TraceRecorder("traces/test_close_reject.jsonl")
    controller = AgentController(model=model, tools=registry, approval=AlwaysApproveGateway(), budget=BudgetManager(max_llm_calls=5, max_tool_calls=5), trace=trace)

    result = controller._execute_tool_call(type("C", (), {"name": "close_incident", "arguments": {"summary": "This is a long enough summary for close.", "evidence_ids": ["EV-0001"], "expected_world_version": env.world_version, "reason": "Need close evidence"}})())
    assert result["status"] == "validation_error"


@pytest.mark.student
def test_controller_denied_approval_is_recorded(controller_factory):
    controller = controller_factory(approval=AlwaysDenyGateway())
    result = controller._execute_tool_call(type("C", (), {"name": "rollback_deployment", "arguments": {"service": "checkout-service", "target_version": "v2", "expected_world_version": controller.tools.environment.world_version, "reason": "Evidence says rollback is reasonable."}})())
    assert result["status"] == "approval_denied"


@pytest.mark.student
def test_loop_guard_resets_after_world_change():
    from incidentzero.agent.policies import LoopGuard
    guard = LoopGuard(max_same_action_repeats=1)
    assert guard.record("restart_service", {"service": "auth-service"}, 1) is False
    assert guard.record("restart_service", {"service": "auth-service"}, 1) is True
    assert guard.record("restart_service", {"service": "auth-service"}, 2) is False
