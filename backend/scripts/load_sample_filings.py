#!/usr/bin/env python3
"""Load the sourced sample filings into a running FinSight 360 API.

    python backend/scripts/load_sample_filings.py --api http://localhost:8000
    python backend/scripts/load_sample_filings.py --v1-only

Two kinds of file live in data/sample_filings/: a base filing carries a
"company" block and one fiscal year; a companion carries "extends" and adds a
prior year without restating anything in the base file.

Base files load first, companions on top, analysis once at the end.
--v1-only skips the companions and reproduces the V1 single-year output.

Idempotent by name, so re-running does not duplicate a company and pollute the
peer median.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sample_filings"
MARKET_FILE = DATA_DIR.parent / "market_data" / "prices_monthly.json"


def request(method: str, url: str, payload: dict | None = None) -> Any:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=body, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{method} {url} -> HTTP {exc.code}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Cannot reach {url} ({exc.reason}). Start the API first: "
            "docker compose up, or uvicorn app.main:app --reload"
        ) from exc


def upload(api: str, company_id: str, statements: list[dict]) -> None:
    for statement in statements:
        request("POST", f"{api}/companies/{company_id}/financial-statements", statement)


def load_market(api: str) -> dict:
    """Load every security in the market file, and return its company listings."""
    if not MARKET_FILE.is_file():
        return {}
    market = json.loads(MARKET_FILE.read_text())
    source = market["provenance"]["source"]
    for ticker, security in market["securities"].items():
        request(
            "POST",
            f"{api}/market/securities",
            {
                "ticker": ticker,
                "name": security["name"],
                "currency": security["currency"],
                "exchange": security["exchange"],
                "sector": security["sector"],
                "source": source,
                "prices": security["prices"],
            },
        )
    print(f"  loaded {len(market['securities'])} securities from {MARKET_FILE.name}")
    return market.get("listings", {})


def report_market(api: str, name: str, company_id: str, listing: dict) -> None:
    """Link the listing, run the market stage, and print the Merton line."""
    request("PUT", f"{api}/companies/{company_id}/listing", listing)
    risk = request("POST", f"{api}/companies/{company_id}/compute-market-risk", {})
    pd = risk["merton_probability_of_default"]
    print(
        f"     Merton DD = {risk['merton_distance_to_default']} -> "
        f"PD = {'n/a' if pd is None else f'{pd:.2%}'}  |  market view: {risk['market_view']}"
        f"  |  beta (adj) = {risk['adjusted_beta']}"
    )


def report_one(api: str, name: str, company_id: str, expected: dict) -> None:
    """Run the whole pipeline and print the verdict beside the expected one."""
    report = request("POST", f"{api}/companies/{company_id}/run-full-analysis")
    context = report["structured_context"]
    risk, health = context["bankruptcy_risk"], context["health_score"]
    suite = context.get("risk_suite") or {}
    quality = context.get("earnings_quality") or {}

    mark = "OK " if risk["zone"] == expected.get("zone", risk["zone"]) else "!! "
    print(
        f"  {mark}{name}: {risk['model']} = {risk['score']} -> {risk['zone']} "
        f"(confidence {risk['confidence']}), health {health['overall_score']}, "
        f"narrative by {report['generated_by']}"
    )
    if suite:
        ohlson = suite.get("ohlson", {})
        probability = ohlson.get("probability")
        print(
            f"     Ohlson O = {ohlson.get('o_score')} -> "
            f"P(distress) = {probability if probability is None else f'{probability:.1%}'}"
            f"  |  consensus: {suite.get('consensus_verdict')}"
        )
    if quality:
        band = quality.get("f_score_band") or "no band (partial)"
        m_score = quality.get("beneish_m_score")
        flag = quality.get("manipulation_flag")
        print(
            f"     Piotroski F = {quality.get('piotroski_f_score')} ({band})  |  "
            f"Beneish M = {m_score if m_score is not None else 'withheld'}"
            + (f", manipulation flag {flag}" if m_score is not None else "")
        )
    if risk["omitted_components"]:
        print(
            f"     omitted Altman components: {[c['component'] for c in risk['omitted_components']]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000", help="base URL of the API")
    parser.add_argument(
        "--v1-only",
        action="store_true",
        help="skip the multi-year companion files and reproduce the V1 single-year output",
    )
    args = parser.parse_args()
    api = args.api.rstrip("/")

    files = [json.loads(path.read_text()) for path in sorted(DATA_DIR.glob("*.json"))]
    bases = [f for f in files if "company" in f]
    companions = [f for f in files if "extends" in f]
    if not bases:
        raise SystemExit(f"No base filings found in {DATA_DIR}")

    existing = {c["name"]: c["id"] for c in request("GET", f"{api}/companies")}
    print(
        f"Loading {len(bases)} base filing(s)"
        + ("" if args.v1_only else f" and {len(companions)} multi-year companion(s)")
        + f" into {api}"
    )

    listings = {} if args.v1_only else load_market(api)

    loaded: dict[str, str] = {}
    for filing in bases:
        name = filing["company"]["name"]
        if name in existing:
            print(f"  = {name}: already loaded, skipping")
            continue
        company = request("POST", f"{api}/companies", filing["company"])
        loaded[name] = company["id"]
        upload(api, company["id"], filing["statements"])

    if not args.v1_only:
        for companion in companions:
            name = companion["company_ref"]
            company_id = loaded.get(name)
            if company_id is None:
                print(f"  ! {name}: companion file has no loaded base filing, skipping")
                continue
            upload(api, company_id, companion["statements"])

    for filing in bases:
        name = filing["company"]["name"]
        if name in loaded:
            report_one(api, name, loaded[name], filing.get("expected", {}))
            if name in listings:
                report_market(api, name, loaded[name], listings[name])

    print(
        "\nDone. Peer-median benchmarks need at least 3 companies in the same industry; "
        "with 3 companies across 3 industries every health score here is computed against "
        "the ILLUSTRATIVE reference table. Attach a sourced peer set with "
        "POST /companies/{id}/peer-set to get a real percentile. "
        "See data/sample_filings/README.md."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
