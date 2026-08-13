import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.analysis import (
        BankruptcyRisk,
        FinancialHealthScore,
        InsightReport,
        RatioAnalysis,
    )
    from app.models.statement import FinancialStatement


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))

    # Coarse sector class. Not decoration: it decides which Altman model is
    # valid for this issuer, and FINANCIAL means no Z-score is reported at all.
    sector_class: Mapped[str] = mapped_column(String(30), nullable=False)

    fiscal_year: Mapped[int | None] = mapped_column(Integer)

    # Reporting currency and the multiplier the line items are expressed in.
    # Every ratio in this system is dimensionless, so mixing currencies across
    # companies is harmless - but a peer benchmark computed across two companies
    # reported in different units would be silently wrong, so the unit is
    # carried and checked rather than assumed.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    units: Mapped[str] = mapped_column(String(20), nullable=False, default="MILLIONS")

    # Where the numbers came from. Required at the API layer: a company with no
    # filing provenance is not an analysis input, it is a guess.
    data_source: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    statements: Mapped[list["FinancialStatement"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="FinancialStatement.uploaded_at",
    )
    ratio_analyses: Mapped[list["RatioAnalysis"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="RatioAnalysis.calculated_at",
    )
    bankruptcy_risks: Mapped[list["BankruptcyRisk"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="BankruptcyRisk.calculated_at",
    )
    health_scores: Mapped[list["FinancialHealthScore"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="FinancialHealthScore.calculated_at",
    )
    insight_reports: Mapped[list["InsightReport"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="InsightReport.generated_at",
    )
