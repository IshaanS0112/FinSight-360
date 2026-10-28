"""Request and response shapes for the V3 market, portfolio and research endpoints."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TICKER = re.compile(r"^[A-Z0-9.\-^]{1,20}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ticker(value: str) -> str:
    code = value.strip().upper()
    if not _TICKER.match(code):
        raise ValueError(f"'{value}' is not a ticker: use letters, digits, '.', '-' or '^'")
    return code


class PricePointIn(BaseModel):
    date: str
    close: float = Field(gt=0)
    adj_close: float = Field(gt=0)

    @field_validator("date")
    @classmethod
    def check_date(cls, value: str) -> str:
        if not _DATE.match(value):
            raise ValueError("date must be YYYY-MM-DD")
        return value


class SecurityCreate(BaseModel):
    """A security and its full price history. Posting again replaces the history."""

    ticker: str
    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    exchange: str | None = Field(default=None, max_length=50)
    sector: str | None = Field(default=None, max_length=100)
    source: str = Field(min_length=3, max_length=500)
    prices: list[PricePointIn] = Field(min_length=1)

    @field_validator("ticker")
    @classmethod
    def check_ticker(cls, value: str) -> str:
        return _ticker(value)

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def unique_dates(self) -> SecurityCreate:
        dates = [p.date for p in self.prices]
        if len(dates) != len(set(dates)):
            raise ValueError("prices contain a duplicate date")
        return self


class SecurityOut(BaseModel):
    ticker: str
    name: str
    currency: str
    exchange: str | None
    sector: str | None
    source: str
    observations: int
    first_date: str | None
    last_date: str | None


class ListingCreate(BaseModel):
    ticker: str
    benchmark_ticker: str | None = None
    fiscal_year_end_month: int = Field(default=12, ge=1, le=12)

    @field_validator("ticker")
    @classmethod
    def check_ticker(cls, value: str) -> str:
        return _ticker(value)

    @field_validator("benchmark_ticker")
    @classmethod
    def check_benchmark(cls, value: str | None) -> str | None:
        return _ticker(value) if value else None


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    ticker: str
    benchmark_ticker: str | None
    fiscal_year_end_month: int


class MarketRiskRequest(BaseModel):
    risk_free_rate: float | None = Field(default=None, ge=-0.05, le=0.5)


class MarketRiskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    fiscal_year: int | None
    ticker: str
    merton_distance_to_default: float | None
    merton_probability_of_default: float | None
    naive_distance_to_default: float | None
    naive_probability_of_default: float | None
    asset_value: float | None
    asset_volatility: float | None
    beta: float | None
    adjusted_beta: float | None
    market_view: str
    risk_metrics: dict[str, Any]
    confidence: str
    calculation_basis: dict[str, Any]
    calculated_at: datetime


class PortfolioRequest(BaseModel):
    """One Portfolio Lab run. Every choice is named; nothing is a hidden default."""

    name: str | None = Field(default=None, max_length=200)
    tickers: list[str] = Field(min_length=2, max_length=30)
    start_date: str | None = None
    end_date: str | None = None
    expected_returns: Literal["mean_historical", "ema_historical", "capm"] = "mean_historical"
    risk_model: Literal["sample", "ledoit_wolf"] = "ledoit_wolf"
    risk_free_rate: float | None = Field(default=None, ge=-0.05, le=0.5)
    max_weight: float = Field(default=1.0, gt=0, le=1.0)
    target_return: float | None = Field(default=None, ge=-1.0, le=5.0)
    budget: float | None = Field(default=None, gt=0)
    credit_overlay: Literal["none", "exclude_high_risk", "cap_mixed"] = "none"
    benchmark_ticker: str | None = None

    @field_validator("tickers")
    @classmethod
    def check_tickers(cls, value: list[str]) -> list[str]:
        cleaned = [_ticker(t) for t in value]
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("tickers contain a duplicate")
        return cleaned

    @field_validator("start_date", "end_date")
    @classmethod
    def check_dates(cls, value: str | None) -> str | None:
        if value is not None and not _DATE.match(value):
            raise ValueError("dates must be YYYY-MM-DD")
        return value


class PortfolioRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    tickers: list[str]
    config: dict[str, Any]
    results: dict[str, Any]
    calculation_basis: dict[str, Any]
    run_at: datetime


class PortfolioRunSummaryOut(BaseModel):
    """A stored run without its frontier, random cloud or correlation matrix."""

    id: uuid.UUID
    name: str | None
    tickers: list[str]
    run_at: datetime
    headline_portfolio: str | None
    expected_return: float | None
    volatility: float | None
    sharpe_ratio: float | None


class ResearchMemoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    memo: dict[str, Any]
    sections: list[Any]
    trace: list[Any]
    curator_report: dict[str, Any]
    generated_by: str
    generated_at: datetime
