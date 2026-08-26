import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from schemas.planning import (
    LearningMap,
    PlanningEvaluationCase,
    PlanningEvaluationReport,
)


def load_planning_evaluation_cases(
    path: str | Path,
) -> list[PlanningEvaluationCase]:
    try:
        with Path(path).resolve().open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Không thể đọc planning evaluation cases.") from exc
    try:
        cases = TypeAdapter(list[PlanningEvaluationCase]).validate_python(payload)
    except ValidationError as exc:
        raise ValueError(f"Planning evaluation không đúng schema: {exc}") from exc
    if not cases:
        raise ValueError("Cần ít nhất một planning evaluation case.")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id trong planning evaluation phải duy nhất.")
    return cases


def evaluate_planning_workflow(
    workflow,
    learning_map: LearningMap,
    cases: list[PlanningEvaluationCase],
) -> PlanningEvaluationReport:
    if not cases:
        raise ValueError("Cần ít nhất một planning evaluation case.")
    known = {concept.concept_id: concept for concept in learning_map.concepts}
    outcome_matches = 0
    priority_matches = 0
    capacity_matches = 0
    prerequisite_matches = 0
    coverage_total = 0.0
    results = []

    for case in cases:
        result = workflow.create_plan(
            learning_map,
            mastery_by_concept=case.mastery_by_concept,
            mastery_threshold=case.mastery_threshold,
            initial_mastery=case.initial_mastery,
            start_date=case.start_date,
            target_date=case.target_date,
            study_days=case.study_days,
            minutes_per_day=case.minutes_per_day,
            focus_concept_ids=case.focus_concept_ids,
        )
        draft = result.draft
        outcome_match = result.verification_status == case.expected_status
        priority_match = (
            draft.priority_concept_ids
            == case.expected_priority_concept_ids
        )
        daily_totals = {}
        sequences = {}
        for item in draft.items:
            daily_totals[item.study_date] = (
                daily_totals.get(item.study_date, 0) + item.duration_minutes
            )
            sequences.setdefault(item.concept_id, []).append(item.sequence)
        capacity_ok = all(
            total <= draft.minutes_per_day
            for total in daily_totals.values()
        )
        prerequisite_ok = True
        for concept_id, concept_sequences in sequences.items():
            for prerequisite_id in known[concept_id].prerequisite_ids:
                if (
                    prerequisite_id not in sequences
                    or max(sequences[prerequisite_id]) >= min(concept_sequences)
                ):
                    prerequisite_ok = False
        covered = set(sequences)
        expected = set(draft.priority_concept_ids)
        coverage = len(covered & expected) / len(expected) if expected else 1.0

        outcome_matches += int(outcome_match)
        priority_matches += int(priority_match)
        capacity_matches += int(capacity_ok)
        prerequisite_matches += int(prerequisite_ok)
        coverage_total += coverage
        results.append(
            {
                "case_id": case.case_id,
                "actual_status": result.verification_status,
                "actual_priority_concept_ids": draft.priority_concept_ids,
                "outcome_match": outcome_match,
                "priority_match": priority_match,
                "daily_capacity_ok": capacity_ok,
                "prerequisite_order_ok": prerequisite_ok,
                "concept_coverage": round(coverage, 6),
            }
        )

    count = len(cases)
    return PlanningEvaluationReport(
        case_count=count,
        verification_outcome_accuracy=round(outcome_matches / count, 6),
        priority_selection_accuracy=round(priority_matches / count, 6),
        daily_capacity_compliance_rate=round(capacity_matches / count, 6),
        prerequisite_order_compliance_rate=round(
            prerequisite_matches / count,
            6,
        ),
        concept_coverage_rate=round(coverage_total / count, 6),
        cases=results,
    )
