import unittest

from starlette.testclient import TestClient

from backend.main import app


class StatesApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_states_endpoint_returns_51(self):
        response = self.client.get("/api/states")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["tax_year"], 2026)
        self.assertEqual(len(body["states"]), 51)

    def test_states_have_required_fields(self):
        response = self.client.get("/api/states")
        states = response.json()["states"]

        for state in states:
            self.assertIn("code", state)
            self.assertIn("name", state)
            self.assertIn("income_tax_type", state)

    def test_states_sorted_by_code(self):
        response = self.client.get("/api/states")
        codes = [state["code"] for state in response.json()["states"]]

        self.assertEqual(codes, sorted(codes))


if __name__ == "__main__":
    unittest.main()
