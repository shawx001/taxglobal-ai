"""PII sanitizer for audit log payloads."""

from __future__ import annotations

import copy
import re
from typing import Any

from backend.guardrail.escalation import _SSN_PATTERN

_LABELED_UNDASHED_SSN_PATTERN = re.compile(
    r"(?i)\b((?:ssn|social security(?: number)?)\s*[:#-]?\s*)(\d{9})(?!\d)"
)

_REDACT_FIELDS: frozenset[str] = frozenset(
    {
        "ssn",
        "social_security_number",
        "ein",
        "itin",
        "name",
        "first_name",
        "last_name",
        "middle_name",
        "full_name",
        "legal_name",
        "taxpayer_name",
        "spouse_name",
        "dependent_name",
        "email",
        "email_address",
        "phone",
        "phone_number",
        "address",
        "street",
        "street_address",
        "city",
        "zip_code",
        "zip",
        "postal_code",
        "date_of_birth",
        "dob",
        "birth_date",
        "bank_account",
        "account_number",
        "routing_number",
        "password",
        "token",
        "api_key",
        "secret",
    }
)

# Substrings that indicate PII in compound field names (e.g. "spouse_ssn",
# "dependent_1_email").  Checked when exact match against _REDACT_FIELDS
# misses.
_PII_SUBSTRINGS: frozenset[str] = frozenset(
    {"ssn", "ein", "itin", "email", "phone", "bank_account", "routing", "password", "token", "secret", "api_key"}
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
    lower = key.lower()
    if lower in {"ssn", "social_security_number"} or "ssn" in lower:
        return _mask_ssn_field(value) if isinstance(value, str) else "[redacted]"
    if lower in _REDACT_FIELDS:
        return "[redacted]"
    if any(token in lower for token in _PII_SUBSTRINGS):
        return "[redacted]"
    return _sanitize(value)


def _mask_ssn(text: str) -> str:
    def _dashed_replacer(match: re.Match[str]) -> str:
        digits = match.group().replace("-", "")
        return f"***-**-{digits[-4:]}"

    def _labeled_undashed_replacer(match: re.Match[str]) -> str:
        return f"{match.group(1)}***-**-{match.group(2)[-4:]}"

    masked = _SSN_PATTERN.sub(_dashed_replacer, text)
    return _LABELED_UNDASHED_SSN_PATTERN.sub(_labeled_undashed_replacer, masked)


_ALREADY_MASKED_SSN = re.compile(r"^\*{3}-\*{2}-\d{4}$")


def _mask_ssn_field(text: str) -> str:
    # Idempotency: already-masked values (***-**-1234) pass through unchanged
    # so defense-in-depth re-sanitization on read doesn't lose the last4.
    if _ALREADY_MASKED_SSN.match(text):
        return text
    normalized = text.replace("-", "")
    if normalized.isdigit() and len(normalized) == 9:
        return f"***-**-{normalized[-4:]}"
    masked = _mask_ssn(text)
    return masked if masked != text else "[redacted]"
