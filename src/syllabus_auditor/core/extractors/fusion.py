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


def make_row_candidate(
    section: str,
    source: str,
    rows: list[dict[str, Any]],
    required_fields: tuple[str, ...],
    *,
    warnings: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
) -> ExtractionCandidate:
    return ExtractionCandidate(
        section=section,
        source=source,
        rows=rows,
        warnings=list(warnings or []),
        evidence=dict(evidence or {}),
        score=score_rows(rows, required_fields),
    )


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
