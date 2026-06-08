"""Skill: assess Foreign Earned Income Exclusion."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.skills.base import TaxSkill
from engine import feie_estimate


class FeieInput(BaseModel):
    """Input schema for FEIE assessment."""

    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(default=2026, ge=2025)
    foreign_earned_income: Decimal = Field(ge=0)
    days_abroad: int = Field(ge=0, le=366)


class AssessFeie(TaxSkill):
    name: str = "assess_feie"
    description: str = "Assess Foreign Earned Income Exclusion eligibility and calculate excluded amount."
    args_schema: type[BaseModel] = FeieInput
    source_attribution = "IRS Form 2555 / Section 911"
    engine_function_name = "feie_estimate"

    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        return feie_estimate(**params)
