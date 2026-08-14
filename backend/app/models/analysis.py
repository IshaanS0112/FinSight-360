import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Uuid, func
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

    liquidity_ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    profitability_ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    leverage_ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    efficiency_ratios: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # Which ratios could not be computed and which line item was missing.
    # Stored rather than logged: "we could not compute interest coverage
    # because the filing summary did not disclose interest expense" is an
    # analytical finding, not a debug detail.
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

    model: Mapped[str] = mapped_column(String(30), nullable=False)
    altman_z_score: Mapped[float | None] = mapped_column(Float)
    zone: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)

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

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="insight_reports")
