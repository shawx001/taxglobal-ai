"""Pure validation functions for Skill output guardrail checks."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from backend.guardrail.escalation import CheckResult, EscalationLevel, GuardrailVerdict
from engine.rules_loader import RuleLoadError, load_rule_file

KNOWN_ENGINE_FUNCTIONS: frozenset[str] = frozenset(
    {
        "income_tax_summary",
        "feie_estimate",
        "rsu_tax_estimate",
        "crypto_gain_estimate",
        "nexus_estimate",
    }
)

TOPIC_SKILL_MAP: dict[str, str] = {
    "income_tax": "calculate_income_tax",
    "feie": "assess_feie",
    "rsu": "analyze_rsu",
    "crypto": "track_crypto",
    "nexus": "detect_nexus",
}

_REQUIRED_ENVELOPE_KEYS = frozenset({"status", "result", "source_attribution", "engine_function"})
_REQUIRED_ENGINE_OUTPUT_KEYS = frozenset(
    {"status", "input", "result", "breakdown", "rule_version", "citations", "assumptions", "reason"}
)
_MONEY_PATTERN = re.compile(r"^-?\d+\.\d{2}$")
_NEEDS_REVIEW_CODES = frozenset({"empty_source_attribution"})


def validate_skill_output(skill_output: dict[str, Any]) -> GuardrailVerdict:
    """Run all guardrail checks on a Skill output envelope."""

    checks = [
        _check_envelope_structure(skill_output),
        _check_status_consistency(skill_output),
        _check_engine_function_known(skill_output),
        _check_source_attribution(skill_output),
        _check_not_covered_integrity(skill_output),
    ]
    failed = [check for check in checks if not check.passed]
    if not failed:
        return GuardrailVerdict(level=EscalationLevel.INFO, checks=checks, reason="All checks passed.")

    reason = "; ".join(check.message for check in failed)
    if all(check.code in _NEEDS_REVIEW_CODES for check in failed):
        return GuardrailVerdict(level=EscalationLevel.NEEDS_REVIEW, checks=checks, reason=reason)
    return GuardrailVerdict(level=EscalationLevel.BLOCKED, checks=checks, reason=reason)


def _check_envelope_structure(output: dict[str, Any]) -> CheckResult:
    missing = sorted(key for key in _REQUIRED_ENVELOPE_KEYS if key not in output)
    if missing:
        return CheckResult(
            passed=False,
            code="missing_envelope_field",
            message=f"Skill output missing required envelope field(s): {', '.join(missing)}",
        )
    if not isinstance(output.get("result"), dict):
        return CheckResult(
            passed=False,
            code="invalid_result_envelope",
            message="Skill output result must be an engine output object.",
        )
    engine_output = output["result"]
    missing_engine_keys = sorted(key for key in _REQUIRED_ENGINE_OUTPUT_KEYS if key not in engine_output)
    if missing_engine_keys:
        return CheckResult(
            passed=False,
            code="invalid_engine_output_shape",
            message=f"Engine output missing required field(s): {', '.join(missing_engine_keys)}",
        )
    return CheckResult(passed=True, code="envelope_structure_ok")


def _check_status_consistency(output: dict[str, Any]) -> CheckResult:
    engine_output = output.get("result")
    if not isinstance(engine_output, dict):
        return CheckResult(passed=True, code="status_consistency_skipped")
    envelope_status = output.get("status")
    engine_status = engine_output.get("status")
    if envelope_status != engine_status:
        return CheckResult(
            passed=False,
            code="status_mismatch",
            message=f"Skill envelope status {envelope_status!r} does not match engine status {engine_status!r}.",
        )
    return CheckResult(passed=True, code="status_consistency_ok")


def _check_engine_function_known(output: dict[str, Any]) -> CheckResult:
    engine_function = output.get("engine_function")
    # Guard against unhashable types (list/dict) which would raise TypeError
    # on frozenset membership check, triggering fail-open bypass.
    if not isinstance(engine_function, str):
        return CheckResult(
            passed=False,
            code="unknown_engine_function",
            message="engine_function must be a string.",
        )
    if engine_function not in KNOWN_ENGINE_FUNCTIONS:
        return CheckResult(
            passed=False,
            code="unknown_engine_function",
            message=f"Unknown engine function: {engine_function!r}",
        )
    return CheckResult(passed=True, code="engine_function_known")


def _check_source_attribution(output: dict[str, Any]) -> CheckResult:
    source_attribution = output.get("source_attribution")
    if not isinstance(source_attribution, str) or not source_attribution.strip():
        return CheckResult(
            passed=False,
            code="empty_source_attribution",
            message="Skill output has empty source attribution.",
        )
    return CheckResult(passed=True, code="source_attribution_present")


def _check_not_covered_integrity(output: dict[str, Any]) -> CheckResult:
    if output.get("status") != "not_covered":
        return CheckResult(passed=True, code="not_covered_integrity_ok")

    engine_output = output.get("result")
    if not isinstance(engine_output, dict):
        return CheckResult(
            passed=False,
            code="not_covered_invalid_result",
            message="not_covered Skill output must contain an engine output object.",
        )
    if engine_output.get("result") is not None:
        return CheckResult(
            passed=False,
            code="not_covered_overridden",
            message="not_covered engine output cannot contain computed result amounts.",
        )
    if extract_engine_amounts(engine_output):
        return CheckResult(
            passed=False,
            code="not_covered_overridden",
            message="not_covered engine output cannot contain monetary breakdown amounts.",
        )
    return CheckResult(passed=True, code="not_covered_integrity_ok")


def extract_engine_amounts(engine_output: dict[str, Any]) -> dict[str, str]:
    """Extract engine monetary strings from result and breakdown sections."""

    amounts: dict[str, str] = {}
    result = engine_output.get("result")
    if isinstance(result, dict):
        _extract_money_values(result, "result", amounts)

    breakdown = engine_output.get("breakdown")
    if isinstance(breakdown, list):
        for index, item in enumerate(breakdown):
            if isinstance(item, dict):
                label = item.get("label")
                safe_label = str(label) if isinstance(label, str) and label else str(index)
                _extract_money_values(item, f"breakdown.{safe_label}", amounts)
    return amounts


def _extract_money_values(value: Any, path: str, amounts: dict[str, str]) -> None:
    if isinstance(value, str) and _MONEY_PATTERN.match(value):
        amounts[path] = value
        return
    if isinstance(value, int | float | Decimal) and not isinstance(value, bool):
        normalized = _normalize_money_value(value)
        if normalized is not None:
            amounts[path] = normalized
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _extract_money_values(item, f"{path}.{key}", amounts)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _extract_money_values(item, f"{path}.{index}", amounts)


def _normalize_money_value(value: int | float | Decimal) -> str | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite():
        return None
    return str(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def validate_amounts_match(claimed: dict[str, str], engine_amounts: dict[str, str]) -> GuardrailVerdict:
    """Verify every claimed monetary amount exists in the engine amount reference set."""

    engine_values = set(engine_amounts.values())
    checks: list[CheckResult] = []
    for field, amount in claimed.items():
        if amount in engine_values:
            checks.append(CheckResult(passed=True, code="amount_match", message=f"{field} matches engine output."))
        else:
            # Never embed raw dollar amounts in messages (PII-safety).
            checks.append(
                CheckResult(
                    passed=False,
                    code="amount_mismatch",
                    message=f"{field} does not match any engine amount (mismatch detected).",
                )
            )

    if any(not check.passed for check in checks):
        reason = "; ".join(check.message for check in checks if not check.passed)
        return GuardrailVerdict(level=EscalationLevel.BLOCKED, checks=checks, reason=reason)
    return GuardrailVerdict(level=EscalationLevel.INFO, checks=checks, reason="All claimed amounts match.")


def check_coverage(topic: str, state_code: str | None = None, tax_year: int = 2026) -> CheckResult:
    """Check whether a topic and optional state are covered by the current engine-backed Skills."""

    if topic not in TOPIC_SKILL_MAP:
        return CheckResult(
            passed=False,
            code="topic_not_covered",
            message=f"Topic {topic!r} is not mapped to an engine Skill.",
        )

    if state_code is None:
        return CheckResult(passed=True, code="covered", message=f"Topic {topic!r} is covered.")

    code = state_code.upper()
    try:
        states_data = load_rule_file(tax_year, "us_states.json")
    except RuleLoadError:
        return CheckResult(
            passed=False,
            code="tax_year_not_covered",
            message=f"Tax year {tax_year} state rules are not available.",
        )

    states = states_data.get("states", {})
    if isinstance(states, Mapping) and code in states:
        return CheckResult(passed=True, code="covered", message=f"Topic {topic!r} and state {code} are covered.")
    return CheckResult(
        passed=False,
        code="state_not_covered",
        message=f"State {code} is not present in tax-year {tax_year} state rules.",
    )
