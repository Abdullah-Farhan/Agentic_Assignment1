from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

from incidentzero.domain.models import AgentPlan, PlanStep
from incidentzero.model.base import ModelClient


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "hypothesis": {"type": "string"},
        "rationale_summary": {"type": "string"},
        "steps": {
            "type": "array",
            "minItems": 2,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "objective": {"type": "string"},
                    "success_signal": {"type": "string"},
                },
                "required": ["step_id", "objective", "success_signal"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["hypothesis", "rationale_summary", "steps"],
    "additionalProperties": False,
}


class Planner:
    def __init__(self, model: ModelClient) -> None:
        self.model = model

    def _fallback_plan(self, incident_observation: dict[str, Any]) -> AgentPlan:
        service = (incident_observation or {}).get("suspected_service") or "checkout-service"
        return AgentPlan(
            hypothesis=f"The incident appears to be caused by a service or dependency issue around {service}; we will validate the diagnosis with evidence before changing production state.",
            steps=[
                PlanStep(step_id="S1", objective=f"Observe {service} health, metrics, and recent deploy history.", success_signal="Relevant evidence has been gathered for the service and dependency path."),
                PlanStep(step_id="S2", objective="Test the leading hypothesis against the current evidence and choose the least risky action.", success_signal="The chosen action is supported by fresh evidence and a clear expected effect."),
                PlanStep(step_id="S3", objective="Verify recovery with objective checks before closure or escalation.", success_signal="verify_recovery reports criteria_met=true or the incident is escalated with evidence."),
            ],
            revision=0,
            rationale_summary="Fallback plan used because the model failed to return a valid structured plan.",
        )

    def _validate_raw_plan(self, raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        if not isinstance(raw.get("steps"), list) or len(raw["steps"]) < 2:
            return False
        try:
            Draft202012Validator(PLAN_SCHEMA).validate(raw)
            return True
        except Exception:
            return False

    def create(self, incident_observation: dict[str, Any], context: list[dict[str, Any]] | None = None) -> AgentPlan:
        """Create an explicit initial plan using Groq when valid, else a safe fallback."""
        messages = [
            {"role": "system", "content": "Create a short SRE investigation-and-remediation plan. Do not assume the ticket's suspected root cause is correct."},
            {"role": "user", "content": f"Incident observation: {incident_observation}"},
        ]
        try:
            raw = self.model.structured(messages, "incident_plan", PLAN_SCHEMA)
        except Exception:
            return self._fallback_plan(incident_observation)
        if not self._validate_raw_plan(raw):
            return self._fallback_plan(incident_observation)

        steps = [PlanStep(**row) for row in raw["steps"]]
        return AgentPlan(hypothesis=raw["hypothesis"], steps=steps, rationale_summary=raw["rationale_summary"])

    def revise(self, current: AgentPlan, trigger: dict[str, Any], state_summary: str) -> AgentPlan:
        """Create a grounded revision without discarding completed evidence."""
        trigger_text = trigger.get("reason") or trigger.get("status") or "new evidence"
        revised_steps = []
        for step in current.steps:
            revised_steps.append(PlanStep(
                step_id=step.step_id,
                objective=step.objective,
                success_signal=step.success_signal,
                status=step.status,
            ))

        revised_steps[-1] = PlanStep(
            step_id=revised_steps[-1].step_id,
            objective=revised_steps[-1].objective,
            success_signal="Verify recovery with objective criteria before closure or escalation.",
            status="pending",
        )

        new_hypothesis = (
            f"The previous hypothesis was insufficient: {trigger_text}. "
            "We will gather fresh evidence, validate the active hypothesis, and only continue if the evidence supports it."
        )
        return AgentPlan(
            hypothesis=new_hypothesis,
            steps=revised_steps,
            revision=current.revision + 1,
            rationale_summary=(current.rationale_summary or "Revised based on new evidence")
            + f" | trigger={trigger_text} | state={state_summary}",
        )
