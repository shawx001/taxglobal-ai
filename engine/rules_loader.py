"""Load versioned tax rules from the repository data directory."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "tax_years"


class RuleLoadError(ValueError):
    """Raised when a requested rule file cannot be loaded."""


@lru_cache(maxsize=32)
def load_rule_file(tax_year: int, filename: str) -> dict[str, Any]:
    """Load a JSON rule file for a tax year.

    The engine deliberately reads only stored rule data. It does not fetch
    live web pages or fall back to prototype values.
    """

    path = DATA_ROOT / str(tax_year) / filename
    if not path.exists():
        raise RuleLoadError(f"Rule file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("tax_year") != tax_year:
        raise RuleLoadError(f"Rule file {path} has unexpected tax_year")
    return data


def load_federal_rules(tax_year: int = 2025) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_federal.json")


def load_fica_rules(tax_year: int = 2025) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_fica.json")


def load_feie_rules(tax_year: int = 2025) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_feie.json")


def load_state_rules(tax_year: int = 2025) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_states.json")
