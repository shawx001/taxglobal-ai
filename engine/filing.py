"""Filing-status normalization for tax engine functions."""

from __future__ import annotations

__all__ = ["SUPPORTED_FILING_STATUSES", "FILING_ALIASES", "_normalize_filing_status"]

SUPPORTED_FILING_STATUSES = {
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
    "qualifying_surviving_spouse",
}


FILING_ALIASES = {
    "mfj": "married_filing_jointly",
    "mfs": "married_filing_separately",
    "hoh": "head_of_household",
    "qss": "qualifying_surviving_spouse",
}


def _normalize_filing_status(filing_status: str) -> str:
    normalized = FILING_ALIASES.get(filing_status, filing_status)
    if normalized not in SUPPORTED_FILING_STATUSES:
        raise ValueError(f"Unsupported filing_status: {filing_status}")
    return normalized
