"""PII sanitizer for audit log payloads."""

from __future__ import annotations

import copy
import re
from typing import Any

from backend.guardrail.escalation import _SSN_PATTERN

_REDACT_FIELDS: frozenset[str] = frozenset(
    {
        "ssn",
        "social_security_number",
        "ein",
        "name",
        "first_name",
        "last_name",
        "taxpayer_name",
        "spouse_name",
        "email",
        "email_address",
        "phone",
        "phone_number",
        "address",
        "street",
        "street_address",
    }
)


def sanitize_payload(data: Any) -> Any:
    """Return a deep copy of *data* with PII fields and SSN values masked."""

    if data is None:
        return None
    return _sanitize(copy.deepcopy(data))


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: _sanitize_value(str(key), value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    if isinstance(obj, str):
        return _mask_ssn(obj)
    return obj


def _sanitize_value(key: str, value: Any) -> Any:
    if key.lower() in _REDACT_FIELDS:
        return "[redacted]"
    return _sanitize(value)


def _mask_ssn(text: str) -> str:
    def _replacer(match: re.Match[str]) -> str:
        digits = match.group().replace("-", "")
        return f"***-**-{digits[-4:]}"

    return _SSN_PATTERN.sub(_replacer, text)
