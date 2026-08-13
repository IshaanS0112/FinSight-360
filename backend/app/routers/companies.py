from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.models import Company, FinancialStatement
from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas import CompanyCreate, CompanyOut, StatementCreate, StatementOut
from app.services.analysis_pipeline import merged_line_items, validate_balance_sheet

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
def list_companies(db: DbSession):
    return list(db.scalars(select(Company).order_by(Company.created_at.desc())))


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
    """Store one statement, rejecting a balance sheet that does not balance.

    The check runs against the *merged* line items rather than this payload
    alone, so a balance sheet split across two uploads is validated once both
    halves are present rather than rejected on the first.
    """
    prospective = {**merged_line_items(company), **payload.line_items}
    error = validate_balance_sheet(prospective, settings)
    if error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)

    statement = FinancialStatement(
        company_id=company.id,
        statement_type=payload.statement_type.value,
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
def list_statements(company: CurrentCompany):
    return company.statements


@router.get("/{company_id}/line-items", tags=["statements"])
def merged_items(company: CurrentCompany):
    """Every reported line item for this company, flattened.

    Exposed because it is the exact input the engines see. When a ratio comes
    back omitted, this endpoint is how you find out whether the line item was
    never uploaded or was uploaded under the wrong key.
    """
    return {
        "company_id": str(company.id),
        "currency": company.currency,
        "units": company.units,
        "line_items": merged_line_items(company),
    }
