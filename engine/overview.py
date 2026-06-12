"""Tax-rate overview from versioned rule data (M3.5 chat follow-up).

Answers "rates questions" ("加州税多少" / "联邦税率是多少") directly from
the rule files — no calculation, no LLM, no retrieval. Every number in
the answer is a verbatim copy of the versioned rule data with its
citations attached.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from engine.rules_loader import load_federal_rules, load_state_rules


def _bracket_rows(brackets: Any, filing_status: str) -> list[dict[str, Any]] | None:
    # Rule data is exposed as immutable MappingProxyType — test against the
    # Mapping ABC, never dict.
    if not isinstance(brackets, Mapping):
        return None
    rows = brackets.get(filing_status)
    if not isinstance(rows, Sequence) or isinstance(rows, str):
        return None
    return [
        {"up_to": row.get("up_to"), "rate": row.get("rate")}
        for row in rows
        if isinstance(row, Mapping)
    ]


def federal_tax_overview(tax_year: int, filing_status: str = "single") -> dict[str, Any]:
    """Federal ordinary-income rate overview straight from rule data."""

    rules = load_federal_rules(tax_year)
    deduction = rules.get("standard_deduction", {})
    return {
        "status": "ok",
        "jurisdiction": "federal",
        "name": "US Federal",
        "tax_year": rules.get("tax_year", tax_year),
        "filing_status": filing_status,
        "income_tax_type": "progressive",
        "standard_deduction": deduction.get(filing_status),
        "brackets": _bracket_rows(rules.get("ordinary_income_brackets"), filing_status),
        "flat_rate": None,
        "rule_version": rules.get("rule_version", ""),
        "source_ids": list(rules.get("source_ids", [])),
        "citation": deduction.get("citation", ""),
        "notes": "",
    }


def state_tax_overview(state_code: str, tax_year: int, filing_status: str = "single") -> dict[str, Any]:
    """State income-tax rate overview straight from rule data."""

    rules = load_state_rules(tax_year)
    state = rules.get("states", {}).get(state_code.upper())
    if not isinstance(state, Mapping):
        return {
            "status": "not_covered",
            "jurisdiction": state_code.upper(),
            "tax_year": tax_year,
            "reason": f"State '{state_code.upper()}' is not in the rule data for {tax_year}.",
        }

    tax_base = state.get("tax_base") or {}
    standard_deduction = (tax_base.get("standard_deduction") or {}).get(filing_status)
    return {
        "status": "ok",
        "jurisdiction": state_code.upper(),
        "name": state.get("name", state_code.upper()),
        "tax_year": rules.get("tax_year", tax_year),
        "filing_status": filing_status,
        "income_tax_type": state.get("income_tax_type", ""),
        "standard_deduction": standard_deduction,
        "brackets": _bracket_rows(state.get("brackets"), filing_status),
        "flat_rate": state.get("flat_rate"),
        "rule_version": rules.get("rule_version", ""),
        "source_ids": list(state.get("source_ids", [])),
        "citation": state.get("citation", ""),
        "notes": state.get("notes", ""),
    }
