"""Skill: track crypto capital gains from lots and disposals."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.skills.base import TaxSkill
from engine import crypto_gain_estimate


class CryptoLotInput(BaseModel):
    """Input schema for an acquired crypto lot."""

    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=1)
    date: str = Field(min_length=10)
    quantity: Decimal = Field(gt=0)
    cost_basis: Decimal = Field(ge=0)


class CryptoDisposalInput(BaseModel):
    """Input schema for a crypto disposal."""

    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=1)
    date: str = Field(min_length=10)
    quantity: Decimal = Field(gt=0)
    proceeds: Decimal = Field(ge=0)


class CryptoInput(BaseModel):
    """Input schema for crypto gain tracking."""

    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(default=2026, ge=2025)
    lots: list[CryptoLotInput] = Field(min_length=1, max_length=1000)
    disposals: list[CryptoDisposalInput] = Field(min_length=1, max_length=1000)
    method: Literal["FIFO", "LIFO", "HIFO", "fifo", "lifo", "hifo"] = "FIFO"
    filing_status: str = "single"
    other_taxable_income: Decimal = Field(default=Decimal("0"), ge=0)
    modified_agi: Decimal | None = Field(default=None, ge=0)
    state_code: str | None = Field(default=None, min_length=2, max_length=2)


class TrackCrypto(TaxSkill):
    name: str = "track_crypto"
    description: str = "Estimate crypto capital gains using deterministic lot matching and tax rules."
    args_schema: type[BaseModel] = CryptoInput
    source_attribution = "IRS capital gains rules / State DOR"
    engine_function_name = "crypto_gain_estimate"

    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        data = dict(params)
        data["method"] = data["method"].upper()
        return crypto_gain_estimate(**data)
