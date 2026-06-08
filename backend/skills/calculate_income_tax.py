"""Skill: calculate comprehensive income tax summary."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas import FilingStatus
from backend.skills.base import TaxSkill
from engine import income_tax_summary


class IncomeTaxInput(BaseModel):
    """Input schema for comprehensive income tax calculation."""

    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(default=2026, ge=2025)
    net_self_employment_profit: Decimal = Field(default=Decimal("0"), ge=0)
    w2_wages: Decimal = Field(default=Decimal("0"), ge=0)
    other_ordinary_income: Decimal = Field(default=Decimal("0"), ge=0)
    long_term_capital_gain: Decimal = Field(default=Decimal("0"), ge=0)
    short_term_capital_gain: Decimal = Field(default=Decimal("0"), ge=0)
    modified_agi: Decimal | None = Field(default=None, ge=0)
    foreign_earned_income: Decimal = Field(default=Decimal("0"), ge=0)
    days_abroad: int = Field(default=0, ge=0, le=366)
    filing_status: FilingStatus = "single"
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    se_health_insurance: Decimal = Field(default=Decimal("0"), ge=0)
    retirement_contributions: Decimal = Field(default=Decimal("0"), ge=0)
    qbi_w2_wages: Decimal = Field(default=Decimal("0"), ge=0)
    qbi_ubia: Decimal = Field(default=Decimal("0"), ge=0)
    is_sstb: bool = False
    deduction: Decimal | None = Field(default=None, ge=0)


class CalculateIncomeTax(TaxSkill):
    name: str = "calculate_income_tax"
    description: str = (
        "Calculate comprehensive income tax including federal, FICA, self-employment, "
        "state, FEIE, NIIT, and QBI deduction."
    )
    args_schema: type[BaseModel] = IncomeTaxInput
    source_attribution = "IRS Rev. Proc. / IRS FICA / State DOR / Section 199A"
    engine_function_name = "income_tax_summary"

    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        return income_tax_summary(**params)
