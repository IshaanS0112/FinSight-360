#!/usr/bin/env python3
"""Pull line items for a US filer straight from SEC XBRL - the primary source.

    python scripts/fetch_sec_filing.py --cik 18230 --fy 2024

The sample filings in ``data/sample_filings/`` were transcribed from standardised
statements rather than parsed from PDFs, and the README says so. This script is
the documented path to primary source, and it is what was used to verify
Caterpillar's FY2024 total assets against the 10-K itself.

Why it is a script and not a service: XBRL tag coverage differs by filer and by
year, so a human has to look at what came back and decide whether
``Revenues`` or ``RevenueFromContractWithCustomerExcludingAssessedTax`` is the
revenue line for this company. Automating that choice silently is how you end up
with a confident wrong number.

The SEC requires a descriptive User-Agent with a contact address. Set
``SEC_USER_AGENT`` before running or requests will be refused.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://data.sec.gov/api/xbrl/companyconcept"

# One or more candidate XBRL tags per line item, tried in order. Filers do not
# agree on which tag carries a given concept, and some switch between years.
TAG_CANDIDATES: dict[str, tuple[str, ...]] = {
    "total_assets": ("Assets",),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "total_liabilities": ("Liabilities",),
    "inventory": ("InventoryNet",),
    "shareholder_equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit",),
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "cogs": ("CostOfGoodsAndServicesSold", "CostOfRevenue"),
    "ebit": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "interest_expense": ("InterestExpense", "InterestExpenseNonoperating"),
}


def fetch_concept(cik: int, tag: str, user_agent: str) -> dict | None:
    url = f"{BASE}/CIK{cik:010d}/us-gaap/{tag}.json"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # filer does not use this tag
        raise SystemExit(f"GET {url} -> HTTP {exc.code}: {exc.read().decode(errors='replace')}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach {url}: {exc.reason}")


def pick_fy(payload: dict, fiscal_year: int) -> tuple[float, str] | None:
    """The value this filer reported for ``fiscal_year`` in its own 10-K.

    Restricted to ``form == "10-K"`` and ``fy == fiscal_year`` so a restated
    figure from a later filing does not silently replace the one as originally
    reported. Where several 10-K facts match, the latest filed wins - that is the
    filer's own most recent statement about that year.
    """
    best: tuple[float, str, str] | None = None
    for unit_facts in payload.get("units", {}).values():
        for fact in unit_facts:
            if fact.get("form") != "10-K" or fact.get("fy") != fiscal_year:
                continue
            filed = fact.get("filed", "")
            if best is None or filed > best[2]:
                best = (float(fact["val"]), f"{fact.get('end')} (filed {filed})", filed)
    return (best[0], best[1]) if best else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cik", type=int, required=True, help="e.g. 18230 for Caterpillar")
    parser.add_argument("--fy", type=int, required=True, help="fiscal year as the filer labels it")
    parser.add_argument("--scale", type=float, default=1e6, help="divide by this (default: report in millions)")
    args = parser.parse_args()

    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise SystemExit(
            "Set SEC_USER_AGENT to something like 'Your Name your@email.com'. The SEC "
            "refuses requests without a contact address, and rightly so."
        )

    print(f"CIK {args.cik:010d}, FY{args.fy}, values divided by {args.scale:,.0f}\n")
    found: dict[str, float] = {}
    for key, tags in TAG_CANDIDATES.items():
        for tag in tags:
            payload = fetch_concept(args.cik, tag, user_agent)
            if payload is None:
                continue
            hit = pick_fy(payload, args.fy)
            if hit is None:
                continue
            value, provenance = hit
            found[key] = round(value / args.scale, 2)
            print(f"  {key:22} {found[key]:>18,.2f}   [{tag}] {provenance}")
            break
        else:
            print(f"  {key:22} {'NOT FOUND':>18}   tried {list(tags)}")

    print("\nline_items block for a sample filing JSON:")
    print(json.dumps(found, indent=2, sort_keys=True))
    print(
        "\nCheck these against the filing before using them. Tag coverage varies by filer, "
        "interest expense is often only in the notes, and market value of equity is not an "
        "XBRL concept at all - it has to be sourced separately at the fiscal year end."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
