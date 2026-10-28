"""Market data, company listings and the market risk stage."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from app.models import CompanyListing, MarketPrice, Security
from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas.market import (
    ListingCreate,
    ListingOut,
    MarketRiskOut,
    MarketRiskRequest,
    SecurityCreate,
    SecurityOut,
)
from app.services import market_pipeline as market
from app.services.analysis_pipeline import latest_fiscal_year
from app.services.market_data import describe_series, risk_metrics

router = APIRouter(tags=["market"])


def _security_out(security: Security) -> SecurityOut:
    prices = market.price_series_from(security)
    return SecurityOut(
        ticker=security.ticker,
        name=security.name,
        currency=security.currency,
        exchange=security.exchange,
        sector=security.sector,
        source=security.source,
        **describe_series(prices),
    )


@router.post("/market/securities", response_model=SecurityOut, status_code=status.HTTP_201_CREATED)
def upsert_security(payload: SecurityCreate, db: DbSession):
    """Create a security, or replace its metadata and entire price history."""
    security = db.get(Security, payload.ticker)
    if security is None:
        security = Security(ticker=payload.ticker)
        db.add(security)
    security.name = payload.name
    security.currency = payload.currency
    security.exchange = payload.exchange
    security.sector = payload.sector
    security.source = payload.source
    # Delete and flush first: the unique (ticker, date) constraint would reject the
    # new rows if they were inserted before the orphans were removed.
    db.execute(delete(MarketPrice).where(MarketPrice.ticker == payload.ticker))
    db.flush()
    db.add_all(
        MarketPrice(ticker=payload.ticker, price_date=p.date, close=p.close, adj_close=p.adj_close)
        for p in payload.prices
    )
    db.commit()
    db.expire(security, ["prices"])
    db.refresh(security)
    return _security_out(security)


@router.get("/market/securities", response_model=list[SecurityOut])
def list_securities(db: DbSession):
    return [_security_out(s) for s in db.scalars(select(Security).order_by(Security.ticker))]


@router.get("/market/securities/{ticker}")
def get_security(ticker: str, db: DbSession):
    security = db.get(Security, ticker.upper())
    if security is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No security {ticker}")
    return {
        **_security_out(security).model_dump(),
        "prices": [
            {"date": p.price_date, "close": p.close, "adj_close": p.adj_close}
            for p in security.prices
        ],
    }


@router.get("/market/securities/{ticker}/risk")
def get_security_risk(
    ticker: str, db: DbSession, settings: AppSettings, end_date: str | None = None
):
    """Risk metrics and beta over the full history, or up to end_date."""
    security = db.get(Security, ticker.upper())
    if security is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No security {ticker}")
    end = end_date or security.prices[-1].price_date
    prices = market.up_to(market.price_series_from(security), end)
    metrics = risk_metrics(
        prices,
        risk_free_annual=settings.market_risk_free_rate,
        confidence=settings.market_var_confidence,
        minimum=settings.market_min_observations,
    )
    beta = market.compute_beta(db, settings, security.ticker, settings.market_benchmark_ticker, end)
    return {
        "ticker": security.ticker,
        "end_date": end,
        "observations": metrics.observations,
        "metrics": metrics.metrics,
        "reason": metrics.reason or None,
        "beta": {
            "benchmark": settings.market_benchmark_ticker,
            "beta": beta.beta,
            "adjusted_beta": beta.adjusted_beta,
            "r_squared": beta.r_squared,
            "observations": beta.observations,
            "reason": beta.reason or None,
        },
        "basis": {
            "returns": "adjusted close, month-end to month-end",
            "risk_free_rate": settings.market_risk_free_rate,
            "var_confidence": settings.market_var_confidence,
            "var_horizon": "one month",
        },
    }


@router.put("/companies/{company_id}/listing", response_model=ListingOut, tags=["companies"])
def set_listing(company: CurrentCompany, payload: ListingCreate, db: DbSession):
    """Link a company to its listed ticker and fiscal-year-end month."""
    if db.get(Security, payload.ticker) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No price history for {payload.ticker}. POST /market/securities first.",
        )
    listing = company.listing or CompanyListing(company_id=company.id)
    listing.ticker = payload.ticker
    listing.benchmark_ticker = payload.benchmark_ticker
    listing.fiscal_year_end_month = payload.fiscal_year_end_month
    company.listing = listing
    db.commit()
    db.refresh(listing)
    return listing


@router.get("/companies/{company_id}/listing", response_model=ListingOut, tags=["companies"])
def get_listing(company: CurrentCompany):
    if company.listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This company has no listing.")
    return company.listing


@router.post("/companies/{company_id}/compute-market-risk", response_model=MarketRiskOut)
def compute_market_risk(
    company: CurrentCompany,
    db: DbSession,
    settings: AppSettings,
    payload: MarketRiskRequest | None = None,
):
    """Merton distance-to-default, regression beta and risk metrics at the fiscal year end.

    Returns 200 with confidence UNUSABLE when the inputs cannot support a model,
    carrying the reason, rather than an error code.
    """
    if company.listing is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="No listing linked. PUT /companies/{id}/listing with the ticker first.",
        )
    if latest_fiscal_year(company) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Upload financial statements first.")
    request = payload or MarketRiskRequest()
    row, _ = market.run_market_risk(company, db, settings, request.risk_free_rate)
    return row


@router.get("/companies/{company_id}/market-risk", response_model=MarketRiskOut)
def get_market_risk(company: CurrentCompany):
    if not company.market_risks:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No market risk yet. POST /compute-market-risk first.",
        )
    return company.market_risks[-1]
