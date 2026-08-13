import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.company import Company


class FinancialStatement(Base):
    __tablename__ = "financial_statements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Free-shaped by design: filings disclose different line items, and the
    # ratio engine reads named keys and skips what a given company did not
    # report rather than imputing a value. The closed set of keys the engine
    # understands is declared in services/line_items.py.
    line_items: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # Per-statement provenance, e.g. "Caterpillar Inc. FY2024 10-K,
    # consolidated balance sheet". Coarser than a page reference, but it means
    # every number in the system can be traced to a document.
    source_note: Mapped[str | None] = mapped_column(String(500))

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="statements")
