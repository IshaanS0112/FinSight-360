"""Rehydrate stored analysis rows into the engines' dataclasses.

Needed because the insight report narrates what was *stored*, not a fresh
computation. Recomputing at narration time would open a gap between the numbers
the API returned and the numbers the narrative describes, which is precisely the
gap this project claims not to have.
"""

from __future__ import annotations

from app.enums import AltmanModel, ResultConfidence, Zone
from app.models import BankruptcyRisk, FinancialHealthScore
from app.services.altman_zscore import ZScoreResult
from app.services.health_score import HealthScoreResult


def zscore_result_from_row(row: BankruptcyRisk) -> ZScoreResult:
    basis = dict(row.calculation_basis or {})
    return ZScoreResult(
        model=AltmanModel(row.model),
        score=row.altman_z_score,
        zone=Zone(row.zone),
        confidence=ResultConfidence(row.confidence),
        components=dict(row.component_scores or {}),
        omitted_components=list(row.omitted_components or []),
        borderline=bool(basis.get("borderline", False)),
        calculation_basis=basis,
    )


def health_result_from_row(row: FinancialHealthScore) -> HealthScoreResult:
    return HealthScoreResult(
        overall_score=row.overall_score,
        component_scores=dict(row.component_scores or {}),
        peer_percentile=row.peer_percentile,
        confidence=ResultConfidence(row.confidence),
        calculation_basis=dict(row.calculation_basis or {}),
    )
