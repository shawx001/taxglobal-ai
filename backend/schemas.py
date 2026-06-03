from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FilingStatus = Literal[
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
    "qualifying_surviving_spouse",
    "mfj",
    "mfs",
    "hoh",
    "qss",
]


class TaxYearModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(default=2026, ge=2025)


class FederalIncomeRequest(TaxYearModel):
    gross_income: float = Field(ge=0)
    filing_status: FilingStatus = "single"
    deduction: float | None = Field(default=None, ge=0)


class FicaRequest(TaxYearModel):
    wages: float = Field(ge=0)
    filing_status: FilingStatus = "single"


class StateIncomeRequest(TaxYearModel):
    state_code: str = Field(min_length=2, max_length=2)
    taxable_income: float
    filing_status: FilingStatus = "single"


class SelfEmploymentRequest(TaxYearModel):
    net_self_employment_profit: float
    filing_status: FilingStatus = "single"


class IncomeSummaryRequest(TaxYearModel):
    net_self_employment_profit: float = Field(default=0, ge=0)
    w2_wages: float = Field(default=0, ge=0)
    other_ordinary_income: float = Field(default=0, ge=0)
    long_term_capital_gain: float = Field(default=0, ge=0)
    short_term_capital_gain: float = Field(default=0, ge=0)
    modified_agi: float | None = Field(default=None, ge=0)
    foreign_earned_income: float = Field(default=0, ge=0)
    days_abroad: int = Field(default=0, ge=0, le=366)
    filing_status: str = "single"
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    se_health_insurance: float = Field(default=0, ge=0)
    retirement_contributions: float = Field(default=0, ge=0)
    qbi_w2_wages: float = Field(default=0, ge=0)
    qbi_ubia: float = Field(default=0, ge=0)
    is_sstb: bool = False
    deduction: float | None = Field(default=None, ge=0)


class FeieRequest(TaxYearModel):
    foreign_earned_income: float = Field(ge=0)
    days_abroad: int = Field(ge=0, le=366)


class CryptoLot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=1)
    date: str = Field(min_length=10)
    quantity: float = Field(gt=0)
    cost_basis: float = Field(ge=0)


class CryptoDisposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = Field(min_length=1)
    date: str = Field(min_length=10)
    quantity: float = Field(gt=0)
    proceeds: float = Field(ge=0)


class CryptoRequest(TaxYearModel):
    lots: list[CryptoLot] = Field(min_length=1)
    disposals: list[CryptoDisposal] = Field(min_length=1)
    method: Literal["FIFO", "LIFO", "HIFO", "fifo", "lifo", "hifo"] = "FIFO"
    filing_status: FilingStatus = "single"
    other_taxable_income: float = Field(default=0, ge=0)
    modified_agi: float | None = Field(default=None, ge=0)
    state_code: str | None = Field(default=None, min_length=2, max_length=2)


class RsuSaleScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sale_date: str = Field(min_length=10)
    sale_price_per_share: float = Field(ge=0)


class RsuRequest(TaxYearModel):
    shares_vested: float = Field(gt=0)
    fmv_per_share: float = Field(ge=0)
    vest_date: str = Field(min_length=10)
    filing_status: FilingStatus = "single"
    other_taxable_income: float = Field(default=0, ge=0)
    sale_scenario: RsuSaleScenario | None = None


class NexusRequest(TaxYearModel):
    state_code: str = Field(min_length=2, max_length=2)
    sales_amount: float = Field(ge=0)
    transaction_count: int | None = Field(default=None, ge=0)
