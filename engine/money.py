"""Money and Decimal helpers for the tax engine."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

__all__ = ["_money", "_money_decimal", "_money_quantized", "_decimal_rule", "_decimal_input"]

def _money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _money_decimal(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _money_quantized(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _decimal_rule(value: Any) -> Decimal:
    return Decimal(str(value))

def _decimal_input(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
