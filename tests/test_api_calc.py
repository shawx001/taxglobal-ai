import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from backend.main import app, create_app


class CalcApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def default_cors_client(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TAXGLOBAL_CORS_ORIGINS", None)
            return TestClient(create_app())

    def cors_client_with_env(self, value):
        with patch.dict(os.environ, {"TAXGLOBAL_CORS_ORIGINS": value}, clear=False):
            return TestClient(create_app())

    def assert_response_has_trace_id(self, response):
        self.assertIn("X-Request-ID", response.headers)
        self.assertTrue(response.headers["X-Request-ID"])

    def assert_engine_payload(self, response):
        self.assertEqual(response.status_code, 200)
        self.assert_response_has_trace_id(response)
        body = response.json()
        self.assertIn("result", body)
        self.assertIn("rule_version", body)
        self.assertIn("citations", body)
        return body

    def test_health_returns_ok_and_request_id(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assert_response_has_trace_id(response)

    def test_local_frontend_origin_gets_cors_headers(self):
        client = self.default_cors_client()
        response = client.options(
            "/calc/federal-income",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access-control-allow-origin", response.headers)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:5173")

    def test_untrusted_origin_does_not_get_cors_allow_origin(self):
        client = self.default_cors_client()
        response = client.options(
            "/calc/federal-income",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_blank_cors_env_falls_back_to_default_dev_origins(self):
        client = self.cors_client_with_env(" , ")
        response = client.options(
            "/calc/federal-income",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:5173")

    def test_configured_cors_env_overrides_default_dev_origins(self):
        client = self.cors_client_with_env("https://app.example.com")
        allowed = client.options(
            "/calc/federal-income",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        default_dev = client.options(
            "/calc/federal-income",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers["access-control-allow-origin"], "https://app.example.com")
        self.assertNotIn("access-control-allow-origin", default_dev.headers)

    def test_calc_routes_return_engine_payloads(self):
        cases = [
            ("/calc/federal-income", {"gross_income": 120000, "filing_status": "single"}),
            ("/calc/fica", {"wages": 100000, "filing_status": "single"}),
            ("/calc/state-income", {"state_code": "FL", "taxable_income": 100000}),
            ("/calc/self-employment", {"net_self_employment_profit": 100000, "filing_status": "single"}),
            ("/calc/feie", {"foreign_earned_income": 140000, "days_abroad": 330}),
            (
                "/calc/crypto",
                {
                    "lots": [{"asset": "BTC", "date": "2023-01-10", "quantity": 1.0, "cost_basis": 20000}],
                    "disposals": [{"asset": "BTC", "date": "2025-03-01", "quantity": 1.0, "proceeds": 50000}],
                    "method": "FIFO",
                    "filing_status": "single",
                },
            ),
            (
                "/calc/rsu",
                {
                    "shares_vested": 1000,
                    "fmv_per_share": 50,
                    "vest_date": "2024-03-01",
                    "filing_status": "single",
                    "other_taxable_income": 150000,
                },
            ),
            (
                "/calc/income-summary",
                {"net_self_employment_profit": 100000, "filing_status": "single", "state_code": "CA"},
            ),
            ("/calc/nexus", {"state_code": "CA", "sales_amount": 600000}),
        ]

        for path, payload in cases:
            with self.subTest(path=path):
                response = self.client.post(path, json=payload)
                body = self.assert_engine_payload(response)
                self.assertIn(body["status"], {"ok", "not_covered"})

    def test_not_covered_state_income_is_http_200(self):
        response = self.client.post("/calc/state-income", json={"state_code": "MA", "taxable_income": 100000})

        body = self.assert_engine_payload(response)
        self.assertEqual(body["status"], "not_covered")
        self.assertIn("source_pending", body["reason"])

    def test_state_income_accepts_filing_status_for_progressive_states(self):
        response = self.client.post(
            "/calc/state-income",
            json={"state_code": "CA", "taxable_income": 125000, "filing_status": "mfj"},
        )

        body = self.assert_engine_payload(response)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["income_tax_type"], "progressive")
        self.assertEqual(body["result"]["tax"], 4768.10)

    def test_income_summary_endpoint_calculates_ca_total(self):
        response = self.client.post(
            "/calc/income-summary",
            json={"net_self_employment_profit": 100000, "filing_status": "single", "state_code": "CA"},
        )

        body = self.assert_engine_payload(response)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["total_tax"], 27311.11)
        self.assertEqual(body["result"]["state_income_tax"]["tax"], 4550.96)
        self.assertEqual(body["result"]["federal_income_tax"], 8630.60)

    def test_income_summary_endpoint_calculates_zero_tax_state(self):
        response = self.client.post(
            "/calc/income-summary",
            json={"net_self_employment_profit": 100000, "filing_status": "single", "state_code": "FL"},
        )

        body = self.assert_engine_payload(response)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["total_tax"], 22760.15)
        self.assertEqual(body["result"]["state_income_tax"]["tax"], 0.00)

    def test_income_summary_endpoint_embeds_state_not_covered(self):
        response = self.client.post(
            "/calc/income-summary",
            json={"net_self_employment_profit": 100000, "filing_status": "single", "state_code": "MA"},
        )

        body = self.assert_engine_payload(response)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["state_income_tax"]["status"], "not_covered")
        self.assertEqual(body["result"]["total_tax"], 22760.15)

    def test_crypto_endpoint_accepts_state_code(self):
        response = self.client.post(
            "/calc/crypto",
            json={
                "lots": [
                    {"asset": "BTC", "date": "2023-01-10", "quantity": 1.0, "cost_basis": 20000},
                    {"asset": "BTC", "date": "2024-06-01", "quantity": 1.0, "cost_basis": 40000},
                ],
                "disposals": [{"asset": "BTC", "date": "2025-03-01", "quantity": 1.5, "proceeds": 75000}],
                "method": "FIFO",
                "filing_status": "single",
                "other_taxable_income": 100000,
                "state_code": "CA",
            },
        )

        body = self.assert_engine_payload(response)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["state"]["tax"], 3255.00)
        self.assertEqual(body["result"]["total_tax_including_state"], 8888.00)

    def test_income_summary_invalid_filing_maps_to_422(self):
        response = self.client.post(
            "/calc/income-summary",
            json={"net_self_employment_profit": 100000, "filing_status": "bad", "state_code": "CA"},
        )

        self.assertEqual(response.status_code, 422)
        self.assert_response_has_trace_id(response)
        error = response.json()["error"]
        self.assertEqual(error["code"], "invalid_input")
        self.assertIn("Unsupported filing_status", error["message"])

    def test_engine_invalid_input_maps_to_422(self):
        response = self.client.post(
            "/calc/crypto",
            json={
                "lots": [{"asset": "BTC", "date": "2023-01-10", "quantity": 1.0, "cost_basis": 20000}],
                "disposals": [{"asset": "BTC", "date": "2025-03-01", "quantity": 2.0, "proceeds": 100000}],
                "method": "FIFO",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assert_response_has_trace_id(response)
        error = response.json()["error"]
        self.assertEqual(error["code"], "invalid_input")
        self.assertIn("exceeds", error["message"])
        self.assertEqual(error["request_id"], response.headers["X-Request-ID"])

    def test_pydantic_validation_error_maps_to_422(self):
        response = self.client.post("/calc/federal-income", json={"filing_status": "single"})

        self.assertEqual(response.status_code, 422)
        self.assert_response_has_trace_id(response)
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertEqual(error["request_id"], response.headers["X-Request-ID"])
        self.assertTrue(error["details"])

    def test_unsupported_tax_year_maps_to_422_without_500(self):
        response = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 120000, "filing_status": "single", "tax_year": 2026},
        )

        self.assertEqual(response.status_code, 422)
        self.assert_response_has_trace_id(response)
        error = response.json()["error"]
        self.assertEqual(error["code"], "unsupported_tax_year")
        self.assertIn("2026", error["message"])
        self.assertEqual(error["request_id"], response.headers["X-Request-ID"])

    def test_past_tax_year_still_uses_schema_validation_error(self):
        response = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 120000, "filing_status": "single", "tax_year": 2024},
        )

        self.assertEqual(response.status_code, 422)
        self.assert_response_has_trace_id(response)
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertEqual(error["request_id"], response.headers["X-Request-ID"])

    def test_unexpected_exception_maps_to_500_without_stack_details(self):
        test_app = create_app()

        @test_app.get("/boom")
        def boom():
            raise RuntimeError("secret internal detail")

        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/boom")

        self.assertEqual(response.status_code, 500)
        self.assert_response_has_trace_id(response)
        error = response.json()["error"]
        self.assertEqual(error["code"], "internal_error")
        self.assertEqual(error["message"], "Internal server error.")
        self.assertNotIn("secret internal detail", str(response.json()))
        self.assertEqual(error["request_id"], response.headers["X-Request-ID"])

    def test_openapi_contains_calc_routes(self):
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        expected_paths = {
            "/health",
            "/calc/federal-income",
            "/calc/fica",
            "/calc/state-income",
            "/calc/self-employment",
            "/calc/income-summary",
            "/calc/feie",
            "/calc/crypto",
            "/calc/rsu",
            "/calc/nexus",
        }
        self.assertTrue(expected_paths.issubset(paths.keys()))


if __name__ == "__main__":
    unittest.main()
