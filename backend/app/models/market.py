"""V3 tables. All new: no column is added to an existing table, so create_all
still upgrades a V2 database without a migration."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.company import Company


class Security(Base):
    """A listed instrument with a price history."""

    __tablename__ = "securities"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(50))
    sector: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    prices: Mapped[list["MarketPrice"]] = relationship(
        back_populates="security", cascade="all, delete-orphan", order_by="MarketPrice.price_date"
    )


class MarketPrice(Base):
    """One month-end observation. close is split-adjusted; adj_close also adds dividends."""

    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("ticker", "price_date", name="uq_market_prices_ticker_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(
        String(20), ForeignKey("securities.ticker", ondelete="CASCADE"), nullable=False, index=True
    )
    price_date: Mapped[str] = mapped_column(String(10), nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float] = mapped_column(Float, nullable=False)

    security: Mapped["Security"] = relationship(back_populates="prices")


class CompanyListing(Base):
    """Links a company to its listed ticker, without altering the companies table."""

    __tablename__ = "company_listings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("securities.ticker"), nullable=False)
    benchmark_ticker: Mapped[str | None] = mapped_column(String(20))
    # Needed to line price windows up with statements: Infosys reports to March.
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, nullable=False, default=12)

    company: Mapped["Company"] = relationship(back_populates="listing")


class MarketRisk(Base):
    """Merton DD, regression beta and risk metrics for one company and fiscal year."""

    __tablename__ = "market_risk"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)

    merton_distance_to_default: Mapped[float | None] = mapped_column(Float)
    merton_probability_of_default: Mapped[float | None] = mapped_column(Float)
    naive_distance_to_default: Mapped[float | None] = mapped_column(Float)
    naive_probability_of_default: Mapped[float | None] = mapped_column(Float)
    asset_value: Mapped[float | None] = mapped_column(Float)
    asset_volatility: Mapped[float | None] = mapped_column(Float)

    beta: Mapped[float | None] = mapped_column(Float)
    adjusted_beta: Mapped[float | None] = mapped_column(Float)

    # CONFIRMS | CONTRADICTS | PARTIAL | UNAVAILABLE, against the accounting consensus.
    market_view: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_metrics: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="market_risks")


class PortfolioRun(Base):
    """One Portfolio Lab optimisation, stored with the configuration that produced it."""

    __tablename__ = "portfolio_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(String(200))
    tickers: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    config: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    results: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )


class ResearchMemo(Base):
    """A multi-agent research memo, with every node's trace and the curator's report."""

    __tablename__ = "research_memos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memo: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    sections: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    trace: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    curator_report: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    generated_by: Mapped[str] = mapped_column(String(30), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="research_memos")
