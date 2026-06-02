import json
import unittest
from pathlib import Path

import engine

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"

EXPECTED_RESPONSE_KEYS = {
    "status",
    "input",
    "result",
    "breakdown",
    "rule_version",
    "citations",
    "assumptions",
    "reason",
}

META_EXPECTED_KEYS = {"status", "reason_contains", "citation_source_ids"}


def load_golden_files():
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8-sig") as handle:
            yield path.name, json.load(handle)


class GoldenFixtureTests(unittest.TestCase):
    def test_golden_cases_match_engine_outputs(self):
        for file_name, fixture in load_golden_files():
            function_name = fixture["function"]
            target = getattr(engine, function_name)

            for case in fixture["cases"]:
                with self.subTest(file=file_name, function=function_name, name=case["name"]):
                    result = target(**case["input"])
                    self.assertEqual(set(result.keys()), EXPECTED_RESPONSE_KEYS)
                    self.assert_golden_result(case["expected"], result)

    def assert_golden_result(self, expected, result):
        self.assertEqual(result["status"], expected["status"])

        if expected["status"] == "not_covered":
            self.assertIsNone(result["result"])
        else:
            self.assertIsInstance(result["result"], dict)

        if "reason_contains" in expected:
            self.assertIsNotNone(result["reason"])
            self.assertIn(expected["reason_contains"], result["reason"])

        if "citation_source_ids" in expected:
            actual_source_ids = {citation["source_id"] for citation in result["citations"]}
            self.assertTrue(set(expected["citation_source_ids"]).issubset(actual_source_ids))

        if result["result"] is None:
            return

        for key, value in expected.items():
            if key in META_EXPECTED_KEYS:
                continue
            self.assertIn(key, result["result"])
            self.assertEqual(result["result"][key], value)


if __name__ == "__main__":
    unittest.main()
