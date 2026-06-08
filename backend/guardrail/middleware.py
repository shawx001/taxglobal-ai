"""Guardrail middleware for post-processing Skill output."""

from __future__ import annotations

import logging
from typing import Any

from backend.guardrail.escalation import EscalationLevel, _sanitize_reason, request_human_review
from backend.guardrail.validator import validate_skill_output

logger = logging.getLogger("taxglobal.guardrail")


class GuardrailViolation(Exception):
    """Raised when guardrail blocks a Skill output."""

    def __init__(self, escalation: dict[str, Any]) -> None:
        self.escalation = escalation
        super().__init__(escalation.get("reason", "Guardrail violation"))


def guardrail_check(skill_output: dict[str, Any], request_id: str = "") -> dict[str, Any]:
    """Validate a Skill output and raise if guardrail blocks it.

    If the guardrail itself crashes (unexpected exception), the Skill output
    is returned with a ``_guardrail.error`` annotation rather than raising —
    a valid engine result is never lost due to a guardrail bug.
    """

    # Defensive: non-dict input cannot be a valid Skill envelope.
    if not isinstance(skill_output, dict):
        raise GuardrailViolation({"reason": "Skill output is not a dict.", "request_id": request_id})

    try:
        return _run_checks(skill_output, request_id)
    except GuardrailViolation:
        raise
    except Exception:
        logger.exception(
            "Guardrail check failed unexpectedly; passing Skill output unchecked (request_id=%s)",
            request_id,
        )
        skill_output["_guardrail"] = {"error": True, "reason": "Guardrail check failed; output returned unchecked."}
        return skill_output


def _run_checks(skill_output: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Core validation logic, separated for the fail-open wrapper."""

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
            "reason": _sanitize_reason(verdict.reason),
        }

    return skill_output
