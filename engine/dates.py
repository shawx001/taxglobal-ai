"""Date helpers for tax engine functions."""

from __future__ import annotations

from datetime import date
from typing import Any

__all__ = ["_parse_iso_date", "_add_one_calendar_year"]

def _parse_iso_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string") from exc

def _add_one_calendar_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)
