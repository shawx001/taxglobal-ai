import unittest
from types import MappingProxyType

from engine.rules_loader import load_rule_file, load_rule_file_mutable


class RulesLoaderFreezeTests(unittest.TestCase):
    def test_frozen_read_access(self):
        rules = load_rule_file(2026, "us_federal.json")

        self.assertIsInstance(rules, MappingProxyType)
        self.assertEqual(rules["tax_year"], 2026)
        self.assertIn("ordinary_income_brackets", rules.keys())
        self.assertIsNotNone(rules.get("standard_deduction"))

    def test_frozen_write_raises(self):
        rules = load_rule_file(2026, "us_federal.json")

        with self.assertRaises(TypeError):
            rules["tax_year"] = 2099
        with self.assertRaises(AttributeError):
            rules.pop("tax_year")
        with self.assertRaises(TypeError):
            rules["ordinary_income_brackets"]["single"] = ()

    def test_mutable_copy_works(self):
        rules = load_rule_file_mutable(2026, "us_federal.json")

        self.assertIsInstance(rules, dict)
        self.assertIsInstance(rules["ordinary_income_brackets"]["single"], list)
        rules["tax_year"] = 2099
        rules["ordinary_income_brackets"]["single"].append({"up_to": None, "rate": "0.99"})
        self.assertEqual(rules["tax_year"], 2099)

    def test_load_rule_file_returns_same_object(self):
        first = load_rule_file(2026, "us_federal.json")
        second = load_rule_file(2026, "us_federal.json")

        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
