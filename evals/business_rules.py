from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evals.common import GoldenCase, deterministic_scores, mean


@dataclass(frozen=True)
class BusinessRuleResult:
    score: float
    passed: bool
    reason: str
    components: dict[str, float | None]


def evaluate_business_rules(
    case: GoldenCase,
    *,
    answer: str,
    documents: list[dict[str, Any]],
    threshold: float = 0.8,
) -> BusinessRuleResult:
    if not 0 <= threshold <= 1:
        raise ValueError("threshold phải nằm trong khoảng 0 đến 1.")

    components = deterministic_scores(
        case,
        answer=answer,
        documents=documents,
    )
    score = mean(components.values())
    final_score = float(score if score is not None else 1.0)
    failed = [
        name
        for name, value in components.items()
        if value is not None and value < 1
    ]
    reason = (
        "Đạt toàn bộ fact và hard constraint deterministic."
        if not failed
        else "Chưa đạt: " + ", ".join(failed)
    )
    return BusinessRuleResult(
        score=final_score,
        passed=final_score >= threshold,
        reason=reason,
        components=components,
    )
