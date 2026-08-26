import logging
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from academic_agents.assessment import AssessmentAgent
from academic_agents.verification import VerificationAgent
from assessment.bkt import update_bkt
from schemas.agents import AgentTraceEvent
from schemas.assessment import (
    AssessmentGrade,
    AssessmentQuestion,
    AssessmentQuestionBank,
    AssessmentSelection,
    AssessmentWorkflowResult,
    BKTParameters,
)


logger = logging.getLogger(__name__)


class AssessmentState(TypedDict, total=False):
    operation: Literal["select_question", "grade_answer"]
    bank: AssessmentQuestionBank
    mastery_by_concept: dict[str, float]
    attempt_count_by_question: dict[str, int]
    target_concept_id: str | None
    question: AssessmentQuestion
    selected_option_id: str
    selection: AssessmentSelection
    grade: AssessmentGrade
    verification_status: Literal["PASS", "BLOCK"]
    bkt_parameters: BKTParameters
    mastery_before: float
    mastery_after: float
    events: list[AgentTraceEvent]


class AcademicAssessmentWorkflow:
    """LangGraph workflow for adaptive question selection and grading."""

    def __init__(
        self,
        *,
        assessment_agent: AssessmentAgent,
        verification_agent: VerificationAgent,
        tracing_enabled: bool = False,
    ) -> None:
        self.assessment_agent = assessment_agent
        self.verification_agent = verification_agent
        self.tracing_enabled = tracing_enabled
        self.graph = self._compile_graph()

    @staticmethod
    def _append_event(
        state: AssessmentState,
        *,
        agent: str,
        action: str,
        status: str,
        details: dict | None = None,
    ) -> list[AgentTraceEvent]:
        events = list(state.get("events", []))
        events.append(
            AgentTraceEvent(
                sequence=len(events) + 1,
                agent=agent,
                action=action,
                status=status,
                details=details or {},
            )
        )
        logger.info(
            "Academic assessment agent action completed.",
            extra={
                "agent": agent,
                "tool": action,
                "agent_status": status,
                **(details or {}),
            },
        )
        return events

    def _compile_graph(self):
        builder = StateGraph(AssessmentState)
        builder.add_node("orchestrate", self._orchestrate_node)
        builder.add_node("select", self._select_node)
        builder.add_node("grade", self._grade_node)
        builder.add_node("verify_selection", self._verify_selection_node)
        builder.add_node("verify_grade", self._verify_grade_node)
        builder.add_node("update_mastery", self._update_mastery_node)
        builder.add_edge(START, "orchestrate")
        builder.add_conditional_edges(
            "orchestrate",
            lambda state: state["operation"],
            {
                "select_question": "select",
                "grade_answer": "grade",
            },
        )
        builder.add_edge("select", "verify_selection")
        builder.add_edge("grade", "verify_grade")
        builder.add_edge("verify_selection", END)
        builder.add_conditional_edges(
            "verify_grade",
            lambda state: (
                "update"
                if state.get("verification_status") == "PASS"
                else "end"
            ),
            {"update": "update_mastery", "end": END},
        )
        builder.add_edge("update_mastery", END)
        return builder.compile()

    def _orchestrate_node(self, state: AssessmentState) -> AssessmentState:
        operation = state["operation"]
        return {
            "events": self._append_event(
                state,
                agent="OrchestratorAgent",
                action="route_assessment_operation",
                status=operation,
            )
        }

    def _select_node(self, state: AssessmentState) -> AssessmentState:
        selection = self.assessment_agent.select_question(
            state["bank"],
            mastery_by_concept=state.get("mastery_by_concept", {}),
            attempt_count_by_question=state.get(
                "attempt_count_by_question",
                {},
            ),
            target_concept_id=state.get("target_concept_id"),
        )
        return {
            "selection": selection,
            "question": selection.question,
            "events": self._append_event(
                state,
                agent="AssessmentAgent",
                action="select_adaptive_question",
                status="completed",
                details={
                    "question_id": selection.question.question_id,
                    "concept_id": selection.question.concept_id,
                    "difficulty": selection.question.difficulty,
                },
            ),
        }

    def _grade_node(self, state: AssessmentState) -> AssessmentState:
        grade = self.assessment_agent.grade_answer(
            state["question"],
            selected_option_id=state["selected_option_id"],
        )
        return {
            "grade": grade,
            "events": self._append_event(
                state,
                agent="AssessmentAgent",
                action="grade_multiple_choice",
                status="completed",
                details={
                    "question_id": grade.question_id,
                    "is_correct": grade.is_correct,
                },
            ),
        }

    def _verify_selection_node(self, state: AssessmentState) -> AssessmentState:
        result = self.verification_agent.verify_assessment_question(
            state["question"]
        )
        return {
            "verification_status": (
                "PASS" if result.status == "PASS" else "BLOCK"
            ),
            "events": self._append_event(
                state,
                agent="VerificationAgent",
                action="verify_assessment_question",
                status=result.status,
                details={"critique": result.critique},
            ),
        }

    def _verify_grade_node(self, state: AssessmentState) -> AssessmentState:
        result = self.verification_agent.verify_assessment_grade(
            state["question"],
            state["grade"],
        )
        return {
            "verification_status": (
                "PASS" if result.status == "PASS" else "BLOCK"
            ),
            "events": self._append_event(
                state,
                agent="VerificationAgent",
                action="verify_assessment_grade",
                status=result.status,
                details={"critique": result.critique},
            ),
        }

    def _update_mastery_node(self, state: AssessmentState) -> AssessmentState:
        updated = update_bkt(
            state["mastery_before"],
            is_correct=state["grade"].is_correct,
            parameters=state["bkt_parameters"],
        )
        return {
            "mastery_after": updated,
            "events": self._append_event(
                state,
                agent="System",
                action="update_bkt_mastery",
                status="completed",
                details={
                    "concept_id": state["question"].concept_id,
                    "mastery_before": state["mastery_before"],
                    "mastery_after": updated,
                },
            ),
        }

    def _invoke(self, state: AssessmentState) -> AssessmentWorkflowResult:
        with tracing_context(enabled=self.tracing_enabled):
            final_state = self.graph.invoke(
                {**state, "events": []},
                config={
                    "recursion_limit": 8,
                    "run_name": "academic_assessment_multi_agent",
                    "tags": ["academic", "assessment", "multi-agent"],
                },
            )
        return AssessmentWorkflowResult(
            operation=final_state["operation"],
            verification_status=final_state.get(
                "verification_status",
                "BLOCK",
            ),
            selection=final_state.get("selection"),
            grade=final_state.get("grade"),
            mastery_before=final_state.get("mastery_before"),
            mastery_after=final_state.get("mastery_after"),
            agent_trace=final_state.get("events", []),
        )

    def select_question(
        self,
        bank: AssessmentQuestionBank,
        *,
        mastery_by_concept: dict[str, float],
        attempt_count_by_question: dict[str, int],
        target_concept_id: str | None = None,
    ) -> AssessmentWorkflowResult:
        return self._invoke(
            {
                "operation": "select_question",
                "bank": bank,
                "mastery_by_concept": mastery_by_concept,
                "attempt_count_by_question": attempt_count_by_question,
                "target_concept_id": target_concept_id,
            }
        )

    def grade_answer(
        self,
        question: AssessmentQuestion,
        *,
        selected_option_id: str,
        mastery_before: float,
        bkt_parameters: BKTParameters,
    ) -> AssessmentWorkflowResult:
        return self._invoke(
            {
                "operation": "grade_answer",
                "question": question,
                "selected_option_id": selected_option_id,
                "mastery_before": mastery_before,
                "bkt_parameters": bkt_parameters,
            }
        )
