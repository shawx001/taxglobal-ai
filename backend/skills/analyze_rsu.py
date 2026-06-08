"""Skill: analyze RSU vesting and optional sale tax impact."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas import FilingStatus
from backend.skills.base import TaxSkill
from engine import rsu_tax_estimate


class RsuSaleInput(BaseModel):
    """Input schema for an optional RSU sale scenario."""

    model_config = ConfigDict(extra="forbid")

    sale_date: str = Field(min_length=10)
    sale_price_per_share: Decimal = Field(ge=0)


class RsuInput(BaseModel):
    """Input schema for RSU analysis."""

    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(default=2026, ge=2025)
    shares_vested: Decimal = Field(gt=0)
    fmv_per_share: Decimal = Field(ge=0)
    vest_date: str = Field(min_length=10)
    filing_status: FilingStatus = "single"
    other_taxable_income: Decimal = Field(default=Decimal("0"), ge=0)
    sale_scenario: RsuSaleInput | None = None


class AnalyzeRsu(TaxSkill):
    name: str = "analyze_rsu"
    description: str = "Estimate RSU vesting ordinary income tax and optional sale capital gains tax."
    args_schema: type[BaseModel] = RsuInput
    source_attribution = "IRS Section 83 / IRS capital gains rules"
    engine_function_name = "rsu_tax_estimate"

    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        data = dict(params)
        data["fair_market_value_per_share"] = data.pop("fmv_per_share")
        return rsu_tax_estimate(**data)
