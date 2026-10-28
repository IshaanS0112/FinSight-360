import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.company import Company


class RatioAnalysis(Base):
    __tablename__ = "ratio_analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # V2: which year these ratios describe. Null only for a company whose
    # statements carry no fiscal year at all, which the API no longer permits.
    fiscal_year: Mapped[int | None] = mapped_column(Integer)

    liquidity_ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    profitability_ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    leverage_ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    efficiency_ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # Which ratios could not be computed and which line item was missing.
    # Stored rather than logged: "we could not compute interest coverage
    # because the filing summary did not disclose interest expense" is an
    # analytical finding, not a debug detail.
    # V2. Own columns, not ratio buckets: none of these is a ratio.
    dupont: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    cash_conversion_cycle: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    trend: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    omitted_ratios: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="ratio_analyses")


class BankruptcyRisk(Base):
    __tablename__ = "bankruptcy_risk"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    fiscal_year: Mapped[int | None] = mapped_column(Integer)

    model: Mapped[str] = mapped_column(String(30), nullable=False)
    altman_z_score: Mapped[float | None] = mapped_column(Float)
    zone: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)

    # V2. One headline Altman result, plus the other variants and Ohlson.
    zscore_variant: Mapped[str | None] = mapped_column(String(20))
    # {Z_1968: {score, zone, confidence}, ...} for every variant that could be run.
    variant_scores: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    ohlson_o_score: Mapped[float | None] = mapped_column(Float)
    ohlson_probability: Mapped[float | None] = mapped_column(Float)
    ohlson_components: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    ohlson_omitted: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    # LOW_RISK | HIGH_RISK | MIXED_SIGNAL | INDETERMINATE. Null until run.
    consensus_verdict: Mapped[str | None] = mapped_column(String(20))

    # {x1..x5: {ratio, coefficient, contribution}} - the per-component
    # decomposition, so a reader can see which term drove the verdict instead
    # of being handed one number.
    component_scores: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    omitted_components: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="bankruptcy_risks")


class FinancialHealthScore(Base):
    __tablename__ = "financial_health_scores"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    overall_score: Mapped[float | None] = mapped_column(Float)
    component_scores: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    peer_percentile: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="health_scores")


class InsightReport(Base):
    __tablename__ = "insight_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Every figure the narrative may mention exists here first, so the claim
    # that no number was invented can be checked by diffing the two.
    structured_context: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    ai_narrative: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    generated_by: Mapped[str] = mapped_column(String(30), nullable=False)

    # V2. [{question, answer, grounded_in, refused, asked_at}]. Append-only.
    qa_thread: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="insight_reports")


class EarningsQuality(Base):
    """Piotroski F-Score and Beneish M-Score for one fiscal year.

    Separate from bankruptcy_risk: those models ask whether the company will
    fail, these ask whether the numbers they were fed can be trusted.
    """

    __tablename__ = "earnings_quality"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_fiscal_year: Mapped[int | None] = mapped_column(Integer)

    # 0-9, or null when too few of the nine tests could be evaluated to report a
    # total. A partial F-Score is not a low F-Score.
    piotroski_f_score: Mapped[int | None] = mapped_column(Integer)
    f_score_band: Mapped[str | None] = mapped_column(String(20))
    # {test_key: {passed, value_t, value_prior, reason}} - all nine, named.
    f_score_components: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    beneish_m_score: Mapped[float | None] = mapped_column(Float)
    # {dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi: {ratio, coefficient, contribution}}
    m_score_components: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    # Beneish's own -1.78 cutoff. The stricter -2.22 verdict is carried in
    # calculation_basis rather than here, because promoting one threshold to a
    # column would quietly pick a side in a live disagreement.
    manipulation_flag: Mapped[bool | None] = mapped_column(Boolean)

    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    omitted: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="earnings_quality")


class DcfValuation(Base):
    """One discounted cash flow run, stored with the assumptions that produced it.

    A DCF is a function of its assumptions, so they are a column, not config.
    """

    __tablename__ = "dcf_valuation"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    base_fiscal_year: Mapped[int | None] = mapped_column(Integer)

    assumptions: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    # Year-by-year: {year, ebit, fcff, discount_factor, present_value}
    fcff_projection: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    wacc: Mapped[float | None] = mapped_column(Float)
    terminal_value: Mapped[float | None] = mapped_column(Float)
    enterprise_value: Mapped[float | None] = mapped_column(Float)
    equity_value: Mapped[float | None] = mapped_column(Float)
    implied_share_price: Mapped[float | None] = mapped_column(Float)
    upside_downside_pct: Mapped[float | None] = mapped_column(Float)

    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="dcf_valuations")


class ScenarioRun(Base):
    """One Monte Carlo sweep over the deterministic engines.

    seed is stored, not logged: the distribution must be regenerable exactly.
    """

    __tablename__ = "scenario_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    n_trials: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    input_distributions: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    # {health_score: {p5, p50, p95}, z_score: {...}, zone_shares: {...},
    #  distress_probability, dcf_equity_value: {...}}
    result_summary: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="scenario_runs")


class PeerCompany(Base):
    """One sourced comparison company: computed ratios plus a required citation."""

    __tablename__ = "peer_companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    peer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="peer_companies")
