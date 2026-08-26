import json
from pathlib import Path

from pydantic import ValidationError

from schemas.agents import (
    AcademicAgentEvaluationCase,
    AcademicAgentEvaluationReport,
    AcademicAssistantResponse,
)


def load_agent_evaluation_cases(
    path: str | Path,
) -> list[AcademicAgentEvaluationCase]:
    resolved_path = Path(path).resolve()
    try:
        with resolved_path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Không thể đọc agent evaluation cases: {path}") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("Agent evaluation cases phải là danh sách không rỗng.")
    try:
        cases = [
            AcademicAgentEvaluationCase.model_validate(item)
            for item in payload
        ]
    except ValidationError as exc:
        raise ValueError(f"Agent evaluation case không đúng schema: {exc}") from exc
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id trong agent evaluation phải duy nhất.")
    return cases


def _tool_was_called(response: AcademicAssistantResponse) -> bool:
    return any(
        event.agent == "KnowledgeAgent"
        and event.action == "search_and_answer"
        and event.details.get("tool_called") is True
        for event in response.agent_trace
    )


def _constraints_satisfied(response: AcademicAssistantResponse) -> bool:
    if response.revision_count > 2:
        return False
    if response.verification_status == "PASS" and not response.citations:
        return False
    if response.verification_status in {"BLOCK", "NOT_REQUIRED"} and (
        response.citations
    ):
        return False

    agents = [event.agent for event in response.agent_trace]
    if response.route == "knowledge":
        return all(
            agent in agents
            for agent in (
                "OrchestratorAgent",
                "KnowledgeAgent",
                "VerificationAgent",
            )
        )
    return "KnowledgeAgent" not in agents and "VerificationAgent" not in agents


def evaluate_academic_agent_workflow(
    workflow,
    cases: list[AcademicAgentEvaluationCase],
) -> AcademicAgentEvaluationReport:
    if not cases:
        raise ValueError("Cần ít nhất một agent evaluation case.")

    route_matches = 0
    tool_matches = 0
    verification_matches = 0
    constraint_matches = 0
    revision_total = 0
    loop_violation_count = 0
    case_results = []

    for case in cases:
        response = workflow.invoke(
            question=case.question,
            course_id=case.course_id,
            course_version=case.course_version,
            top_k=case.top_k,
        )
        tool_called = _tool_was_called(response)
        expected_tool_call = case.expected_route == "knowledge"
        constraints_ok = _constraints_satisfied(response)

        route_matches += int(response.route == case.expected_route)
        tool_matches += int(tool_called == expected_tool_call)
        verification_matches += int(
            response.verification_status
            == case.expected_verification_status
        )
        constraint_matches += int(constraints_ok)
        revision_total += response.revision_count
        loop_violation_count += int(response.revision_count > 2)
        case_results.append(
            {
                "case_id": case.case_id,
                "actual_route": response.route,
                "actual_verification_status": response.verification_status,
                "tool_called": tool_called,
                "revision_count": response.revision_count,
                "constraints_satisfied": constraints_ok,
            }
        )

    count = len(cases)
    return AcademicAgentEvaluationReport(
        case_count=count,
        routing_accuracy=round(route_matches / count, 6),
        tool_selection_accuracy=round(tool_matches / count, 6),
        verification_outcome_accuracy=round(
            verification_matches / count,
            6,
        ),
        constraint_satisfaction_rate=round(
            constraint_matches / count,
            6,
        ),
        average_revision_count=round(revision_total / count, 6),
        loop_violation_count=loop_violation_count,
        cases=case_results,
    )
