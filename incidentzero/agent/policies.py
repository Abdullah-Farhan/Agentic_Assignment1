from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from incidentzero.domain.models import RiskLevel


class RiskPolicy:
    def __init__(self, config_path: str | Path = "configs/risk_policy.json") -> None:
        self.mapping = json.loads(Path(config_path).read_text(encoding="utf-8"))

    def risk(self, tool_name: str) -> RiskLevel:
        return RiskLevel(self.mapping.get(tool_name, "critical"))

    def requires_human_approval(self, tool_name: str) -> bool:
        return self.risk(tool_name) in {RiskLevel.HIGH, RiskLevel.CRITICAL}


class ReplanPolicy:
    def should_replan(self, tool_result: dict[str, Any]) -> bool:
        """True when the last tool outcome warrants a new hypothesis or control path."""
        status = str(tool_result.get("status", "")).lower()
        if status in {"stale_precondition", "approval_denied", "validation_error", "replan_required"}:
            return True
        if status == "error" and not tool_result.get("retryable", False):
            return True
        if status == "ok":
            data = tool_result.get("data") or {}
            if isinstance(data, dict) and data.get("criteria_met") is False:
                return True
        return False


class LoopGuard:
    def __init__(self, max_same_action_repeats: int = 2) -> None:
        self.max_same_action_repeats = max_same_action_repeats
        self._counts: dict[str, int] = {}
        self._last_world_version: int | None = None

    def record(self, action_name: str, arguments: dict[str, Any], world_version: int | None = None) -> bool:
        """Return True when the exact same action has repeated too often.

        A materially new world observation resets the count so the controller can adapt
        after environment changes instead of recursively reusing stale loop counters.
        """
        if world_version is not None and self._last_world_version is not None and world_version != self._last_world_version:
            self._counts.clear()
        self._last_world_version = world_version
        canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
        fingerprint = f"{action_name}|{canonical}"
        self._counts[fingerprint] = self._counts.get(fingerprint, 0) + 1
        return self._counts[fingerprint] > self.max_same_action_repeats
