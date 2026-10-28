"""Request and response schemas.

Input validation is doing real work here, not ceremony. Line-item keys are
restricted to the closed vocabulary, non-negative items are enforced as
non-negative, and unknown keys are rejected rather than silently ignored - because
a payload with ``"total_asets"`` would otherwise store fine and then produce a
Z-score of ``None`` with no indication of why.

The one rule worth arguing about is that ``data_source`` is required. A company
in this system with no filing provenance is not an analysis input.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.enums import AltmanModel, Distribution, SectorClass, StatementType
from app.services.benchmarks import RULE_BY_KEY
from app.services.line_items import ITEM_BY_KEY, ITEMS_BY_STATEMENT, is_number

CURRENCY_CODES = {"USD", "INR", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "SGD", "AED"}
UNIT_SCALES = {"UNITS", "THOUSANDS", "LAKHS", "MILLIONS", "CRORE", "BILLIONS"}


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    sector_class: SectorClass
    fiscal_year: int | None = Field(default=None, ge=1900, le=2100)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    units: str = Field(default="MILLIONS")
    # Required, not optional. See the module docstring.
    data_source: str = Field(min_length=3, max_length=500)

    @field_validator("currency")
    @classmethod
    def check_currency(cls, value: str) -> str:
        code = value.upper()
        if code not in CURRENCY_CODES:
            raise ValueError(
                f"currency must be one of {sorted(CURRENCY_CODES)}. Ratios are "
                "dimensionless so the code does not affect the maths, but it is "
                "displayed alongside every figure and a wrong one misleads the reader."
            )
        return code

    @field_validator("units")
    @classmethod
    def check_units(cls, value: str) -> str:
        scale = value.upper()
        if scale not in UNIT_SCALES:
            raise ValueError(f"units must be one of {sorted(UNIT_SCALES)}")
        return scale


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    industry: str | None
    sector_class: str
    fiscal_year: int | None
    currency: str
    units: str
    data_source: str | None
    created_at: datetime


class CompanySummaryOut(CompanyOut):
    """A company plus the headline of each stage that has run, for the index page.

    A stage that has not run is null, never an error: the index lists companies
    at every point in the pipeline.
    """

    ticker: str | None = None
    consensus_verdict: str | None = None
    altman_model: str | None = None
    altman_zone: str | None = None
    health_score: float | None = None
    market_view: str | None = None
    merton_probability_of_default: float | None = None


class StatementCreate(BaseModel):
    statement_type: StatementType
    # V2. Optional on the wire, defaulted from the company by the router, so
    # every V1 payload still uploads. Stored NOT NULL either way.
    fiscal_year: int | None = Field(default=None, ge=1900, le=2100)
    line_items: dict[str, float] = Field(min_length=1)
    source_note: str | None = Field(default=None, max_length=500)

    @field_validator("line_items")
    @classmethod
    def check_line_items(cls, value: dict[str, Any]) -> dict[str, float]:
        cleaned: dict[str, float] = {}
        for key, raw in (value or {}).items():
            spec = ITEM_BY_KEY.get(key)
            if spec is None:
                raise ValueError(
                    f"'{key}' is not a recognised line item. Accepted keys: "
                    f"{sorted(ITEM_BY_KEY)}. Unknown keys are rejected rather than "
                    "ignored, because a typo would otherwise store cleanly and then "
                    "silently omit every ratio that needed it."
                )
            if not is_number(raw):
                raise ValueError(f"line_items['{key}'] must be a number, got {type(raw).__name__}")
            number = float(raw)
            if spec.non_negative and number < 0:
                raise ValueError(
                    f"line_items['{key}'] ({number}) cannot be negative. "
                    f"{spec.label} is a non-negative quantity in a well-formed filing; "
                    "a negative value here is a sign error."
                )
            cleaned[key] = number
        return cleaned

    @field_validator("line_items")
    @classmethod
    def warn_wrong_statement(cls, value: dict[str, float], info: Any) -> dict[str, float]:
        # Runs after the key check above; ordering is guaranteed by declaration order.
        statement = (info.data or {}).get("statement_type")
        if statement is None:
            return value
        allowed = {spec.key for spec in ITEMS_BY_STATEMENT[StatementType(statement)]}
        stray = sorted(set(value) - allowed)
        if stray:
            raise ValueError(
                f"{sorted(value)} contains items that do not belong to a "
                f"{StatementType(statement).value}: {stray}. Upload them with the "
                "statement they actually come from so the provenance note stays true."
            )
        return value


class StatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    statement_type: str
    fiscal_year: int
    line_items: dict[str, Any]
    source_note: str | None
    uploaded_at: datetime


class RatioAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    fiscal_year: int | None
    liquidity_ratios: dict[str, Any]
    profitability_ratios: dict[str, Any]
    leverage_ratios: dict[str, Any]
    efficiency_ratios: dict[str, Any]
    dupont: dict[str, Any]
    cash_conversion_cycle: dict[str, Any]
    trend: dict[str, Any]
    omitted_ratios: list[Any]
    calculation_basis: dict[str, Any]
    calculated_at: datetime


class BankruptcyRiskRequest(BaseModel):
    """Optional overrides for the Altman computation.

    The default path selects the model from the company's sector class. Both
    overrides exist so a user can reproduce a figure computed elsewhere with a
    different (possibly wrong) choice - and the choice is recorded in the result
    either way.
    """

    model: AltmanModel | None = None
    emerging_market_adjustment: bool = False


class BankruptcyRiskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    fiscal_year: int | None
    model: str
    altman_z_score: float | None
    zone: str
    confidence: str
    component_scores: dict[str, Any]
    omitted_components: list[Any]
    zscore_variant: str | None
    variant_scores: dict[str, Any]
    ohlson_o_score: float | None
    ohlson_probability: float | None
    ohlson_components: dict[str, Any]
    ohlson_omitted: list[Any]
    consensus_verdict: str | None
    calculation_basis: dict[str, Any]
    calculated_at: datetime


class PeerCompanyCreate(BaseModel):
    """One sourced comparison company.

    source is required: a peer with no citation is a number someone typed. Ratio
    keys are restricted to the ten the engine computes.
    """

    peer_name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    fiscal_year: int | None = Field(default=None, ge=1900, le=2100)
    source: str = Field(min_length=3, max_length=500)
    ratios: dict[str, float] = Field(min_length=1)

    @field_validator("ratios")
    @classmethod
    def check_ratio_keys(cls, value: dict[str, Any]) -> dict[str, float]:
        cleaned: dict[str, float] = {}
        for key, raw in (value or {}).items():
            if key not in RULE_BY_KEY:
                raise ValueError(
                    f"'{key}' is not a ratio this engine computes. Accepted keys: "
                    f"{sorted(RULE_BY_KEY)}. A peer set that carries a metric the "
                    "subject company has no equivalent for cannot be benchmarked "
                    "against, so the key is rejected rather than stored and ignored."
                )
            if not is_number(raw):
                raise ValueError(f"ratios['{key}'] must be a number, got {type(raw).__name__}")
            cleaned[key] = float(raw)
        return cleaned


class PeerSetCreate(BaseModel):
    """A whole peer set, replacing whatever was attached before.

    Replace, not append: who a company is comparable to is one judgement.
    """

    peers: list[PeerCompanyCreate] = Field(min_length=1)


class PeerCompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    peer_name: str
    industry: str | None
    fiscal_year: int | None
    source: str
    ratios: dict[str, Any]
    added_at: datetime


class EarningsQualityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    fiscal_year: int
    prior_fiscal_year: int | None
    piotroski_f_score: int | None
    f_score_band: str | None
    f_score_components: dict[str, Any]
    beneish_m_score: float | None
    m_score_components: dict[str, Any]
    manipulation_flag: bool | None
    confidence: str
    omitted: list[Any]
    calculation_basis: dict[str, Any]
    calculated_at: datetime


class DcfValuationRequest(BaseModel):
    """DCF assumptions. Every field optional, falling back to a declared default.

    The default actually used is echoed back in the stored assumptions.
    """

    revenue_growth: float | None = Field(default=None, ge=-0.5, le=1.0)
    terminal_growth: float | None = Field(default=None, ge=-0.05, le=0.15)
    tax_rate: float | None = Field(default=None, ge=0.0, lt=1.0)
    projection_years: int | None = Field(default=None, ge=1, le=20)
    risk_free_rate: float | None = Field(default=None, ge=-0.05, le=0.5)
    equity_risk_premium: float | None = Field(default=None, ge=0.0, le=0.5)
    beta: float | None = Field(default=None, ge=0.0, le=5.0)
    wacc_override: float | None = Field(default=None, gt=0.0, le=1.0)
    cost_of_debt_override: float | None = Field(default=None, ge=0.0, le=1.0)
    ebit_margin_override: float | None = Field(default=None, ge=-1.0, le=1.0)


class DcfValuationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    base_fiscal_year: int | None
    assumptions: dict[str, Any]
    fcff_projection: list[Any]
    wacc: float | None
    terminal_value: float | None
    enterprise_value: float | None
    equity_value: float | None
    implied_share_price: float | None
    upside_downside_pct: float | None
    confidence: str
    calculation_basis: dict[str, Any]
    calculated_at: datetime


class ShockSpecIn(BaseModel):
    """One sampled input: TRIANGULAR takes low/mode/high, NORMAL takes mu/sigma."""

    distribution: Distribution = Distribution.TRIANGULAR
    low: float | None = None
    mode: float | None = None
    high: float | None = None
    mu: float | None = None
    sigma: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def check_shape(self) -> ShockSpecIn:
        if self.distribution is Distribution.TRIANGULAR:
            if self.low is None or self.mode is None or self.high is None:
                raise ValueError("a TRIANGULAR shock needs low, mode and high")
            if not self.low <= self.mode <= self.high:
                raise ValueError(
                    f"a TRIANGULAR shock needs low <= mode <= high, got "
                    f"{self.low} / {self.mode} / {self.high}"
                )
        elif self.mu is None or self.sigma is None:
            raise ValueError("a NORMAL shock needs mu and sigma")
        return self


class ScenarioRunRequest(BaseModel):
    n_trials: int | None = Field(default=None, ge=100)
    # Exposed so the caller can pin it and regenerate the distribution exactly.
    seed: int | None = None
    distributions: dict[str, ShockSpecIn] | None = None
    dcf: DcfValuationRequest | None = None
    include_dcf: bool = True


class ScenarioRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    n_trials: int
    seed: int
    input_distributions: dict[str, Any]
    result_summary: dict[str, Any]
    calculation_basis: dict[str, Any]
    run_at: datetime


class HealthScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    overall_score: float | None
    component_scores: dict[str, Any]
    peer_percentile: float | None
    confidence: str
    calculation_basis: dict[str, Any]
    calculated_at: datetime


class InsightQuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class InsightAnswerOut(BaseModel):
    """One answer, with the evidence it rests on.

    grounded_in names the context fields the answer used, checked against the
    context rather than taken on the model's word.
    """

    question: str
    answer: str
    grounded_in: list[str]
    refused: bool
    answered_by: str | None
    dropped_citations: int
    asked_at: str
    report_id: str


class InsightReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    structured_context: dict[str, Any]
    ai_narrative: dict[str, Any]
    generated_by: str
    qa_thread: list[Any]
    generated_at: datetime
