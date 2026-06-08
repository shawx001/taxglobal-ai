"""Skill: detect sales-tax economic nexus exposure."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.skills.base import TaxSkill
from engine import nexus_estimate


class NexusInput(BaseModel):
    """Input schema for economic nexus detection."""

    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(default=2026, ge=2025)
    state_code: str = Field(min_length=2, max_length=2)
    sales_amount: Decimal = Field(ge=0)
    transaction_count: int | None = Field(default=None, ge=0)


class DetectNexus(TaxSkill):
    name: str = "detect_nexus"
    description: str = "Estimate sales-tax economic nexus from stored state threshold rules."
    args_schema: type[BaseModel] = NexusInput
    source_attribution = "State DOR economic nexus thresholds"
    engine_function_name = "nexus_estimate"

    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        return nexus_estimate(**params)
