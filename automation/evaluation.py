import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from automation.policy import decide_replan
from schemas.automation import (
    AutomationEvaluationCase,
    AutomationEvaluationReport,
)


def load_automation_evaluation_cases(
    path: str | Path,
) -> list[AutomationEvaluationCase]:
    try:
        with Path(path).resolve().open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Khong the doc automation evaluation cases.") from exc
    try:
        cases = TypeAdapter(list[AutomationEvaluationCase]).validate_python(
            payload
        )
    except ValidationError as exc:
        raise ValueError(f"Automation evaluation sai schema: {exc}") from exc
    if not cases:
        raise ValueError("Can it nhat mot automation evaluation case.")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id trong automation evaluation phai duy nhat.")
    return cases


def evaluate_automation_policy(
    cases: list[AutomationEvaluationCase],
) -> AutomationEvaluationReport:
    if not cases:
        raise ValueError("Can it nhat mot automation evaluation case.")

    trigger_matches = 0
    proposal_matches = 0
    duplicate_cases = 0
    duplicate_prevented = 0
    approval_guard_matches = 0
    results = []
    for case in cases:
        decision = decide_replan(
            is_correct=case.is_correct,
            mastery_after=case.mastery_after,
            has_active_plan=case.has_active_plan,
            has_pending_replan=case.has_pending_replan,
        )
        trigger_match = (
            decision.replan_required == case.expected_replan_required
        )
        proposal_match = (
            decision.create_proposal == case.expected_create_proposal
        )
        trigger_matches += int(trigger_match)
        proposal_matches += int(proposal_match)
        if case.has_pending_replan:
            duplicate_cases += 1
            duplicate_prevented += int(not decision.create_proposal)

        # Activation belongs to the explicit approval endpoint, never policy.
        approval_guard_matches += int(not decision.auto_activate)
        results.append(
            {
                "case_id": case.case_id,
                "reason": decision.reason,
                "actual_replan_required": decision.replan_required,
                "actual_create_proposal": decision.create_proposal,
                "trigger_match": trigger_match,
                "proposal_match": proposal_match,
                "auto_activates": decision.auto_activate,
            }
        )

    count = len(cases)
    return AutomationEvaluationReport(
        case_count=count,
        trigger_accuracy=round(trigger_matches / count, 6),
        proposal_decision_accuracy=round(proposal_matches / count, 6),
        duplicate_prevention_rate=round(
            duplicate_prevented / duplicate_cases if duplicate_cases else 1.0,
            6,
        ),
        human_approval_compliance_rate=round(
            approval_guard_matches / count,
            6,
        ),
        cases=results,
    )


__all__ = [
    "evaluate_automation_policy",
    "load_automation_evaluation_cases",
]
