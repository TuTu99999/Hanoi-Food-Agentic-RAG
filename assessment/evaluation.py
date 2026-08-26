import json
from pathlib import Path

from pydantic import ValidationError

from assessment.bkt import update_bkt
from schemas.assessment import (
    AssessmentEvaluationReport,
    AssessmentEvaluationSuite,
    AssessmentQuestionBank,
)


def load_assessment_evaluation_suite(
    path: str | Path,
) -> AssessmentEvaluationSuite:
    try:
        with Path(path).resolve().open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Không thể đọc assessment evaluation cases.") from exc
    try:
        return AssessmentEvaluationSuite.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            f"Assessment evaluation cases không đúng schema: {exc}"
        ) from exc


def evaluate_assessment_workflow(
    workflow,
    bank: AssessmentQuestionBank,
    suite: AssessmentEvaluationSuite,
) -> AssessmentEvaluationReport:
    concept_matches = 0
    question_matches = 0
    grading_matches = 0
    verification_passes = 0
    verification_total = 0
    bkt_bounded = 0
    case_results = []

    for case in suite.selection_cases:
        result = workflow.select_question(
            bank,
            mastery_by_concept=case.mastery_by_concept,
            attempt_count_by_question=case.attempt_count_by_question,
            target_concept_id=case.target_concept_id,
        )
        selected = result.selection.question if result.selection else None
        concept_match = bool(
            selected and selected.concept_id == case.expected_concept_id
        )
        question_match = bool(
            selected and selected.question_id == case.expected_question_id
        )
        passed = result.verification_status == "PASS"
        concept_matches += int(concept_match)
        question_matches += int(question_match)
        verification_passes += int(passed)
        verification_total += 1
        case_results.append(
            {
                "case_id": case.case_id,
                "case_type": "selection",
                "actual_concept_id": selected.concept_id if selected else None,
                "actual_question_id": selected.question_id if selected else None,
                "concept_match": concept_match,
                "question_match": question_match,
                "verification_status": result.verification_status,
            }
        )

    questions = {question.question_id: question for question in bank.questions}
    for case in suite.grading_cases:
        question = questions.get(case.question_id)
        if question is None:
            raise ValueError(
                f"Evaluation tham chiếu question_id không tồn tại: {case.question_id}"
            )
        result = workflow.grade_answer(
            question,
            selected_option_id=case.selected_option_id,
            mastery_before=bank.bkt.p_initial,
            bkt_parameters=bank.bkt,
        )
        grade_match = bool(
            result.grade
            and result.grade.is_correct == case.expected_is_correct
        )
        passed = result.verification_status == "PASS"
        grading_matches += int(grade_match)
        verification_passes += int(passed)
        verification_total += 1
        updated = result.mastery_after
        if updated is None:
            updated = update_bkt(
                bank.bkt.p_initial,
                is_correct=False,
                parameters=bank.bkt,
            )
        bounded = 0 <= updated <= 1
        bkt_bounded += int(bounded)
        case_results.append(
            {
                "case_id": case.case_id,
                "case_type": "grading",
                "actual_is_correct": (
                    result.grade.is_correct if result.grade else None
                ),
                "grading_match": grade_match,
                "verification_status": result.verification_status,
                "bkt_after": updated,
                "bkt_bounded": bounded,
            }
        )

    selection_count = len(suite.selection_cases)
    grading_count = len(suite.grading_cases)
    return AssessmentEvaluationReport(
        selection_case_count=selection_count,
        grading_case_count=grading_count,
        concept_selection_accuracy=(
            round(concept_matches / selection_count, 6)
            if selection_count
            else 0.0
        ),
        question_selection_accuracy=(
            round(question_matches / selection_count, 6)
            if selection_count
            else 0.0
        ),
        grading_accuracy=(
            round(grading_matches / grading_count, 6)
            if grading_count
            else 0.0
        ),
        verification_pass_rate=(
            round(verification_passes / verification_total, 6)
            if verification_total
            else 0.0
        ),
        bkt_boundedness_rate=(
            round(bkt_bounded / grading_count, 6)
            if grading_count
            else 0.0
        ),
        cases=case_results,
    )
