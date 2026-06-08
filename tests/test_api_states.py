import unittest

from starlette.testclient import TestClient

from backend.main import DEFAULT_TAX_YEAR, app


class StatesApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_states_endpoint_returns_51(self):
        response = self.client.get("/api/states")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))
        body = response.json()
        self.assertEqual(body["tax_year"], DEFAULT_TAX_YEAR)
        self.assertEqual(len(body["states"]), 51)

    def test_states_have_required_fields(self):
        response = self.client.get("/api/states")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))
        states = response.json()["states"]

        for state in states:
            self.assertIn("code", state)
            self.assertIn("name", state)
            self.assertIn("income_tax_type", state)

    def test_states_sorted_by_code(self):
        response = self.client.get("/api/states")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))
        codes = [state["code"] for state in response.json()["states"]]

        self.assertEqual(codes, sorted(codes))


if __name__ == "__main__":
    unittest.main()
