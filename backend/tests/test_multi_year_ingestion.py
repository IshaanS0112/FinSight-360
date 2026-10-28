"""Multi-year ingestion: one company, several fiscal years, no cross-year bleed.

# roadmap: v2-01-multi-year-ingestion

The single behaviour worth guarding here is that the engines see *one year at a
time*. V1 merged every statement a company owned into one dictionary, which was
correct while a company could only hold one year. The moment it can hold two,
that same merge silently produces a balance sheet belonging to neither.
"""

from __future__ import annotations

import pytest

from app.enums import StatementType
from app.services.line_items import ITEM_BY_KEY, ITEMS_BY_STATEMENT


def _year(statement: dict, fiscal_year: int) -> dict:
    return {**statement, "fiscal_year": fiscal_year}


# --- The vocabulary the V2 models need ---------------------------------------


def test_every_input_the_v2_models_need_is_in_the_vocabulary():
    """A model that cannot name its own inputs cannot be fed them.

    Each key below is a direct input to a named published model: Beneish needs
    receivables, PP&E, SG&A, depreciation, long-term debt and income from
    continuing operations; Ohlson needs depreciation for its funds-from-operations
    proxy; the DCF needs cash, shares and a year-end price.
    """
    required = {
        "accounts_receivable",
        "accounts_payable",
        "ppe_net",
        "long_term_debt",
        "cash_and_equivalents",
        "shares_outstanding",
        "share_price",
        "pretax_income",
        "tax_expense",
        "sga_expense",
        "income_continuing_ops",
        "depreciation_amortization",
    }
    assert required <= set(ITEM_BY_KEY)


@pytest.mark.parametrize(
    ("key", "statement"),
    [
        ("accounts_receivable", StatementType.BALANCE_SHEET),
        ("ppe_net", StatementType.BALANCE_SHEET),
        ("sga_expense", StatementType.INCOME_STATEMENT),
        ("pretax_income", StatementType.INCOME_STATEMENT),
        ("depreciation_amortization", StatementType.CASH_FLOW),
    ],
)
def test_new_items_are_filed_under_the_statement_they_come_from(key, statement):
    assert key in {spec.key for spec in ITEMS_BY_STATEMENT[statement]}


def test_items_that_can_legitimately_go_negative_are_not_constrained():
    """A loss-making company must remain representable.

    ``pretax_income`` is negative for every company this tool exists to flag, and
    ``tax_expense`` goes negative whenever a loss produces a tax benefit. Marking
    either non-negative would reject exactly the filings that matter.
    """
    assert ITEM_BY_KEY["pretax_income"].non_negative is False
    assert ITEM_BY_KEY["tax_expense"].non_negative is False
    assert ITEM_BY_KEY["income_continuing_ops"].non_negative is False
    # And the ones that genuinely cannot be negative still are constrained.
    assert ITEM_BY_KEY["accounts_receivable"].non_negative is True
    assert ITEM_BY_KEY["ppe_net"].non_negative is True


# --- Backward compatibility ---------------------------------------------------


def test_upload_without_a_fiscal_year_inherits_the_companys_own(client, caterpillar):
    """Every V1 payload must still land unchanged. The sample filings are V1 payloads."""
    company_id = client.post("/companies", json=caterpillar["company"]).json()["id"]
    response = client.post(
        f"/companies/{company_id}/financial-statements", json=caterpillar["statements"][0]
    )
    assert response.status_code == 201
    assert response.json()["fiscal_year"] == 2024


def test_an_undated_statement_on_an_undated_company_is_refused(client, caterpillar):
    payload = {k: v for k, v in caterpillar["company"].items() if k != "fiscal_year"}
    company_id = client.post("/companies", json=payload).json()["id"]
    response = client.post(
        f"/companies/{company_id}/financial-statements", json=caterpillar["statements"][0]
    )
    assert response.status_code == 422
    assert "must be dated" in response.json()["detail"]


# --- The behaviour this item exists for ---------------------------------------


def test_two_years_do_not_merge_into_one_blob(client, load_company, caterpillar):
    """The load-bearing test for the whole V2 schema change.

    FY2023 is uploaded with deliberately different totals. If the engines merged
    across years, the later upload would overwrite FY2024's balance sheet and the
    ratios would describe no year at all.
    """
    company_id = load_company(caterpillar)
    prior = _year(
        {
            "statement_type": "BALANCE_SHEET",
            "line_items": {
                "total_assets": 87476,
                "current_assets": 46949,
                "current_liabilities": 34728,
                "total_liabilities": 67973,
                "shareholder_equity": 19503,
            },
        },
        2023,
    )
    assert (
        client.post(f"/companies/{company_id}/financial-statements", json=prior).status_code == 201
    )

    latest = client.get(f"/companies/{company_id}/line-items").json()
    assert latest["fiscal_year"] == 2024
    assert latest["fiscal_years_on_file"] == [2023, 2024]
    assert latest["line_items"]["total_assets"] == 87764, "FY2024 must not inherit FY2023"

    earlier = client.get(f"/companies/{company_id}/line-items?fiscal_year=2023").json()
    assert earlier["line_items"]["total_assets"] == 87476
    assert earlier["line_items"]["current_assets"] == 46949


def test_the_balance_check_is_scoped_to_the_year_being_uploaded(client, load_company, caterpillar):
    """A prior-year sheet must be checked against its own year, not against FY2024.

    Without year scoping, FY2023's liabilities would be validated against FY2024's
    equity and a perfectly well-formed filing would be rejected.
    """
    company_id = load_company(caterpillar)
    response = client.post(
        f"/companies/{company_id}/financial-statements",
        json=_year(
            {
                "statement_type": "BALANCE_SHEET",
                "line_items": {
                    "total_assets": 87476,
                    "total_liabilities": 67973,
                    "shareholder_equity": 19503,
                },
            },
            2023,
        ),
    )
    assert response.status_code == 201


def test_ratios_record_which_year_they_describe(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    body = client.post(f"/companies/{company_id}/compute-ratios").json()
    assert body["fiscal_year"] == 2024
    assert body["calculation_basis"]["fiscal_years_on_file"] == [2024]


def test_statements_can_be_limited_to_the_most_recent_years(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    client.post(
        f"/companies/{company_id}/financial-statements",
        json=_year({"statement_type": "INCOME_STATEMENT", "line_items": {"revenue": 67060}}, 2023),
    )
    every = client.get(f"/companies/{company_id}/financial-statements").json()
    assert {s["fiscal_year"] for s in every} == {2023, 2024}

    recent = client.get(f"/companies/{company_id}/financial-statements?years=1").json()
    assert {s["fiscal_year"] for s in recent} == {2024}
