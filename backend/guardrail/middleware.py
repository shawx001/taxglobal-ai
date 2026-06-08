"""Guardrail middleware for post-processing Skill output."""

from __future__ import annotations

from typing import Any

from backend.guardrail.escalation import EscalationLevel, request_human_review
from backend.guardrail.validator import validate_skill_output


class GuardrailViolation(Exception):
    """Raised when guardrail blocks a Skill output."""

    def __init__(self, escalation: dict[str, Any]) -> None:
        self.escalation = escalation
        super().__init__(escalation.get("reason", "Guardrail violation"))


def guardrail_check(skill_output: dict[str, Any], request_id: str = "") -> dict[str, Any]:
    """Validate a Skill output and raise if guardrail blocks it."""

    verdict = validate_skill_output(skill_output)
    engine_function = str(skill_output.get("engine_function", ""))
    failed_codes = ",".join(check.code for check in verdict.checks if not check.passed)

    if verdict.level == EscalationLevel.BLOCKED:
        escalation = request_human_review(
            reason=verdict.reason,
            severity=EscalationLevel.BLOCKED,
            request_id=request_id,
            engine_function=engine_function,
            check_code=failed_codes,
        )
        raise GuardrailViolation(escalation)

    if verdict.level == EscalationLevel.NEEDS_REVIEW:
        request_human_review(
            reason=verdict.reason,
            severity=EscalationLevel.NEEDS_REVIEW,
            request_id=request_id,
            engine_function=engine_function,
            check_code=failed_codes,
        )
        skill_output["_guardrail"] = {
            "needs_review": True,
            "reason": verdict.reason,
        }

    return skill_output
