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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import AltmanModel, SectorClass, StatementType
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


class StatementCreate(BaseModel):
    statement_type: StatementType
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
    line_items: dict[str, Any]
    source_note: str | None
    uploaded_at: datetime


class RatioAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    liquidity_ratios: dict[str, Any]
    profitability_ratios: dict[str, Any]
    leverage_ratios: dict[str, Any]
    efficiency_ratios: dict[str, Any]
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
    model: str
    altman_z_score: float | None
    zone: str
    confidence: str
    component_scores: dict[str, Any]
    omitted_components: list[Any]
    calculation_basis: dict[str, Any]
    calculated_at: datetime


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


class InsightReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    structured_context: dict[str, Any]
    ai_narrative: dict[str, Any]
    generated_by: str
    generated_at: datetime
