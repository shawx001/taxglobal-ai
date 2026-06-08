"""Guardrail escalation levels and audit logging."""

from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("taxglobal.guardrail")
_SSN_PATTERN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_COMMA_AMOUNT_PATTERN = re.compile(r"(?<![\d.])-?\$?\d{1,3}(?:,\d{3})+(?:\.\d{2})?(?![\d.])")
_MONEY_LIKE_PATTERN = re.compile(r"-?\d+\.\d{2}")
_LARGE_INTEGER_PATTERN = re.compile(r"(?<![\d.])-?\d{5,}(?![\d.])")
_PII_FIELD_PATTERN = re.compile(r"ssn|income", re.IGNORECASE)


class EscalationLevel(str, Enum):
    """Guardrail check severity."""

    INFO = "info"
    WARNING = "warning"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class CheckResult(BaseModel):
    """Single guardrail check outcome."""

    passed: bool
    code: str
    message: str = ""


class GuardrailVerdict(BaseModel):
    """Aggregate result of guardrail checks on one Skill output."""

    level: EscalationLevel
    checks: list[CheckResult]
    reason: str = ""


def request_human_review(
    *,
    reason: str,
    severity: EscalationLevel,
    request_id: str = "",
    engine_function: str = "",
    check_code: str = "",
) -> dict[str, Any]:
    """Log a PII-safe guardrail escalation marker."""

    safe_reason = _sanitize_reason(reason)
    safe_engine_function = _sanitize_reason(engine_function)
    safe_check_code = _sanitize_reason(check_code)
    logger.warning(
        json.dumps(
            {
                "event": "guardrail_escalation",
                "severity": severity.value,
                "reason": safe_reason,
                "request_id": request_id,
                "engine_function": safe_engine_function,
                "check_code": safe_check_code,
            },
            separators=(",", ":"),
        )
    )
    return {
        "escalation_level": severity.value,
        "reason": safe_reason,
        "request_id": request_id,
    }


def _sanitize_reason(reason: str) -> str:
    """Strip amount-like values and obvious PII field labels from audit reasons."""

    safe = _SSN_PATTERN.sub("[redacted_pii]", reason)
    safe = _COMMA_AMOUNT_PATTERN.sub("[amount]", safe)
    safe = _MONEY_LIKE_PATTERN.sub("[amount]", safe)
    safe = _LARGE_INTEGER_PATTERN.sub("[amount]", safe)
    return _PII_FIELD_PATTERN.sub("[redacted_field]", safe)
