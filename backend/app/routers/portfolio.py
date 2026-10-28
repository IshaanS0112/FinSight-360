"""Portfolio Lab endpoints. Cross-company, so not nested under /companies."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.models import PortfolioRun
from app.routers.deps import AppSettings, DbSession
from app.schemas.market import PortfolioRequest, PortfolioRunOut, PortfolioRunSummaryOut
from app.services.portfolio_pipeline import PortfolioError, run_portfolio

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.post("/optimize", response_model=PortfolioRunOut, status_code=status.HTTP_201_CREATED)
def optimize(payload: PortfolioRequest, db: DbSession, settings: AppSettings):
    """Run every optimiser side by side over one universe and store the result."""
    try:
        return run_portfolio(db, settings, payload)
    except PortfolioError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/runs", response_model=list[PortfolioRunOut])
def list_runs(db: DbSession, limit: int = 20):
    rows = db.scalars(select(PortfolioRun).order_by(PortfolioRun.run_at.desc()).limit(limit))
    return list(rows)


@router.get("/runs/summary", response_model=list[PortfolioRunSummaryOut])
def list_run_summaries(db: DbSession, limit: int = 20):
    """Recent runs, headline figures only.

    A full run carries a 2,000-point random cloud, so a history list built from
    /runs would ship roughly 100 KB per entry to show four numbers.
    """
    rows = db.scalars(select(PortfolioRun).order_by(PortfolioRun.run_at.desc()).limit(limit))
    return [_run_summary(row) for row in rows]


def _run_summary(row: PortfolioRun) -> PortfolioRunSummaryOut:
    """Headline portfolio figures for one run; null where that optimiser refused."""
    headline = row.calculation_basis.get("headline_portfolio")
    figures = row.results.get("portfolios", {}).get(headline or "", {})
    return PortfolioRunSummaryOut(
        id=row.id,
        name=row.name,
        tickers=row.tickers,
        run_at=row.run_at,
        headline_portfolio=headline,
        expected_return=figures.get("expected_return"),
        volatility=figures.get("volatility"),
        sharpe_ratio=figures.get("sharpe_ratio"),
    )


@router.get("/runs/{run_id}", response_model=PortfolioRunOut)
def get_run(run_id: uuid.UUID, db: DbSession):
    row = db.get(PortfolioRun, run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No portfolio run {run_id}")
    return row
