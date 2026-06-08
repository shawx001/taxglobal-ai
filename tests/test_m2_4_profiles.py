"""M2.4 profile persistence API tests."""

from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from pydantic import ValidationError
from starlette.testclient import TestClient

from backend.main import create_app


def _profile(user_id: uuid.UUID | None = None, tax_year: int = 2026, data: dict | None = None) -> SimpleNamespace:
    now = datetime(2026, 6, 8, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        tax_year=tax_year,
        data=data or {"filing_status": "single", "state_code": "CA"},
        created_at=now,
        updated_at=now,
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class TestProfileSchemas(unittest.TestCase):
    def test_profile_create_valid(self):
        from backend.profiles.schemas import ProfileCreate

        user_id = uuid.uuid4()
        profile = ProfileCreate(user_id=user_id, tax_year=2026, data={"filing_status": "single"})

        self.assertEqual(profile.user_id, user_id)
        self.assertEqual(profile.tax_year, 2026)
        self.assertEqual(profile.data["filing_status"], "single")

    def test_profile_create_missing_data(self):
        from backend.profiles.schemas import ProfileCreate

        with self.assertRaises(ValidationError):
            ProfileCreate(user_id=uuid.uuid4(), tax_year=2026)

    def test_profile_create_extra_field_rejected(self):
        from backend.profiles.schemas import ProfileCreate

        with self.assertRaises(ValidationError):
            ProfileCreate(user_id=uuid.uuid4(), tax_year=2026, data={}, unexpected=True)


class TestProfileService(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_creates_new_profile(self):
        from backend.profiles import service

        created = _profile()
        user = SimpleNamespace(id=created.user_id)
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [_ScalarResult(None), _ScalarResult(None)]
        with (
            patch.object(service, "_new_user", return_value=user),
            patch.object(service, "_new_profile", return_value=created),
        ):
            result = await service.upsert_profile(session, created.user_id, created.tax_year, created.data)

        self.assertEqual(session.add.call_args_list, [call(user), call(created)])
        self.assertEqual(session.commit.await_count, 2)
        session.refresh.assert_awaited_once_with(created)
        self.assertIs(result, created)

    async def test_upsert_updates_existing_profile(self):
        from backend.profiles.service import upsert_profile

        existing = _profile(data={"old": True})
        session = AsyncMock()
        session.execute.return_value = _ScalarResult(existing)

        result = await upsert_profile(session, existing.user_id, existing.tax_year, {"new": True})

        session.add.assert_not_called()
        session.commit.assert_awaited_once()
        self.assertEqual(result.data, {"new": True})

    async def test_upsert_recovers_from_concurrent_user_insert_conflict(self):
        from backend.profiles import service

        user_id = uuid.uuid4()
        created = _profile(user_id=user_id, data={"new": True})
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [
            _ScalarResult(None),
            _ScalarResult(None),
            _ScalarResult(SimpleNamespace(id=user_id)),
        ]
        session.commit.side_effect = [service.IntegrityError("insert", {}, None), None]
        with (
            patch.object(service, "_new_user", return_value=SimpleNamespace(id=user_id)),
            patch.object(service, "_new_profile", return_value=created),
        ):
            result = await service.upsert_profile(session, user_id, 2026, {"new": True})

        session.rollback.assert_awaited_once()
        self.assertIs(result, created)

    async def test_upsert_recovers_from_concurrent_profile_insert_conflict(self):
        from backend.profiles import service

        user_id = uuid.uuid4()
        recovered = _profile(user_id=user_id, data={"new": True})
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [
            _ScalarResult(None),
            _ScalarResult(SimpleNamespace(id=user_id)),
            _ScalarResult(recovered),
        ]
        session.commit.side_effect = [service.IntegrityError("insert", {}, None), None]
        with patch.object(service, "_new_profile", return_value=_profile(user_id=user_id)):
            result = await service.upsert_profile(session, user_id, 2026, {"new": True})

        session.rollback.assert_awaited_once()
        self.assertEqual(result.data, {"new": True})
        self.assertIs(result, recovered)

    async def test_get_profile_by_id_found(self):
        from backend.profiles.service import get_profile_by_id

        profile = _profile()
        session = AsyncMock()
        session.execute.return_value = _ScalarResult(profile)

        result = await get_profile_by_id(session, profile.id)

        self.assertIs(result, profile)

    async def test_get_profile_by_id_not_found(self):
        from backend.profiles.service import get_profile_by_id

        session = AsyncMock()
        session.execute.return_value = _ScalarResult(None)

        result = await get_profile_by_id(session, uuid.uuid4())

        self.assertIsNone(result)

    async def test_get_profiles_by_user_orders_by_newest_tax_year(self):
        from backend.profiles.service import get_profiles_by_user

        profiles = [_profile(tax_year=2026), _profile(tax_year=2025)]
        session = AsyncMock()
        session.execute.return_value = _ScalarResult(profiles)

        result = await get_profiles_by_user(session, profiles[0].user_id)

        self.assertEqual(result, profiles)


class TestProfileRoutes(unittest.TestCase):
    def setUp(self):
        from backend import config
        from backend.profiles import routes

        self._config_patchers = [
            patch.object(config, "ENABLE_POSTGRES", False),
            patch.object(config, "ENABLE_NEO4J", False),
            patch.object(config, "ENABLE_CHROMA", False),
        ]
        for patcher in self._config_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        async def fake_session():
            yield Mock()

        self.app = create_app()
        self.app.dependency_overrides[routes.profile_session] = fake_session
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_create_profile_returns_201(self):
        profile = _profile()
        with patch("backend.profiles.routes.upsert_profile", return_value=profile):
            response = self.client.post(
                "/api/profiles",
                json={"user_id": str(profile.user_id), "tax_year": 2026, "data": profile.data},
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["id"], str(profile.id))
        self.assertEqual(body["data"], profile.data)

    def test_create_profile_missing_data_returns_422(self):
        response = self.client.post("/api/profiles", json={"user_id": str(uuid.uuid4()), "tax_year": 2026})

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("user_id", str(response.json()["error"]["details"]))

    def test_read_profile_returns_200(self):
        profile = _profile()
        with patch("backend.profiles.routes.get_profile_by_id", return_value=profile):
            response = self.client.get(f"/api/profiles/{profile.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(profile.id))

    def test_read_profile_not_found_returns_404(self):
        profile_id = uuid.uuid4()
        with patch("backend.profiles.routes.get_profile_by_id", return_value=None):
            response = self.client.get(f"/api/profiles/{profile_id}")

        self.assertEqual(response.status_code, 404)
        error = response.json()["error"]
        self.assertEqual(error["code"], "profile_not_found")
        self.assertEqual(error["request_id"], response.headers["X-Request-ID"])

    def test_read_profile_runtime_pg_failure_returns_503(self):
        from backend.profiles import service

        profile_id = uuid.uuid4()
        with patch(
            "backend.profiles.routes.get_profile_by_id",
            side_effect=service.OperationalError("select", {}, Exception("db down")),
        ):
            response = self.client.get(f"/api/profiles/{profile_id}")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "postgres_unavailable")

    def test_read_profile_integrity_error_remains_500(self):
        from backend.profiles import service

        profile_id = uuid.uuid4()
        with patch(
            "backend.profiles.routes.get_profile_by_id",
            side_effect=service.IntegrityError("select", {}, Exception("constraint")),
        ):
            response = self.client.get(f"/api/profiles/{profile_id}")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")

    def test_list_profiles_returns_200(self):
        user_id = uuid.uuid4()
        profiles = [_profile(user_id=user_id, tax_year=2026), _profile(user_id=user_id, tax_year=2025)]
        with patch("backend.profiles.routes.get_profiles_by_user", return_value=profiles):
            response = self.client.get(f"/api/profiles?user_id={user_id}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual([item["tax_year"] for item in body["profiles"]], [2026, 2025])

    def test_list_profiles_with_tax_year_filter(self):
        user_id = uuid.uuid4()
        profiles = [_profile(user_id=user_id, tax_year=2026)]
        with patch("backend.profiles.routes.get_profiles_by_user", return_value=profiles) as mock_service:
            response = self.client.get(f"/api/profiles?user_id={user_id}&tax_year=2026")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        mock_service.assert_called_once()
        call_kwargs = mock_service.call_args
        self.assertEqual(call_kwargs.args[1], user_id)
        self.assertEqual(call_kwargs.args[2], 2026)

    def test_list_profiles_runtime_pg_failure_returns_503(self):
        from backend.profiles import service

        user_id = uuid.uuid4()
        with patch(
            "backend.profiles.routes.get_profiles_by_user",
            side_effect=service.OperationalError("select", {}, Exception("db down")),
        ):
            response = self.client.get(f"/api/profiles?user_id={user_id}")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "postgres_unavailable")

    def test_list_profiles_missing_user_id_returns_422(self):
        response = self.client.get("/api/profiles")

        self.assertEqual(response.status_code, 422)


class TestProfileGracefulDegradation(unittest.TestCase):
    def test_profile_endpoint_503_when_pg_unavailable(self):
        from backend import config

        with (
            patch.object(config, "ENABLE_POSTGRES", False),
            TestClient(create_app(), raise_server_exceptions=False) as client,
        ):
            response = client.get(f"/api/profiles/{uuid.uuid4()}")

        self.assertEqual(response.status_code, 503)
        error = response.json()["error"]
        self.assertEqual(error["code"], "postgres_unavailable")

    def test_calc_endpoint_unaffected_when_pg_unavailable(self):
        from backend import config

        with (
            patch.object(config, "ENABLE_POSTGRES", False),
            TestClient(create_app(), raise_server_exceptions=False) as client,
        ):
            response = client.post(
                "/calc/federal-income",
                json={"gross_income": 120000, "filing_status": "single", "tax_year": 2026},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_search_endpoint_unaffected_when_pg_unavailable(self):
        from backend import config

        empty_search = {
            "results": [],
            "total": 0,
            "query_metadata": {"vector_hits": 0, "graph_expansions": 0, "retrieval_method": "none"},
        }
        with (
            patch.object(config, "ENABLE_POSTGRES", False),
            patch("backend.knowledge.search_routes.hybrid_search", return_value=empty_search),
            TestClient(create_app(), raise_server_exceptions=False) as client,
        ):
            response = client.get("/api/knowledge/search?q=FEIE")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
