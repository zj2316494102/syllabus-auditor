from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExtractionCandidate:
    section: str
    source: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


def row_completeness(rows: list[dict[str, Any]], required_fields: tuple[str, ...]) -> float:
    if not rows:
        return 0.0
    total = len(rows) * max(len(required_fields), 1)
    hits = sum(1 for row in rows for field in required_fields if str(row.get(field, "")).strip())
    return hits / total


def score_rows(rows: list[dict[str, Any]], required_fields: tuple[str, ...]) -> float:
    if not rows:
        return 0.0
    complete = row_completeness(rows, required_fields)
    row_bonus = min(len(rows), 20) / 20
    return complete * 80 + row_bonus * 20


def score_rows_weighted(
    rows: list[dict[str, Any]],
    *,
    required: tuple[str, ...],
    weighted: dict[str, int] | None = None,
    min_rows: int = 1,
    warning_penalty: int = 5,
    warnings: list[dict[str, Any]] | None = None,
) -> float:
    if not rows:
        return 0.0

    weighted = weighted or {}
    base = row_completeness(rows, required) * 50.0

    if weighted:
        weight_total = sum(weighted.values()) or 1
        weight_hits = sum(
            weight
            for row in rows
            for field, weight in weighted.items()
            if str(row.get(field, "")).strip()
        )
        base += (weight_hits / (len(rows) * weight_total)) * 30.0

    row_bonus = min(len(rows), 20) / 20 * 20.0
    if len(rows) < min_rows:
        base *= len(rows) / max(min_rows, 1)

    penalty = len(warnings or []) * warning_penalty
    return max(base + row_bonus - penalty, 0.0)


def make_row_candidate(
    section: str,
    source: str,
    rows: list[dict[str, Any]],
    required_fields: tuple[str, ...],
    *,
    warnings: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
    scoring_config: dict[str, Any] | None = None,
) -> ExtractionCandidate:
    if scoring_config:
        score = score_rows_weighted(
            rows,
            required=tuple(scoring_config.get("required") or required_fields),
            weighted=scoring_config.get("weighted") or {},
            min_rows=int(scoring_config.get("min_rows", 1)),
            warnings=warnings,
        )
    else:
        score = score_rows(rows, required_fields)

    return ExtractionCandidate(
        section=section,
        source=source,
        rows=rows,
        warnings=list(warnings or []),
        evidence=dict(evidence or {}),
        score=score,
    )


def apply_fusion_scoring(
    candidate: ExtractionCandidate,
    scoring_config: dict[str, Any] | None,
    *,
    required_fields: tuple[str, ...] = (),
) -> ExtractionCandidate:
    if not scoring_config:
        return candidate
    candidate.score = score_rows_weighted(
        candidate.rows,
        required=tuple(scoring_config.get("required") or required_fields),
        weighted=scoring_config.get("weighted") or {},
        min_rows=int(scoring_config.get("min_rows", 1)),
        warnings=candidate.warnings,
    )
    return candidate


def choose_candidate(
    current: ExtractionCandidate,
    alternatives: list[ExtractionCandidate],
    *,
    min_improvement: float = 8.0,
) -> ExtractionCandidate:
    selected = current
    for candidate in alternatives:
        if candidate.score <= 0:
            continue
        if selected.score <= 0 or candidate.score >= selected.score + min_improvement:
            selected = candidate
    return selected


def section_summary(selected: ExtractionCandidate, candidates: list[ExtractionCandidate]) -> dict[str, Any]:
    return {
        "selected_source": selected.source,
        "selected_score": round(selected.score, 2),
        "candidate_scores": [
            {
                "source": candidate.source,
                "score": round(candidate.score, 2),
                "rows": len(candidate.rows),
                "warnings": candidate.warnings,
            }
            for candidate in candidates
        ],
        "evidence": selected.evidence,
    }
