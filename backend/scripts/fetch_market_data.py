#!/usr/bin/env python3
"""Regenerate data/market_data/prices_monthly.json from the Yahoo Finance chart API.

    python backend/scripts/fetch_market_data.py
    python backend/scripts/fetch_market_data.py --start 2019-01 --end 2024-12

A setup-time script, not a service: nothing in the application fetches prices at
request time. Re-running it rewrites the file, so diff the result before
committing it - a changed historical price means the source restated it.
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent.parent / "data" / "market_data" / "prices_monthly.json"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1mo&period1={p1}&period2={p2}"
EXCHANGES = {"NYQ": "NYSE", "NMS": "NASDAQ", "PCX": "NYSE Arca", "NSI": "NSE"}


def month(text: str) -> tuple[int, int]:
    year, mon = text.split("-")
    return int(year), int(mon)


def fetch(ticker: str, start: tuple[int, int], end: tuple[int, int]) -> dict:
    """Month-end close and adjusted close for one ticker, labelled by month-end date."""
    p1 = calendar.timegm((start[0], start[1], 1, 0, 0, 0))
    p2 = calendar.timegm((end[0] + (end[1] == 12), end[1] % 12 + 1, 1, 0, 0, 0))
    request = urllib.request.Request(
        CHART.format(ticker=ticker, p1=p1, p2=p2),
        headers={"User-Agent": "Mozilla/5.0 FinSight360-market-data"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read())["chart"]["result"][0]

    quote, adjusted = result["indicators"]["quote"][0], result["indicators"]["adjclose"][0]
    rows = []
    for stamp, close, adj in zip(
        result["timestamp"], quote["close"], adjusted["adjclose"], strict=False
    ):
        moment = time.gmtime(stamp)
        key = (moment.tm_year, moment.tm_mon)
        if close is None or adj is None or not start <= key <= end:
            continue
        last = calendar.monthrange(*key)[1]
        rows.append(
            {
                "date": f"{key[0]:04d}-{key[1]:02d}-{last:02d}",
                "close": round(close, 4),
                "adj_close": round(adj, 4),
            }
        )
    meta = result["meta"]
    return {
        "name": meta.get("longName") or meta.get("shortName"),
        "currency": meta.get("currency"),
        "exchange": EXCHANGES.get(meta.get("exchangeName"), meta.get("exchangeName")),
        "prices": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2019-01")
    parser.add_argument("--end", default="2024-12")
    args = parser.parse_args()

    current = json.loads(OUT.read_text())
    start, end = month(args.start), month(args.end)
    for ticker, security in current["securities"].items():
        fresh = fetch(ticker, start, end)
        security.update({k: fresh[k] for k in ("name", "currency", "exchange", "prices")})
        print(f"  {ticker:8} {fresh['currency']} {len(fresh['prices'])} months")
        time.sleep(0.5)

    current["provenance"]["retrieved"] = date.today().isoformat()
    current["provenance"]["period"] = f"{args.start} to {args.end}"
    OUT.write_text(json.dumps(current, indent=1))
    print(f"\nWrote {OUT}. Diff it before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
