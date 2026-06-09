from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from backend.audit.middleware import (
    _append_limited,
    _extract_action,
    _extract_user_id,
    _request_payload,
    _response_payload,
    _should_audit,
)
from backend.audit.sanitizer import sanitize_payload
from backend.main import create_app


class AuditSanitizerTests(TestCase):
    def test_masks_ssn_values_and_redacts_pii_fields(self) -> None:
        payload = {
            "message": "Taxpayer SSN 123-45-6789 was provided.",
            "name": "Jane Taxpayer",
            "email": "jane@example.com",
            "income": 150000,
            "nested": [{"phone_number": "555-1212", "note": "spouse 987-65-4321"}],
        }

        sanitized = sanitize_payload(payload)

        self.assertEqual(sanitized["message"], "Taxpayer SSN ***-**-6789 was provided.")
        self.assertEqual(sanitized["name"], "[redacted]")
        self.assertEqual(sanitized["email"], "[redacted]")
        self.assertEqual(sanitized["income"], 150000)
        self.assertEqual(sanitized["nested"][0]["phone_number"], "[redacted]")
        self.assertEqual(sanitized["nested"][0]["note"], "spouse ***-**-4321")

    def test_does_not_mutate_original_payload(self) -> None:
        payload = {"ssn": "123-45-6789", "items": [{"taxpayer_name": "Jane"}]}

        sanitized = sanitize_payload(payload)

        self.assertEqual(payload["ssn"], "123-45-6789")
        self.assertEqual(payload["items"][0]["taxpayer_name"], "Jane")
        self.assertEqual(sanitized["ssn"], "***-**-6789")
        self.assertEqual(sanitized["items"][0]["taxpayer_name"], "[redacted]")

    def test_preserves_money_like_values(self) -> None:
        payload = {"gross_income": "$150,000.00", "long_term_capital_gain": 50000}

        sanitized = sanitize_payload(payload)

        self.assertEqual(sanitized, payload)

    def test_masks_undashed_ssn_fields_and_labeled_text(self) -> None:
        payload = {
            "ssn": "123456789",
            "note": "SSN 987654321 belongs to taxpayer.",
            "gross_income": "123456789",
        }

        sanitized = sanitize_payload(payload)

        self.assertEqual(sanitized["ssn"], "***-**-6789")
        self.assertEqual(sanitized["note"], "SSN ***-**-4321 belongs to taxpayer.")
        self.assertEqual(sanitized["gross_income"], "123456789")

    def test_redacts_compound_token_keys(self) -> None:
        payload = {"access_token": "secret-token", "refresh_token": "refresh-token"}

        sanitized = sanitize_payload(payload)

        self.assertEqual(sanitized["access_token"], "[redacted]")
        self.assertEqual(sanitized["refresh_token"], "[redacted]")


class AuditLoggerTests(IsolatedAsyncioTestCase):
    async def test_log_action_noops_when_postgres_unavailable(self) -> None:
        from backend.audit import logger as audit_logger

        with (
            patch.object(audit_logger, "is_pg_available", return_value=False),
            patch.object(audit_logger, "_write_record", new_callable=AsyncMock) as write_record,
        ):
            await audit_logger.log_action(
                request_id=str(uuid.uuid4()),
                user_id=None,
                action="skill:income_tax_summary",
                request_payload={"ssn": "123-45-6789"},
                response_payload={"name": "Jane"},
            )

        write_record.assert_not_called()

    async def test_log_action_sanitizes_before_write(self) -> None:
        from backend.audit import logger as audit_logger

        with (
            patch.object(audit_logger, "is_pg_available", return_value=True),
            patch.object(audit_logger, "_write_record", new_callable=AsyncMock) as write_record,
        ):
            await audit_logger.log_action(
                request_id=str(uuid.uuid4()),
                user_id=None,
                action="assistant:query",
                request_payload={"query": "ssn 123-45-6789", "email": "jane@example.com", "income": 150000},
                response_payload={"answer": "Use $150,000", "taxpayer_name": "Jane"},
            )

        kwargs = write_record.await_args.kwargs
        self.assertEqual(kwargs["request_payload"]["query"], "ssn ***-**-6789")
        self.assertEqual(kwargs["request_payload"]["email"], "[redacted]")
        self.assertEqual(kwargs["request_payload"]["income"], 150000)
        self.assertEqual(kwargs["response_payload"]["answer"], "Use $150,000")
        self.assertEqual(kwargs["response_payload"]["taxpayer_name"], "[redacted]")

    async def test_log_action_never_raises(self) -> None:
        from backend.audit import logger as audit_logger

        with (
            patch.object(audit_logger, "is_pg_available", return_value=True),
            patch.object(audit_logger, "_write_record", side_effect=RuntimeError("db down")),
        ):
            await audit_logger.log_action(
                request_id=str(uuid.uuid4()),
                user_id=None,
                action="tips:list",
                request_payload={},
                response_payload={},
            )

    async def test_invalid_user_id_does_not_drop_audit_write(self) -> None:
        from backend.audit import logger as audit_logger

        with (
            patch.object(audit_logger, "select", None),
            patch("backend.database._session_factory") as session_factory,
            patch("backend.models.AuditLog") as audit_log,
        ):
            session = Mock()
            session.commit = AsyncMock()
            context_manager = Mock()
            context_manager.__aenter__ = AsyncMock(return_value=session)
            context_manager.__aexit__ = AsyncMock(return_value=None)
            session_factory.return_value = context_manager
            audit_log.return_value = Mock(user_id=None)
            await audit_logger._write_record(
                request_id=str(uuid.uuid4()),
                user_id="not-a-uuid",
                action="skill:calculate_income_tax",
                request_payload={},
                response_payload={},
            )

        self.assertIsNone(audit_log.call_args.kwargs["user_id"])
        self.assertEqual(audit_log.call_args.kwargs["prev_hash"], audit_logger.GENESIS_HASH)
        self.assertEqual(len(audit_log.call_args.kwargs["entry_hash"]), 64)
        session.add.assert_called_once_with(audit_log.return_value)
        session.commit.assert_awaited_once()

    def test_compute_entry_hash_is_deterministic(self) -> None:
        from backend.audit import logger as audit_logger

        first = audit_logger._compute_entry_hash(
            request_id="r1",
            action="skill:test",
            request_payload={"amount": "100"},
            response_payload={"result": "ok"},
            prev_hash=audit_logger.GENESIS_HASH,
        )
        second = audit_logger._compute_entry_hash(
            request_id="r1",
            action="skill:test",
            request_payload={"amount": "100"},
            response_payload={"result": "ok"},
            prev_hash=audit_logger.GENESIS_HASH,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_compute_entry_hash_changes_with_prev_hash(self) -> None:
        from backend.audit import logger as audit_logger

        first = audit_logger._compute_entry_hash(
            request_id="r1",
            action="skill:test",
            request_payload={},
            response_payload={},
            prev_hash=audit_logger.GENESIS_HASH,
        )
        second = audit_logger._compute_entry_hash(
            request_id="r1",
            action="skill:test",
            request_payload={},
            response_payload={},
            prev_hash="a" * 64,
        )

        self.assertNotEqual(first, second)


class AuditMiddlewareUnitTests(TestCase):
    def test_should_audit_selected_paths_only(self) -> None:
        self.assertTrue(_should_audit("/api/skills"))
        self.assertTrue(_should_audit("/api/skills/income_tax_summary"))
        self.assertTrue(_should_audit("/api/assistant/query"))
        self.assertTrue(_should_audit("/api/tips"))
        self.assertTrue(_should_audit("/api/admin/audit"))
        self.assertFalse(_should_audit("/calc/summary"))
        self.assertFalse(_should_audit("/api/knowledge/search"))
        self.assertFalse(_should_audit("/api/profiles"))

    def test_extract_action(self) -> None:
        self.assertEqual(_extract_action("GET", "/api/skills"), "skill:list")
        self.assertEqual(_extract_action("POST", "/api/skills/income_tax_summary"), "skill:income_tax_summary")
        self.assertEqual(_extract_action("POST", "/api/assistant/query"), "assistant:query")
        self.assertEqual(_extract_action("GET", "/api/tips"), "tips:list")
        self.assertEqual(_extract_action("GET", "/api/admin/audit"), "admin:audit:list")

    def test_extract_action_trailing_slash_normalizes_to_list(self) -> None:
        self.assertEqual(_extract_action("GET", "/api/skills/"), "skill:list")
        self.assertEqual(_extract_action("GET", "/api/tips/"), "tips:list")

    def test_options_requests_are_not_audited(self) -> None:
        """CORS preflight (OPTIONS) should bypass audit entirely."""
        captured: list[dict[str, object]] = []

        def fake_schedule_log(**kwargs: object) -> None:
            captured.append(kwargs)

        app = create_app()
        client = TestClient(app)
        with patch("backend.audit.middleware._schedule_log", fake_schedule_log):
            client.options("/api/skills/calculate_income_tax")

        self.assertEqual(captured, [], "OPTIONS request should not trigger audit")

    def test_request_payload_uses_query_string_for_get(self) -> None:
        self.assertEqual(
            _request_payload("GET", b"", b"state=CA&income_types=w2&income_types=rsu"),
            {"state": "CA", "income_types": ["w2", "rsu"]},
        )

    def test_admin_audit_response_payload_is_summarized(self) -> None:
        raw = json.dumps(
            {
                "records": [
                    {"request_payload": {"ssn": "123-45-6789"}},
                    {"response_payload": {"name": "Jane"}},
                ],
                "count": 2,
            }
        ).encode()

        self.assertEqual(_response_payload("/api/admin/audit", raw), {"audit_query_count": 2})

    def test_admin_audit_error_response_payload_is_not_counted_as_none(self) -> None:
        raw = json.dumps({"error": {"code": "admin_forbidden"}}).encode()

        self.assertEqual(_response_payload("/api/admin/audit", raw), {"error": {"code": "admin_forbidden"}})

    def test_append_limited_truncates_to_remaining_budget(self) -> None:
        chunks = [b"a" * 65_530]

        new_size = _append_limited(chunks, 65_530, b"b" * 20)

        self.assertEqual(new_size, 65_536)
        self.assertEqual(len(b"".join(chunks)), 65_536)
        self.assertEqual(chunks[-1], b"b" * 6)

    def test_admin_audit_user_id_filter_not_extracted_as_actor(self) -> None:
        """user_id in /api/admin/audit query is a search filter, not the acting user."""
        payload = {"user_id": "d3f1a2b4-5678-4c9e-a012-3456789abcde", "action": "skill:income_tax_summary"}
        self.assertIsNone(_extract_user_id(payload, "/api/admin/audit"))

    def test_extract_user_id_works_for_non_admin_paths(self) -> None:
        uid = "d3f1a2b4-5678-4c9e-a012-3456789abcde"
        payload = {"user_id": uid}
        self.assertEqual(_extract_user_id(payload, "/api/skills/calc"), uid)


class AuditRouteIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.client = TestClient(self.app)

    def test_audited_skill_route_still_reads_request_body(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_schedule_log(**kwargs: object) -> None:
            captured.append(kwargs)

        with patch("backend.audit.middleware._schedule_log", fake_schedule_log):
            response = self.client.post(
                "/api/skills/calculate_income_tax",
                json={"w2_wages": 100000, "filing_status": "single", "tax_year": 2026},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response.headers)
        request_body = json.loads(captured[0]["request_body"])
        response_body = json.loads(captured[0]["response_body"])
        self.assertEqual(captured[0]["path"], "/api/skills/calculate_income_tax")
        self.assertEqual(request_body["w2_wages"], 100000)
        self.assertIn("result", response_body)

    def test_calc_route_is_not_audited(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_schedule_log(**kwargs: object) -> None:
            captured.append(kwargs)

        with patch("backend.audit.middleware._schedule_log", fake_schedule_log):
            response = self.client.post("/calc/income-summary", json={"w2_wages": 100000, "filing_status": "single"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured, [])

    def test_tips_query_params_are_captured(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_schedule_log(**kwargs: object) -> None:
            captured.append(kwargs)

        with patch("backend.audit.middleware._schedule_log", fake_schedule_log):
            response = self.client.get("/api/tips", params={"state": "CA", "income_types": "w2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured[0]["method"], "GET")
        self.assertEqual(captured[0]["path"], "/api/tips")
        self.assertIn(b"state=CA", captured[0]["query_string"])
        self.assertIn(b"income_types=w2", captured[0]["query_string"])

    def test_admin_audit_503_when_postgres_unavailable(self) -> None:
        with (
            patch.dict("os.environ", {"TAXGLOBAL_ADMIN_AUDIT_TOKEN": "test-token"}),
            patch("backend.audit.routes.is_pg_available", return_value=False),
            patch("backend.audit.middleware._schedule_log", lambda **kwargs: None),
        ):
            response = self.client.get("/api/admin/audit", headers={"X-Admin-Token": "test-token"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "postgres_unavailable")
        self.assertIn("X-Request-ID", response.headers)


class AuditAdminRouteTests(TestCase):
    def test_admin_audit_requires_configured_token(self) -> None:
        app = create_app()
        client = TestClient(app)

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("backend.audit.middleware._schedule_log", lambda **kwargs: None),
        ):
            response = client.get("/api/admin/audit")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "admin_audit_auth_not_configured")

    def test_admin_audit_rejects_bad_token(self) -> None:
        app = create_app()
        client = TestClient(app)

        with (
            patch.dict("os.environ", {"TAXGLOBAL_ADMIN_AUDIT_TOKEN": "test-token"}),
            patch("backend.audit.middleware._schedule_log", lambda **kwargs: None),
        ):
            response = client.get("/api/admin/audit", headers={"X-Admin-Token": "wrong"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "admin_forbidden")

    def test_admin_audit_serializes_records(self) -> None:
        from backend.audit import routes as audit_routes

        request_id = uuid.uuid4()
        user_id = uuid.uuid4()
        created_at = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
        record = Mock(
            id=42,
            request_id=request_id,
            user_id=user_id,
            action="skill:income_tax_summary",
            request_payload={"income": 150000},
            response_payload={"total_tax": "40000.00"},
            created_at=created_at,
        )
        self.assertEqual(
            audit_routes._serialize_record(record),
            {
                "id": 42,
                "request_id": str(request_id),
                "user_id": str(user_id),
                "action": "skill:income_tax_summary",
                "request_payload": {"income": 150000},
                "response_payload": {"total_tax": "40000.00"},
                "created_at": created_at.isoformat(),
            },
        )

    def test_admin_audit_rejects_invalid_date_filter(self) -> None:
        from backend.audit import routes as audit_routes

        app = create_app()
        client = TestClient(app)

        with (
            patch.dict("os.environ", {"TAXGLOBAL_ADMIN_AUDIT_TOKEN": "test-token"}),
            patch.object(audit_routes, "is_pg_available", return_value=True),
            patch("backend.audit.middleware._schedule_log", lambda **kwargs: None),
        ):
            response = client.get(
                "/api/admin/audit",
                params={"from": "not-a-date"},
                headers={"X-Admin-Token": "test-token"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_date_filter")

    def test_admin_audit_accepts_utc_z_date_filter(self) -> None:
        from backend.audit import routes as audit_routes

        parsed = audit_routes._parse_date("2026-06-09T12:00:00Z")

        self.assertEqual(parsed, datetime(2026, 6, 9, 12, 0, tzinfo=UTC))

    def test_verify_records_detects_valid_chain(self) -> None:
        from backend.audit import logger as audit_logger
        from backend.audit import routes as audit_routes

        first_hash = audit_logger._compute_entry_hash(
            request_id="r1",
            action="skill:a",
            request_payload={},
            response_payload={},
            prev_hash=audit_logger.GENESIS_HASH,
        )
        second_hash = audit_logger._compute_entry_hash(
            request_id="r2",
            action="skill:b",
            request_payload={},
            response_payload={},
            prev_hash=first_hash,
        )
        records = [
            Mock(
                id=1,
                request_id="r1",
                action="skill:a",
                request_payload={},
                response_payload={},
                prev_hash=audit_logger.GENESIS_HASH,
                entry_hash=first_hash,
            ),
            Mock(
                id=2,
                request_id="r2",
                action="skill:b",
                request_payload={},
                response_payload={},
                prev_hash=first_hash,
                entry_hash=second_hash,
            ),
        ]

        result = audit_routes._verify_records(records)
        self.assertEqual(
            result, {"status": "ok", "verified": 2, "skipped_legacy": 0, "broken_at": None},
        )

    def test_verify_records_detects_broken_chain(self) -> None:
        from backend.audit import logger as audit_logger
        from backend.audit import routes as audit_routes

        first_hash = audit_logger._compute_entry_hash(
            request_id="r1",
            action="skill:a",
            request_payload={},
            response_payload={},
            prev_hash=audit_logger.GENESIS_HASH,
        )
        records = [
            Mock(
                id=1,
                request_id="r1",
                action="skill:a",
                request_payload={},
                response_payload={},
                prev_hash=audit_logger.GENESIS_HASH,
                entry_hash=first_hash,
            ),
            Mock(
                id=2,
                request_id="r2",
                action="skill:b",
                request_payload={},
                response_payload={},
                prev_hash="bad",
                entry_hash="bad",
            ),
        ]

        self.assertEqual(audit_routes._verify_records(records), {"status": "tampered", "verified": 1, "broken_at": 2})

    def test_verify_records_skips_legacy_rows_without_entry_hash(self) -> None:
        """Legacy rows (before hash-chain migration) have NULL entry_hash — they
        should be skipped as unverifiable, not falsely flagged as tampered."""
        from backend.audit import logger as audit_logger
        from backend.audit import routes as audit_routes

        hashed_entry = audit_logger._compute_entry_hash(
            request_id="r2",
            action="skill:b",
            request_payload={},
            response_payload={},
            prev_hash=audit_logger.GENESIS_HASH,
        )
        records = [
            Mock(id=1, request_id="r1", action="skill:a",
                 request_payload={}, response_payload={},
                 prev_hash=None, entry_hash=None),  # legacy row
            Mock(id=2, request_id="r2", action="skill:b",
                 request_payload={}, response_payload={},
                 prev_hash=audit_logger.GENESIS_HASH,
                 entry_hash=hashed_entry),
        ]

        result = audit_routes._verify_records(records)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["verified"], 1)
        self.assertEqual(result["skipped_legacy"], 1)
        self.assertIsNone(result["broken_at"])
