"""Load versioned tax rules from the repository data directory."""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "tax_years"


class RuleLoadError(ValueError):
    """Raised when a requested rule file cannot be loaded."""


@lru_cache(maxsize=32)
def _load_rule_file_cached(tax_year: int, filename: str) -> dict[str, Any]:
    """Load and cache a JSON rule file for a tax year.

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


def load_rule_file(tax_year: int, filename: str) -> dict[str, Any]:
    """Load a JSON rule file and return an isolated copy.

    The cached object must never be handed directly to callers. A route,
    alert generator, or test mutating rule data should not poison the process
    for later calculations.
    """

    return deepcopy(_load_rule_file_cached(tax_year, filename))


def load_federal_rules(tax_year: int = 2026) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_federal.json")


def load_fica_rules(tax_year: int = 2026) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_fica.json")


def load_feie_rules(tax_year: int = 2026) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_feie.json")


def load_state_rules(tax_year: int = 2026) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_states.json")


def load_nexus_rules(tax_year: int = 2026) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_nexus.json")


def load_capital_gains_rules(tax_year: int = 2026) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_capital_gains.json")


def load_qbi_rules(tax_year: int = 2026) -> dict[str, Any]:
    return load_rule_file(tax_year, "us_qbi.json")
