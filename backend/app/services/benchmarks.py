"""Comparison points for the health score.

⚠️ THE SHIPPED REFERENCE BANDS ARE ILLUSTRATIVE ROUND NUMBERS, NOT SOURCED
INDUSTRY DATA. They are plausible orders of magnitude so the engine has
something to compare against out of the box. They are not attributed to any
data provider, because inventing an attribution would be worse than admitting
the numbers are placeholders. This project does not claim a proprietary
industry-benchmark database, and the code reflects that.

Three paths to a comparison point, in precedence order:

1. **Peer median.** Load at least ``benchmark_min_peers`` other companies with
   the same ``industry`` string and the engine benchmarks against the median of
   their computed ratios. This is the intended path; the result records
   ``PEER_SET``.
2. **Your own table.** Point ``REFERENCE_BENCHMARKS_PATH`` at a JSON file of
   figures you actually sourced, keyed by industry.
3. **The built-in placeholders**, labelled as such in every response.

Median rather than mean throughout: peer sets are small, and one outlier
competitor should not move the comparison point.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from app.enums import BenchmarkBasis, RatioCategory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RatioRule:
    """One comparable ratio: which bucket it belongs to and which way is good."""

    key: str
    label: str
    category: RatioCategory
    higher_is_better: bool
    note: str = ""


RATIO_RULES: tuple[RatioRule, ...] = (
    RatioRule("current_ratio", "Current ratio", RatioCategory.LIQUIDITY, True),
    RatioRule("quick_ratio", "Quick ratio", RatioCategory.LIQUIDITY, True),
    RatioRule(
        "roe",
        "Return on equity",
        RatioCategory.PROFITABILITY,
        True,
        note="Meaningless when equity is negative; the engine reports it as unavailable, not as a large number.",
    ),
    RatioRule("roa", "Return on assets", RatioCategory.PROFITABILITY, True),
    RatioRule("net_margin", "Net margin", RatioCategory.PROFITABILITY, True),
    RatioRule("gross_margin", "Gross margin", RatioCategory.PROFITABILITY, True),
    RatioRule(
        "debt_to_equity",
        "Debt-to-equity",
        RatioCategory.LEVERAGE,
        False,
        note="Lower is better as a solvency signal. Undefined at negative equity.",
    ),
    RatioRule("interest_coverage", "Interest coverage", RatioCategory.LEVERAGE, True),
    RatioRule("asset_turnover", "Asset turnover", RatioCategory.EFFICIENCY, True),
    RatioRule(
        "inventory_turnover",
        "Inventory turnover",
        RatioCategory.EFFICIENCY,
        True,
        note="Undefined for a company holding effectively no inventory, which is normal for services.",
    ),
)

RULE_BY_KEY: dict[str, RatioRule] = {rule.key: rule for rule in RATIO_RULES}
RULES_BY_CATEGORY: dict[RatioCategory, tuple[RatioRule, ...]] = {
    category: tuple(r for r in RATIO_RULES if r.category is category) for category in RatioCategory
}


# ⚠️ Illustrative placeholders. See the module docstring.
_DEFAULT_REFERENCE_BANDS: dict[str, dict[str, float]] = {
    "_default": {
        "current_ratio": 1.5,
        "quick_ratio": 1.0,
        "roe": 12.0,
        "roa": 5.0,
        "net_margin": 8.0,
        "gross_margin": 35.0,
        "debt_to_equity": 1.0,
        "interest_coverage": 5.0,
        "asset_turnover": 0.8,
        "inventory_turnover": 6.0,
    },
    "industrial machinery": {
        "current_ratio": 1.4,
        "quick_ratio": 0.9,
        "roe": 18.0,
        "roa": 7.0,
        "net_margin": 10.0,
        "gross_margin": 30.0,
        "debt_to_equity": 1.5,
        "interest_coverage": 8.0,
        "asset_turnover": 0.8,
        "inventory_turnover": 3.0,
    },
    "it services": {
        "current_ratio": 2.2,
        "quick_ratio": 2.0,
        "roe": 25.0,
        "roa": 15.0,
        "net_margin": 15.0,
        "gross_margin": 30.0,
        "debt_to_equity": 0.2,
        "interest_coverage": 40.0,
        "asset_turnover": 1.1,
        "inventory_turnover": 100.0,
    },
    "telecom": {
        "current_ratio": 0.9,
        "quick_ratio": 0.7,
        "roe": 8.0,
        "roa": 3.0,
        "net_margin": 5.0,
        "gross_margin": 45.0,
        "debt_to_equity": 2.0,
        "interest_coverage": 2.5,
        "asset_turnover": 0.35,
        "inventory_turnover": 50.0,
    },
}

REFERENCE_PROVENANCE = (
    "ILLUSTRATIVE PLACEHOLDER BANDS - not sourced industry data. Load at least "
    "benchmark_min_peers companies in the same industry to benchmark against the "
    "peer median instead, or set REFERENCE_BENCHMARKS_PATH to your own sourced table."
)


def load_reference_bands(path: str | None = None) -> tuple[dict[str, dict[str, float]], str]:
    """Return ``(table, provenance)``.

    A missing or malformed override file falls back to the built-in table with a
    warning rather than raising: a benchmark table is an input to the analysis,
    not a hard dependency of the service starting.
    """
    if not path:
        return _DEFAULT_REFERENCE_BANDS, REFERENCE_PROVENANCE

    file_path = Path(path)
    if not file_path.is_file():
        logger.warning("REFERENCE_BENCHMARKS_PATH=%s does not exist; using built-in table", path)
        return _DEFAULT_REFERENCE_BANDS, REFERENCE_PROVENANCE

    try:
        payload: dict[str, Any] = json.loads(file_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s (%s); using built-in table", path, exc)
        return _DEFAULT_REFERENCE_BANDS, REFERENCE_PROVENANCE

    provenance = str(payload.pop("_provenance", f"user-supplied table: {file_path.name}"))
    table = {
        str(industry): {str(k): float(v) for k, v in bands.items()}
        for industry, bands in payload.items()
        if isinstance(bands, dict)
    }
    table.setdefault("_default", _DEFAULT_REFERENCE_BANDS["_default"])
    return table, provenance


def reference_band(
    table: dict[str, dict[str, float]], industry: str | None, ratio_key: str
) -> float | None:
    """Industry-specific band, falling back to the generic row."""
    key = (industry or "").strip().lower()
    for candidate in (key, "_default"):
        row = table.get(candidate)
        if row and ratio_key in row:
            return float(row[ratio_key])
    return None


def peer_median(peer_ratios: list[dict[str, float]], ratio_key: str, minimum: int) -> float | None:
    """Median of the peers that actually reported a value for ``ratio_key``.

    ``None`` when fewer than ``minimum`` peers have the ratio, which is the
    signal to fall back to the reference table.
    """
    values = [
        float(ratios[ratio_key])
        for ratios in peer_ratios
        if isinstance(ratios, dict)
        and isinstance(ratios.get(ratio_key), int | float)
        and not isinstance(ratios.get(ratio_key), bool)
    ]
    if len(values) < minimum:
        return None
    return float(median(values))


def resolve_benchmark(
    *,
    ratio_key: str,
    industry: str | None,
    peer_ratios: list[dict[str, float]],
    table: dict[str, dict[str, float]],
    minimum_peers: int,
) -> tuple[float | None, BenchmarkBasis]:
    """Peer median if there are enough peers, else the reference band, else nothing."""
    value = peer_median(peer_ratios, ratio_key, minimum_peers)
    if value is not None:
        return value, BenchmarkBasis.PEER_SET
    value = reference_band(table, industry, ratio_key)
    if value is not None:
        return value, BenchmarkBasis.REFERENCE_TABLE
    return None, BenchmarkBasis.UNAVAILABLE
