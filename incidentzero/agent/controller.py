from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from incidentzero.approval.gateway import ApprovalGateway
from incidentzero.domain.models import AgentOutcome, ModelReply, ToolCall
from incidentzero.model.base import ModelClient
from incidentzero.model.errors import PermanentModelError, TransientModelError
from incidentzero.telemetry.budget import BudgetExceeded, BudgetManager
from incidentzero.telemetry.trace import TraceRecorder
from incidentzero.tools.registry import ToolRegistry

from .planner import Planner
from .policies import LoopGuard, ReplanPolicy, RiskPolicy
from .prompts import SYSTEM_PROMPT
from .recovery import RetryPolicy
from .state import AgentState


class AgentController:
    """Baseline controller derived from the class 'first agent' loop.

    It intentionally lacks production reliability. Your assignment is to evolve this
    controller rather than replacing it with an agent framework.
    """

    def __init__(
        self,
        model: ModelClient,
        tools: ToolRegistry,
        approval: ApprovalGateway,
        budget: BudgetManager,
        trace: TraceRecorder,
    ) -> None:
        self.model = model
        self.tools = tools
        self.approval = approval
        self.budget = budget
        self.trace = trace
        self.state = AgentState()
        self.planner = Planner(model)
        self.risk = RiskPolicy()
        self.replan_policy = ReplanPolicy()
        self.loop_guard = LoopGuard()
        self.retry_policy = RetryPolicy()

    def _model_decide(self) -> ModelReply:
        """Bounded retrial for transient model failures; each attempt counts against the LLM budget."""

        def _attempt() -> ModelReply:
            self.budget.consume_llm()
            self.state.llm_budget_used = self.budget.llm_calls
            return self.model.decide(self.state.messages, self.tools.groq_tools)

        return self.retry_policy.call_model(_attempt)

    def _execute_tool_call(self, call: ToolCall) -> dict[str, Any]:
        """Validate, approve if needed, execute, trace, and return one observation."""
        self.budget.consume_tool()
        self.state.tool_budget_used = self.budget.tool_calls

        if not isinstance(call.arguments, dict):
            return {
                "status": "validation_error", "tool": call.name,
                "world_version": self.tools.environment.world_version,
                "evidence_id": None, "data": None,
                "retryable": False, "message": "Tool arguments must be a dict.",
            }

        ok, error = self.tools.validate(call.name, call.arguments)
        if not ok:
            return {
                "status": "validation_error", "tool": call.name,
                "world_version": self.tools.environment.world_version,
                "evidence_id": None, "data": None,
                "retryable": False, "message": error,
            }

        if call.name == "close_incident":
            evidence_ids = call.arguments.get("evidence_ids") or []
            latest_verification = self.state.latest_verification_evidence_id
            if not latest_verification or latest_verification not in evidence_ids:
                return {
                    "status": "validation_error", "tool": call.name,
                    "world_version": self.tools.environment.world_version,
                    "evidence_id": None, "data": None,
                    "retryable": False,
                    "message": "close_incident requires a successful verify_recovery evidence ID in the cited list.",
                }

        if call.name == "escalate_incident":
            evidence_ids = call.arguments.get("evidence_ids") or []
            known_evidence = set(self.state.evidence_ids)
            if not evidence_ids or not set(evidence_ids).issubset(known_evidence):
                return {
                    "status": "validation_error", "tool": call.name,
                    "world_version": self.tools.environment.world_version,
                    "evidence_id": None, "data": None,
                    "retryable": False,
                    "message": "escalate_incident requires non-empty evidence_ids gathered by the controller.",
                }

        if self.risk.requires_human_approval(call.name):
            approved = self.approval.approve(
                call.name,
                call.arguments,
                call.arguments.get("reason", "Evidence-backed action requested by the controller."),
            )
            self.trace.record("approval_result", {"tool": call.name, "approved": approved, "arguments": call.arguments})
            if not approved:
                return {
                    "status": "approval_denied",
                    "tool": call.name,
                    "world_version": self.tools.environment.world_version,
                    "evidence_id": None,
                    "data": None,
                    "retryable": False,
                    "message": "Approval denied by human operator.",
                }

        result = self.tools.execute(call.name, call.arguments)
        self.trace.record("tool_result", {"call": {"name": call.name, "arguments": call.arguments}, "result": result})
        return result

    def _append_assistant(self, reply: ModelReply) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": reply.content}
        if reply.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in reply.tool_calls
            ]
        self.state.messages.append(msg)

    def _append_tool_result(self, call: ToolCall, result: dict[str, Any]) -> None:
        self.state.messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(result, ensure_ascii=False),
        })

    def _maybe_revise_plan(self, trigger: dict[str, Any]) -> None:
        if not self.state.plan:
            self.state.plan = self.planner.create({"incident": "bootstrap"})
            return
        summary = json.dumps({
            "latest_world_version": self.state.latest_world_version,
            "evidence_ids": self.state.evidence_ids,
            "last_status": trigger.get("status"),
        }, ensure_ascii=False)
        self.state.plan = self.planner.revise(self.state.plan, trigger, summary)
        self.state.plan_revision = self.state.plan.revision
        self.trace.record("plan_revised", {"trigger": trigger, "plan": asdict(self.state.plan)})

    def run(self) -> AgentOutcome:
        self.state.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Investigate the active production incident, mitigate it safely, verify recovery, then close it; otherwise escalate with evidence."},
        ]
        try:
            self.budget.consume_tool()
            incident = self.tools.execute("get_incident", {})
            self.state.observe_result(incident)
            self.trace.record("bootstrap_incident", incident)
            self.state.messages.append({"role": "system", "content": f"Current incident evidence: {json.dumps(incident)}"})

            self.budget.consume_llm()
            self.state.plan = self.planner.create(incident)
            self.state.plan_revision = self.state.plan.revision
            self.trace.record("plan_created", {"plan": asdict(self.state.plan)})

            while self.budget.remaining_llm > 0 and self.budget.remaining_tools > 0:
                reply = self._model_decide()
                self._append_assistant(reply)
                self.trace.record("model_reply", {"content": reply.content, "tool_calls": [asdict(c) for c in reply.tool_calls]})

                if not reply.tool_calls:
                    return AgentOutcome(
                        status="failed",
                        summary="Model stopped without a tool call; the controller cannot prove resolution.",
                        llm_calls=self.budget.llm_calls,
                        tool_calls=self.budget.tool_calls,
                        final_world_version=self.state.latest_world_version,
                        evidence_ids=self.state.evidence_ids,
                        trace_path=str(self.trace.path),
                    )

                call = reply.tool_calls[0]
                if self.loop_guard.record(call.name, call.arguments, self.state.latest_world_version):
                    self.trace.record("loop_detected", {"tool": call.name, "arguments": call.arguments})
                    self.state.status = "failed"
                    return AgentOutcome(
                        status="failed",
                        summary="Repeated unsafe action blocked by loop detector.",
                        llm_calls=self.budget.llm_calls,
                        tool_calls=self.budget.tool_calls,
                        final_world_version=self.state.latest_world_version,
                        evidence_ids=self.state.evidence_ids,
                        trace_path=str(self.trace.path),
                    )

                result = self._execute_tool_call(call)
                self.state.observe_result(result)
                self._append_tool_result(call, result)

                if call.name == "close_incident" and result.get("status") == "ok":
                    return AgentOutcome("resolved", "Incident closed with simulator evidence.", self.budget.llm_calls, self.budget.tool_calls, self.state.latest_world_version, self.state.evidence_ids, str(self.trace.path))
                if call.name == "escalate_incident" and result.get("status") == "ok":
                    return AgentOutcome("escalated", "Incident escalated with evidence.", self.budget.llm_calls, self.budget.tool_calls, self.state.latest_world_version, self.state.evidence_ids, str(self.trace.path))

                if self.replan_policy.should_replan(result):
                    self._maybe_revise_plan({"status": result.get("status"), "tool": call.name, "reason": result.get("message") or "evidence does not support the active plan"})
                    continue

                if result.get("status") == "ok" and call.name == "verify_recovery":
                    data = result.get("data") or {}
                    if not data.get("criteria_met"):
                        self._maybe_revise_plan({"status": "verify_failed", "tool": call.name, "reason": "Recovery criteria were not met."})
                        continue

            return AgentOutcome("budget_exhausted", "Agent budget exhausted before safe termination.", self.budget.llm_calls, self.budget.tool_calls, self.state.latest_world_version, self.state.evidence_ids, str(self.trace.path))
        except (PermanentModelError, TransientModelError) as exc:
            self.state.status = "aborted"
            self.trace.record("terminal_result", {"status": "aborted", "reason": str(exc)})
            return AgentOutcome(
                "aborted",
                f"Model request failed safely: {exc}",
                self.budget.llm_calls,
                self.budget.tool_calls,
                self.state.latest_world_version,
                self.state.evidence_ids,
                str(self.trace.path),
            )
        except BudgetExceeded as exc:
            return AgentOutcome("budget_exhausted", str(exc), self.budget.llm_calls, self.budget.tool_calls, self.state.latest_world_version, self.state.evidence_ids, str(self.trace.path))
