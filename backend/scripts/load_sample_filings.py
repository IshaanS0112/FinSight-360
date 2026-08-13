#!/usr/bin/env python3
"""Load the sourced sample filings into a running FinSight 360 API.

    python scripts/load_sample_filings.py --api http://localhost:8000

Idempotent by name: a company already present is skipped rather than duplicated,
so re-running after a restart does not silently create a second Caterpillar whose
ratios then pollute the peer median.

Prints the resulting zone next to the expected zone from each file, so the
validation result is visible from the command line and not only in the test
suite.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sample_filings"


def request(method: str, url: str, payload: dict | None = None) -> dict | list:
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


def load_one(api: str, path: Path, existing: dict[str, str]) -> None:
    payload = json.loads(path.read_text())
    meta, expected = payload["company"], payload.get("expected", {})

    if meta["name"] in existing:
        print(f"  = {meta['name']}: already loaded, skipping")
        return

    company = request("POST", f"{api}/companies", meta)
    company_id = company["id"]

    for statement in payload["statements"]:
        request("POST", f"{api}/companies/{company_id}/financial-statements", statement)

    report = request("POST", f"{api}/companies/{company_id}/run-full-analysis")
    context = report["structured_context"]
    risk, health = context["bankruptcy_risk"], context["health_score"]

    verdict = "OK " if risk["zone"] == expected.get("zone") else "!! "
    print(
        f"  {verdict}{meta['name']}: {risk['model']} = {risk['score']} -> {risk['zone']} "
        f"(expected {expected.get('zone', '?')}, confidence {risk['confidence']}), "
        f"health {health['overall_score']}, narrative by {report['generated_by']}"
    )
    if risk["omitted_components"]:
        print(f"     omitted components: {[c['component'] for c in risk['omitted_components']]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000", help="base URL of the API")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"No filings found in {DATA_DIR}")

    existing = {c["name"]: c["id"] for c in request("GET", f"{api}/companies")}
    print(f"Loading {len(files)} sample filing(s) into {api}")
    for path in files:
        load_one(api, path, existing)

    print(
        "\nDone. Peer-median benchmarks need at least 3 companies in the same industry; "
        "with 3 companies across 3 industries every health score here is computed against "
        "the ILLUSTRATIVE reference table. See data/sample_filings/README.md."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
