from __future__ import annotations

import json
import re
import unittest
from dataclasses import MISSING
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import create_app


def _engine_output(status: str = "ok", result: object = MISSING) -> dict:
    return {
        "status": status,
        "input": {"tax_year": 2026},
        "result": {"total_tax": "500.00", "deduction": "100.00"} if result is MISSING else result,
        "breakdown": [
            {"label": "federal_tax", "amount": "300.00"},
            {"label": "state_tax", "amount": "200.00"},
        ],
        "rule_version": "test-rule",
        "citations": [{"source_id": "irs", "citation": "test"}],
        "assumptions": [],
        "reason": None,
    }


def _skill_output(**overrides: object) -> dict:
    output = {
        "status": "ok",
        "result": _engine_output(),
        "source_attribution": "IRS / State DOR",
        "engine_function": "income_tax_summary",
    }
    output.update(overrides)
    return output


class TestEscalationModels(unittest.TestCase):
    def test_escalation_levels_serialize(self) -> None:
        from backend.guardrail.escalation import EscalationLevel

        self.assertEqual(EscalationLevel.INFO.value, "info")
        self.assertEqual(EscalationLevel.WARNING.value, "warning")
        self.assertEqual(EscalationLevel.NEEDS_REVIEW.value, "needs_review")
        self.assertEqual(EscalationLevel.BLOCKED.value, "blocked")

    def test_check_result_model(self) -> None:
        from backend.guardrail.escalation import CheckResult

        result = CheckResult(passed=False, code="missing_field", message="field is missing")

        self.assertFalse(result.passed)
        self.assertEqual(result.code, "missing_field")
        self.assertEqual(result.message, "field is missing")


class TestValidator(unittest.TestCase):
    def test_valid_skill_output_passes(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        verdict = validate_skill_output(_skill_output())

        self.assertEqual(verdict.level, EscalationLevel.INFO)
        self.assertTrue(all(check.passed for check in verdict.checks))

    def test_unknown_engine_function_blocked(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        verdict = validate_skill_output(_skill_output(engine_function="fake_function"))

        self.assertEqual(verdict.level, EscalationLevel.BLOCKED)
        self.assertIn("unknown_engine_function", {check.code for check in verdict.checks if not check.passed})

    def test_missing_envelope_field_blocked(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        output = _skill_output()
        del output["source_attribution"]
        verdict = validate_skill_output(output)

        self.assertEqual(verdict.level, EscalationLevel.BLOCKED)
        self.assertIn("missing_envelope_field", {check.code for check in verdict.checks if not check.passed})

    def test_partial_engine_output_blocked(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        verdict = validate_skill_output(_skill_output(result={"status": "ok"}))

        self.assertEqual(verdict.level, EscalationLevel.BLOCKED)
        self.assertIn("invalid_engine_output_shape", {check.code for check in verdict.checks if not check.passed})

    def test_empty_source_attribution_needs_review(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        verdict = validate_skill_output(_skill_output(source_attribution=""))

        self.assertEqual(verdict.level, EscalationLevel.NEEDS_REVIEW)
        self.assertIn("empty_source_attribution", {check.code for check in verdict.checks if not check.passed})

    def test_not_covered_with_null_result_passes(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        engine_output = _engine_output(status="not_covered", result=None)
        engine_output["breakdown"] = []
        output = _skill_output(status="not_covered", result=engine_output)
        verdict = validate_skill_output(output)

        self.assertEqual(verdict.level, EscalationLevel.INFO)

    def test_not_covered_with_amounts_blocked(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        output = _skill_output(
            status="not_covered",
            result=_engine_output(status="not_covered", result={"total_tax": "100.00"}),
        )
        verdict = validate_skill_output(output)

        self.assertEqual(verdict.level, EscalationLevel.BLOCKED)
        self.assertIn("not_covered_overridden", {check.code for check in verdict.checks if not check.passed})

    def test_not_covered_with_breakdown_amounts_blocked(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        engine_output = _engine_output(status="not_covered", result=None)
        engine_output["breakdown"] = [{"label": "fabricated", "amount": "999.99"}]
        verdict = validate_skill_output(_skill_output(status="not_covered", result=engine_output))

        self.assertEqual(verdict.level, EscalationLevel.BLOCKED)
        self.assertIn("not_covered_overridden", {check.code for check in verdict.checks if not check.passed})

    def test_mismatched_envelope_and_engine_status_blocked(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_skill_output

        output = _skill_output(status="ok", result=_engine_output(status="not_covered", result=None))
        verdict = validate_skill_output(output)

        self.assertEqual(verdict.level, EscalationLevel.BLOCKED)
        self.assertIn("status_mismatch", {check.code for check in verdict.checks if not check.passed})

    def test_extract_engine_amounts(self) -> None:
        from backend.guardrail.validator import extract_engine_amounts

        amounts = extract_engine_amounts(_engine_output())

        self.assertEqual(amounts["result.total_tax"], "500.00")
        self.assertEqual(amounts["result.deduction"], "100.00")
        self.assertEqual(amounts["breakdown.federal_tax.amount"], "300.00")
        self.assertEqual(amounts["breakdown.state_tax.amount"], "200.00")

    def test_extract_engine_amounts_from_real_float_shape(self) -> None:
        from backend.guardrail.validator import extract_engine_amounts

        amounts = extract_engine_amounts(
            {
                "status": "ok",
                "result": {"total_tax": 500.0, "deduction": 100.25},
                "breakdown": [{"label": "federal_tax", "amount": 300.0}],
            }
        )

        self.assertEqual(amounts["result.total_tax"], "500.00")
        self.assertEqual(amounts["result.deduction"], "100.25")
        self.assertEqual(amounts["breakdown.federal_tax.amount"], "300.00")

    def test_validate_amounts_match_passes(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_amounts_match

        verdict = validate_amounts_match({"claimed_total": "500.00"}, {"result.total_tax": "500.00"})

        self.assertEqual(verdict.level, EscalationLevel.INFO)

    def test_validate_amounts_match_detects_mismatch(self) -> None:
        from backend.guardrail.escalation import EscalationLevel
        from backend.guardrail.validator import validate_amounts_match

        verdict = validate_amounts_match({"claimed_total": "999.99"}, {"result.total_tax": "500.00"})

        self.assertEqual(verdict.level, EscalationLevel.BLOCKED)
        self.assertIn("amount_mismatch", {check.code for check in verdict.checks if not check.passed})


class TestCheckCoverage(unittest.TestCase):
    def test_known_topic_covered(self) -> None:
        from backend.guardrail.validator import check_coverage

        result = check_coverage("income_tax")

        self.assertTrue(result.passed)
        self.assertEqual(result.code, "covered")

    def test_unknown_topic_not_covered(self) -> None:
        from backend.guardrail.validator import check_coverage

        result = check_coverage("yacht_tax")

        self.assertFalse(result.passed)
        self.assertEqual(result.code, "topic_not_covered")

    def test_state_coverage_check(self) -> None:
        from backend.guardrail.validator import check_coverage

        self.assertTrue(check_coverage("income_tax", state_code="CA").passed)
        self.assertFalse(check_coverage("income_tax", state_code="XX").passed)


class TestEscalation(unittest.TestCase):
    def test_request_human_review_logs(self) -> None:
        from backend.guardrail.escalation import EscalationLevel, request_human_review

        with patch("backend.guardrail.escalation.logger.warning") as warning:
            marker = request_human_review(
                reason="test",
                severity=EscalationLevel.BLOCKED,
                request_id="r1",
                engine_function="income_tax_summary",
                check_code="unknown_engine_function",
            )

        warning.assert_called_once()
        payload = json.loads(warning.call_args.args[0])
        self.assertEqual(payload["event"], "guardrail_escalation")
        self.assertEqual(payload["severity"], "blocked")
        self.assertEqual(payload["request_id"], "r1")
        self.assertEqual(marker["escalation_level"], "blocked")
        self.assertEqual(marker["reason"], "test")
        self.assertEqual(marker["request_id"], "r1")

    def test_request_human_review_no_pii(self) -> None:
        from backend.guardrail.escalation import EscalationLevel, request_human_review

        with patch("backend.guardrail.escalation.logger.warning") as warning:
            request_human_review(
                reason="ssn 123-45-6789 and income mismatch 999.99 120000",
                severity=EscalationLevel.BLOCKED,
                request_id="r2",
                engine_function="ssn_income_999.99_123-45-6789_120000",
                check_code="test_123.45_120000",
            )

        logged = warning.call_args.args[0].lower()
        self.assertNotIn("ssn", logged)
        self.assertNotIn("income", logged)
        self.assertNotIn("123-45-6789", logged)
        self.assertNotIn("120000", logged)
        self.assertIsNone(re.search(r"\d+\.\d{2}", logged))


class TestGuardrailMiddleware(unittest.TestCase):
    def test_guardrail_check_passes_valid_output(self) -> None:
        from backend.guardrail.middleware import guardrail_check

        output = _skill_output()

        self.assertIs(guardrail_check(output, request_id="r1"), output)

    def test_guardrail_check_raises_on_blocked(self) -> None:
        from backend.guardrail.middleware import GuardrailViolation, guardrail_check

        with self.assertRaises(GuardrailViolation):
            guardrail_check(_skill_output(engine_function="fabricated"), request_id="r1")

    def test_guardrail_check_annotates_needs_review(self) -> None:
        from backend.guardrail.middleware import guardrail_check

        output = guardrail_check(_skill_output(source_attribution=""), request_id="r1")

        self.assertTrue(output["_guardrail"]["needs_review"])

    def test_guardrail_check_rejects_non_dict(self) -> None:
        from backend.guardrail.middleware import GuardrailViolation, guardrail_check

        with self.assertRaises(GuardrailViolation):
            guardrail_check("not a dict", request_id="r1")  # type: ignore[arg-type]

        with self.assertRaises(GuardrailViolation):
            guardrail_check(None, request_id="r2")  # type: ignore[arg-type]

    def test_guardrail_check_fail_open_on_unexpected_error(self) -> None:
        """If guardrail itself crashes, valid Skill output is returned with _guardrail.error annotation."""
        from backend.guardrail.middleware import guardrail_check

        output = _skill_output()
        with patch("backend.guardrail.middleware.validate_skill_output", side_effect=RuntimeError("bug")):
            result = guardrail_check(output, request_id="r1")

        self.assertIs(result, output)
        self.assertTrue(result["_guardrail"]["error"])

    def test_guardrail_needs_review_reason_is_sanitized(self) -> None:
        """The _guardrail annotation must not contain raw PII or amounts."""
        from backend.guardrail.middleware import guardrail_check

        output = guardrail_check(_skill_output(source_attribution=""), request_id="r1")

        reason = output["_guardrail"]["reason"]
        self.assertNotRegex(reason, r"\d+\.\d{2}")


class TestGuardrailIntegration(unittest.TestCase):
    def setUp(self) -> None:
        from backend import config

        self._config_patchers = [
            patch.object(config, "ENABLE_POSTGRES", False),
            patch.object(config, "ENABLE_NEO4J", False),
            patch.object(config, "ENABLE_CHROMA", False),
        ]
        for patcher in self._config_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.app = create_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_skill_invoke_with_guardrail_passes(self) -> None:
        response = self.client.post(
            "/api/skills/assess_feie",
            json={"foreign_earned_income": "120000", "days_abroad": 335, "tax_year": 2026},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engine_function"], "feie_estimate")

    def test_skill_invoke_guardrail_blocked(self) -> None:
        class FakeSkill:
            name = "fake"

            def invoke(self, _body: dict) -> dict:
                return _skill_output(engine_function="fabricated")

        with patch("backend.skills.routes.get_skill", return_value=FakeSkill()):
            response = self.client.post("/api/skills/fake", json={})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "guardrail_blocked")

    def test_existing_calc_routes_unaffected(self) -> None:
        response = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_existing_skill_list_unaffected(self) -> None:
        response = self.client.get("/api/skills")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 5)


if __name__ == "__main__":
    unittest.main()
