"""The closed set of financial line items the engines understand.

Two jobs.

**A vocabulary.** Filings do not agree on names - "Cost of Revenue" and "Cost of
Goods Sold" are the same line, "Total Common Shareholders' Equity" and
"Shareholders' Equity" are not. Declaring the accepted keys in one place means a
typo in an upload is a rejected request rather than a ratio that silently
evaluates to ``None``.

**Safe reads.** ``get`` returns ``None`` for a missing item and never coerces a
missing value to zero. That distinction is the whole difference between "this
company reported no inventory" and "we do not know this company's inventory",
and every ratio downstream depends on it. A quick ratio computed with inventory
silently defaulted to 0 equals the current ratio, which is a wrong number that
looks completely reasonable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.enums import StatementType


@dataclass(frozen=True)
class LineItemSpec:
    key: str
    label: str
    statement: StatementType
    # Some line items cannot be negative in a well-formed filing. Total assets
    # cannot. Retained earnings absolutely can, and rejecting that would make
    # the system unable to read exactly the distressed companies it exists to
    # score.
    non_negative: bool = False
    note: str = ""


BALANCE_SHEET_ITEMS: tuple[LineItemSpec, ...] = (
    LineItemSpec("total_assets", "Total assets", StatementType.BALANCE_SHEET, non_negative=True),
    LineItemSpec(
        "current_assets", "Total current assets", StatementType.BALANCE_SHEET, non_negative=True
    ),
    LineItemSpec(
        "current_liabilities",
        "Total current liabilities",
        StatementType.BALANCE_SHEET,
        non_negative=True,
    ),
    LineItemSpec(
        "total_liabilities", "Total liabilities", StatementType.BALANCE_SHEET, non_negative=True
    ),
    LineItemSpec("inventory", "Inventory", StatementType.BALANCE_SHEET, non_negative=True),
    LineItemSpec(
        "shareholder_equity",
        "Total shareholders' equity",
        StatementType.BALANCE_SHEET,
        note="Can be negative. Vodafone Idea FY2024 reports -1,041,668m INR.",
    ),
    LineItemSpec(
        "retained_earnings",
        "Retained earnings / accumulated deficit",
        StatementType.BALANCE_SHEET,
        note="Negative for any company with cumulative losses; that is the X2 signal, not an error.",
    ),
    LineItemSpec("total_debt", "Total debt", StatementType.BALANCE_SHEET, non_negative=True),
    LineItemSpec(
        "market_value_equity",
        "Market value of equity",
        StatementType.BALANCE_SHEET,
        non_negative=True,
        note=(
            "Not a balance sheet line. Required only by Altman Z (1968), where X4 "
            "uses market rather than book equity, and it must be measured at the "
            "fiscal year end, not today. Absent it, the engine reports Z' instead "
            "of substituting book equity into the 1968 coefficients."
        ),
    ),
    # --- V2 additions -------------------------------------------------------
    # Each is a direct input to a named V2 model, for two fiscal years.
    LineItemSpec(
        "accounts_receivable",
        "Trade and other receivables, current",
        StatementType.BALANCE_SHEET,
        non_negative=True,
        note="Beneish DSRI and the cash conversion cycle's DSO term.",
    ),
    LineItemSpec(
        "accounts_payable",
        "Trade and other payables, current",
        StatementType.BALANCE_SHEET,
        non_negative=True,
        note="The cash conversion cycle's DPO term.",
    ),
    LineItemSpec(
        "ppe_net",
        "Property, plant and equipment, net",
        StatementType.BALANCE_SHEET,
        non_negative=True,
        note="Beneish AQI and DEPI. Net of accumulated depreciation, as reported.",
    ),
    LineItemSpec(
        "long_term_debt",
        "Long-term debt, non-current portion",
        StatementType.BALANCE_SHEET,
        non_negative=True,
        note=(
            "Piotroski test 5 and Beneish LVGI. A subset of total_debt, not a "
            "synonym for it: total_debt also carries short-term borrowings and "
            "current maturities."
        ),
    ),
    LineItemSpec(
        "cash_and_equivalents",
        "Cash and cash equivalents",
        StatementType.BALANCE_SHEET,
        non_negative=True,
        note="Net debt for the DCF bridge from enterprise value to equity value.",
    ),
    LineItemSpec(
        "shares_outstanding",
        "Shares outstanding",
        StatementType.BALANCE_SHEET,
        non_negative=True,
        note=(
            "Not a balance sheet line; it sits on the cover page or in the equity "
            "note. Carried here because Piotroski test 7 compares it year on year "
            "and the DCF divides equity value by it. Supply it in the same unit "
            "scale as every other figure in the filing."
        ),
    ),
    LineItemSpec(
        "share_price",
        "Share price at fiscal year end",
        StatementType.BALANCE_SHEET,
        non_negative=True,
        note=(
            "The closing price on the last day of the fiscal year, not today's. "
            "Used only to state the DCF's implied value as an upside or downside; "
            "no analysis depends on it. See docs/architecture.md on why this is a "
            "filing-date figure rather than a live market feed."
        ),
    ),
)

INCOME_STATEMENT_ITEMS: tuple[LineItemSpec, ...] = (
    LineItemSpec("revenue", "Revenue", StatementType.INCOME_STATEMENT, non_negative=True),
    LineItemSpec("cogs", "Cost of revenue", StatementType.INCOME_STATEMENT, non_negative=True),
    LineItemSpec("gross_profit", "Gross profit", StatementType.INCOME_STATEMENT),
    LineItemSpec(
        "ebit",
        "Operating income (EBIT)",
        StatementType.INCOME_STATEMENT,
        note="Operating income is used as EBIT. See docs/architecture.md on why that is not always identical.",
    ),
    LineItemSpec("net_income", "Net income", StatementType.INCOME_STATEMENT),
    LineItemSpec(
        "interest_expense",
        "Interest expense",
        StatementType.INCOME_STATEMENT,
        non_negative=True,
        note="Supplied as a positive magnitude; filings often present it as a negative.",
    ),
    # --- V2 additions -----------------------------------------------------
    LineItemSpec(
        "pretax_income",
        "Profit before tax",
        StatementType.INCOME_STATEMENT,
        note="Negative for any loss-making company. DuPont's tax and interest burden terms.",
    ),
    LineItemSpec(
        "tax_expense",
        "Income tax expense",
        StatementType.INCOME_STATEMENT,
        note="Can be negative: a tax benefit is a real and common outcome for a loss year.",
    ),
    LineItemSpec(
        "sga_expense",
        "Selling, general and administrative expense",
        StatementType.INCOME_STATEMENT,
        non_negative=True,
        note="Beneish SGAI.",
    ),
    LineItemSpec(
        "income_continuing_ops",
        "Income from continuing operations",
        StatementType.INCOME_STATEMENT,
        note=(
            "Beneish TATA's numerator. Distinct from net income wherever a company "
            "reports discontinued operations, which is exactly when the accrual "
            "signal Beneish is looking for would otherwise be distorted."
        ),
    ),
)

CASH_FLOW_ITEMS: tuple[LineItemSpec, ...] = (
    LineItemSpec("operating_cash_flow", "Cash flow from operations", StatementType.CASH_FLOW),
    LineItemSpec("capital_expenditure", "Capital expenditure", StatementType.CASH_FLOW),
    LineItemSpec(
        "depreciation_amortization",
        "Depreciation and amortisation",
        StatementType.CASH_FLOW,
        non_negative=True,
        note=(
            "Supplied as a positive magnitude, as the cash flow statement adds it "
            "back. Ohlson's FUTL proxy, Beneish DEPI, and the DCF's FCFF bridge."
        ),
    ),
)

ALL_ITEMS: tuple[LineItemSpec, ...] = BALANCE_SHEET_ITEMS + INCOME_STATEMENT_ITEMS + CASH_FLOW_ITEMS
ITEM_BY_KEY: dict[str, LineItemSpec] = {spec.key: spec for spec in ALL_ITEMS}

ITEMS_BY_STATEMENT: dict[StatementType, tuple[LineItemSpec, ...]] = {
    StatementType.BALANCE_SHEET: BALANCE_SHEET_ITEMS,
    StatementType.INCOME_STATEMENT: INCOME_STATEMENT_ITEMS,
    StatementType.CASH_FLOW: CASH_FLOW_ITEMS,
}


def is_number(value: Any) -> bool:
    """``True`` for real numbers only.

    ``isinstance(True, int)`` is ``True`` in Python, so a JSON payload with
    ``"total_assets": true`` would otherwise sail through and produce a total
    assets figure of 1.
    """
    return isinstance(value, int | float) and not isinstance(value, bool)


def get(items: dict[str, Any], key: str) -> float | None:
    """Read a line item, or ``None`` if it was not reported.

    Never returns 0.0 as a stand-in for a missing value.
    """
    value = items.get(key)
    return float(value) if is_number(value) else None


def merge_statements(statements: list[tuple[str, dict[str, Any]]]) -> dict[str, float]:
    """Flatten the latest value of every reported line item across statements.

    Later statements win on key collision, which is why the caller passes them
    in upload order. In practice the three statement types do not share keys,
    with one exception: re-uploading a corrected balance sheet should supersede
    the original, and it does.
    """
    merged: dict[str, float] = {}
    for _statement_type, items in statements:
        for key, value in (items or {}).items():
            if key in ITEM_BY_KEY and is_number(value):
                merged[key] = float(value)
    return merged


def derive_gross_profit(items: dict[str, float]) -> float | None:
    """Gross profit, taken as reported or derived from revenue - COGS.

    Derivation is safe here because the identity is definitional, and it is
    worth doing because gross margin is one of the headline profitability ratios
    and filings frequently omit it while reporting both of its inputs.
    """
    reported = get(items, "gross_profit")
    if reported is not None:
        return reported
    revenue, cogs = get(items, "revenue"), get(items, "cogs")
    if revenue is None or cogs is None:
        return None
    return revenue - cogs


def working_capital(items: dict[str, float]) -> float | None:
    current_assets = get(items, "current_assets")
    current_liabilities = get(items, "current_liabilities")
    if current_assets is None or current_liabilities is None:
        return None
    return current_assets - current_liabilities
