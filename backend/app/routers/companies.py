from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Company, FinancialStatement
from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas import (
    CompanyCreate,
    CompanyOut,
    CompanySummaryOut,
    StatementCreate,
    StatementOut,
)
from app.services.analysis_pipeline import (
    fiscal_years,
    latest_fiscal_year,
    line_items_by_year,
    merged_line_items,
    validate_balance_sheet,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
def list_companies(db: DbSession):
    return list(db.scalars(select(Company).order_by(Company.created_at.desc())))


@router.get("/summary", response_model=list[CompanySummaryOut])
def list_company_summaries(db: DbSession):
    """Every company with its latest verdicts, in one request.

    Declared before /{company_id} so "summary" is not parsed as an id. The
    relationships are batch-loaded, so the query count does not grow with the
    number of companies.
    """
    query = (
        select(Company)
        .options(
            selectinload(Company.listing),
            selectinload(Company.bankruptcy_risks),
            selectinload(Company.health_scores),
            selectinload(Company.market_risks),
        )
        .order_by(Company.created_at.desc())
    )
    return [_summary(company) for company in db.scalars(query)]


def _summary(company: Company) -> CompanySummaryOut:
    """Latest risk, health and market rows folded into one CompanySummaryOut."""
    risk = company.bankruptcy_risks[-1] if company.bankruptcy_risks else None
    health = company.health_scores[-1] if company.health_scores else None
    market = company.market_risks[-1] if company.market_risks else None
    return CompanySummaryOut.model_validate(company).model_copy(
        update={
            "ticker": company.listing.ticker if company.listing else None,
            "consensus_verdict": risk.consensus_verdict if risk else None,
            "altman_model": risk.model if risk else None,
            "altman_zone": risk.zone if risk else None,
            "health_score": health.overall_score if health else None,
            "market_view": market.market_view if market else None,
            "merton_probability_of_default": (
                market.merton_probability_of_default if market else None
            ),
        }
    )


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: DbSession):
    company = Company(
        name=payload.name,
        industry=payload.industry,
        sector_class=payload.sector_class.value,
        fiscal_year=payload.fiscal_year,
        currency=payload.currency,
        units=payload.units,
        data_source=payload.data_source,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyOut)
def get_company_detail(company: CurrentCompany):
    return company


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(company: CurrentCompany, db: DbSession):
    db.delete(company)
    db.commit()


@router.post(
    "/{company_id}/financial-statements",
    response_model=StatementOut,
    status_code=status.HTTP_201_CREATED,
    tags=["statements"],
)
def upload_statement(
    company: CurrentCompany,
    payload: StatementCreate,
    db: DbSession,
    settings: AppSettings,
):
    """Store one statement for one fiscal year, rejecting an unbalanced sheet.

    The balance check is scoped to that year. fiscal_year falls back to the
    company's own; an undated statement on an undated company is rejected.
    """
    year = payload.fiscal_year or company.fiscal_year
    if year is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No fiscal_year on the statement and none on the company. Every "
                "statement must be dated: Piotroski, Beneish and Ohlson all compare "
                "year t against year t-1, and an undated statement cannot take part."
            ),
        )

    prospective = {**merged_line_items(company, year), **payload.line_items}
    error = validate_balance_sheet(prospective, settings)
    if error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)

    statement = FinancialStatement(
        company_id=company.id,
        statement_type=payload.statement_type.value,
        fiscal_year=year,
        line_items=payload.line_items,
        source_note=payload.source_note,
    )
    db.add(statement)
    db.commit()
    db.refresh(statement)
    return statement


@router.get(
    "/{company_id}/financial-statements",
    response_model=list[StatementOut],
    tags=["statements"],
)
def list_statements(company: CurrentCompany, years: int | None = None):
    """Statements for this company, optionally only the most recent ``years``."""
    statements = sorted(company.statements, key=lambda s: (s.fiscal_year, s.uploaded_at))
    if years is None or years < 1:
        return statements
    keep = set(fiscal_years(company)[-years:])
    return [s for s in statements if s.fiscal_year in keep]


@router.get("/{company_id}/line-items", tags=["statements"])
def merged_items(company: CurrentCompany, fiscal_year: int | None = None):
    """Every reported line item for one fiscal year, flattened.

    The exact input the engines see. Defaults to the latest year and also
    returns every year, so a two-year comparison needs one round trip.
    """
    year = fiscal_year if fiscal_year is not None else latest_fiscal_year(company)
    return {
        "company_id": str(company.id),
        "currency": company.currency,
        "units": company.units,
        "fiscal_year": year,
        "fiscal_years_on_file": fiscal_years(company),
        "line_items": merged_line_items(company, year),
        "line_items_by_year": {str(y): v for y, v in line_items_by_year(company).items()},
    }
