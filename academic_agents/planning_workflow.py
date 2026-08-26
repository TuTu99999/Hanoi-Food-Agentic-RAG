import logging
from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from academic_agents.planning import PlanningAgent
from academic_agents.verification import VerificationAgent
from schemas.agents import AgentTraceEvent
from schemas.planning import (
    LearningMap,
    LearningPlanDraft,
    PlanningWorkflowResult,
)


logger = logging.getLogger(__name__)


class PlanningState(TypedDict, total=False):
    operation: str
    learning_map: LearningMap
    mastery_by_concept: dict[str, float]
    mastery_threshold: float
    initial_mastery: float
    start_date: date
    target_date: date
    study_days: int
    minutes_per_day: int
    focus_concept_ids: list[str]
    draft: LearningPlanDraft
    verification_status: str
    critique: str
    events: list[AgentTraceEvent]


class AcademicPlanningWorkflow:
    def __init__(
        self,
        *,
        planning_agent: PlanningAgent,
        verification_agent: VerificationAgent,
        tracing_enabled: bool = False,
    ) -> None:
        self.planning_agent = planning_agent
        self.verification_agent = verification_agent
        self.tracing_enabled = tracing_enabled
        self.graph = self._compile_graph()

    @staticmethod
    def _append_event(
        state: PlanningState,
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
            "Academic planning agent action completed.",
            extra={
                "agent": agent,
                "tool": action,
                "agent_status": status,
                **(details or {}),
            },
        )
        return events

    def _compile_graph(self):
        builder = StateGraph(PlanningState)
        builder.add_node("orchestrate", self._orchestrate_node)
        builder.add_node("plan", self._plan_node)
        builder.add_node("verify", self._verify_node)
        builder.add_edge(START, "orchestrate")
        builder.add_edge("orchestrate", "plan")
        builder.add_edge("plan", "verify")
        builder.add_edge("verify", END)
        return builder.compile()

    def _orchestrate_node(self, state: PlanningState) -> PlanningState:
        return {
            "events": self._append_event(
                state,
                agent="OrchestratorAgent",
                action="route_planning_request",
                status="create_plan",
            )
        }

    def _plan_node(self, state: PlanningState) -> PlanningState:
        draft = self.planning_agent.create_plan(
            state["learning_map"],
            mastery_by_concept=state["mastery_by_concept"],
            mastery_threshold=state["mastery_threshold"],
            initial_mastery=state["initial_mastery"],
            start_date=state["start_date"],
            target_date=state["target_date"],
            study_days=state["study_days"],
            minutes_per_day=state["minutes_per_day"],
            focus_concept_ids=state.get("focus_concept_ids"),
        )
        return {
            "draft": draft,
            "events": self._append_event(
                state,
                agent="PlanningAgent",
                action="build_mastery_aware_plan",
                status="completed",
                details={
                    "concept_count": len(draft.priority_concept_ids),
                    "scheduled_minutes": draft.scheduled_minutes,
                    "capacity_minutes": draft.capacity_minutes,
                },
            ),
        }

    def _verify_node(self, state: PlanningState) -> PlanningState:
        result = self.verification_agent.verify_learning_plan(
            state["draft"],
            state["learning_map"],
        )
        status = "PASS" if result.status == "PASS" else "BLOCK"
        return {
            "verification_status": status,
            "critique": result.critique,
            "events": self._append_event(
                state,
                agent="VerificationAgent",
                action="verify_learning_plan_constraints",
                status=status,
                details={"critique": result.critique},
            ),
        }

    def create_plan(
        self,
        learning_map: LearningMap,
        *,
        mastery_by_concept: dict[str, float],
        mastery_threshold: float,
        start_date: date,
        target_date: date,
        study_days: int,
        minutes_per_day: int,
        focus_concept_ids: list[str] | None = None,
        initial_mastery: float = 0.2,
    ) -> PlanningWorkflowResult:
        with tracing_context(enabled=self.tracing_enabled):
            final_state = self.graph.invoke(
                {
                    "operation": "create_plan",
                    "learning_map": learning_map,
                    "mastery_by_concept": mastery_by_concept,
                    "mastery_threshold": mastery_threshold,
                    "initial_mastery": initial_mastery,
                    "start_date": start_date,
                    "target_date": target_date,
                    "study_days": study_days,
                    "minutes_per_day": minutes_per_day,
                    "focus_concept_ids": focus_concept_ids or [],
                    "events": [],
                },
                config={
                    "recursion_limit": 8,
                    "run_name": "academic_planning_multi_agent",
                    "tags": ["academic", "planning", "multi-agent"],
                },
            )
        return PlanningWorkflowResult(
            verification_status=final_state.get("verification_status", "BLOCK"),
            critique=final_state.get("critique", "Kế hoạch chưa được xác minh."),
            draft=final_state["draft"],
            agent_trace=final_state.get("events", []),
        )
