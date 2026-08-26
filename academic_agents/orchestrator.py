import logging
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from academic_agents.knowledge import KnowledgeAgent
from academic_agents.routing import OrchestratorAgent
from academic_agents.verification import VerificationAgent
from schemas.agents import (
    AcademicAssistantResponse,
    AgentCitation,
    AgentTraceEvent,
    KnowledgeAgentOutput,
    OrchestratorDecision,
    VerificationAgentOutput,
)


logger = logging.getLogger(__name__)
CITATION_PATTERN = re.compile(r"\[(\d+)\]")
DIRECT_ANSWER = (
    "Chào bạn! Mình có thể tra cứu và giải thích kiến thức trong môn bạn đã chọn, "
    "kèm citation để bạn đối chiếu tài liệu."
)
UNSUPPORTED_ANSWER = (
    "Yêu cầu này nằm ngoài phạm vi trợ lý học tập của môn đang chọn."
)
BLOCKED_ANSWER = (
    "Hệ thống chưa thể trả lời vì Verification Agent xác định evidence hoặc "
    "citation chưa đủ tin cậy."
)


class AcademicAgentState(TypedDict, total=False):
    question: str
    course_id: str
    course_version: str
    top_k: int
    route: str
    route_reason: str
    knowledge_output: KnowledgeAgentOutput
    verification_output: VerificationAgentOutput
    verification_status: str
    critique: str
    revision_count: int
    final_answer: str
    final_citations: list[AgentCitation]
    events: list[AgentTraceEvent]


class AcademicAgentWorkflow:
    """Controlled multi-agent workflow for grounded academic Q&A."""

    def __init__(
        self,
        *,
        orchestrator_agent: OrchestratorAgent,
        knowledge_agent: KnowledgeAgent,
        verification_agent: VerificationAgent,
        max_revisions: int = 2,
        tracing_enabled: bool = False,
    ) -> None:
        if max_revisions < 0 or max_revisions > 2:
            raise ValueError("max_revisions phải từ 0 đến 2.")
        self.orchestrator_agent = orchestrator_agent
        self.knowledge_agent = knowledge_agent
        self.verification_agent = verification_agent
        self.max_revisions = max_revisions
        self.tracing_enabled = tracing_enabled
        self.graph = self._compile_graph()

    @staticmethod
    def _append_event(
        state: AcademicAgentState,
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
            "Academic agent action completed.",
            extra={
                "agent": agent,
                "tool": action,
                "agent_status": status,
                **(details or {}),
            },
        )
        return events

    def _compile_graph(self):
        builder = StateGraph(AcademicAgentState)
        builder.add_node("orchestrate", self._orchestrate_node)
        builder.add_node("direct", self._direct_node)
        builder.add_node("unsupported", self._unsupported_node)
        builder.add_node("knowledge", self._knowledge_node)
        builder.add_node("verify", self._verification_node)

        builder.add_edge(START, "orchestrate")
        builder.add_conditional_edges(
            "orchestrate",
            self._route_after_orchestrator,
            {
                "direct": "direct",
                "unsupported": "unsupported",
                "knowledge": "knowledge",
            },
        )
        builder.add_edge("direct", END)
        builder.add_edge("unsupported", END)
        builder.add_edge("knowledge", "verify")
        builder.add_conditional_edges(
            "verify",
            self._route_after_verification,
            {
                "revise": "knowledge",
                "end": END,
            },
        )
        return builder.compile()

    def _orchestrate_node(
        self,
        state: AcademicAgentState,
    ) -> AcademicAgentState:
        decision: OrchestratorDecision = self.orchestrator_agent.route(
            question=state["question"],
            course_id=state["course_id"],
            course_version=state["course_version"],
        )
        return {
            "route": decision.route,
            "route_reason": decision.reason,
            "events": self._append_event(
                state,
                agent="OrchestratorAgent",
                action="route_request",
                status=decision.route,
                details={"reason": decision.reason},
            ),
        }

    @staticmethod
    def _route_after_orchestrator(state: AcademicAgentState) -> str:
        return state.get("route", "unsupported")

    def _direct_node(self, state: AcademicAgentState) -> AcademicAgentState:
        return {
            "final_answer": DIRECT_ANSWER,
            "final_citations": [],
            "verification_status": "NOT_REQUIRED",
            "events": self._append_event(
                state,
                agent="OrchestratorAgent",
                action="direct_response",
                status="completed",
            ),
        }

    def _unsupported_node(self, state: AcademicAgentState) -> AcademicAgentState:
        return {
            "final_answer": UNSUPPORTED_ANSWER,
            "final_citations": [],
            "verification_status": "BLOCK",
            "events": self._append_event(
                state,
                agent="OrchestratorAgent",
                action="block_unsupported_request",
                status="BLOCK",
            ),
        }

    def _knowledge_node(self, state: AcademicAgentState) -> AcademicAgentState:
        previous_output = state.get("knowledge_output")
        draft = self.knowledge_agent.answer(
            question=state["question"],
            course_id=state["course_id"],
            course_version=state["course_version"],
            top_k=state["top_k"],
            previous_retrieval=(
                previous_output.retrieval
                if previous_output is not None
                else None
            ),
            critique=state.get("critique"),
        )
        return {
            "knowledge_output": draft,
            "events": self._append_event(
                state,
                agent="KnowledgeAgent",
                action=(
                    "revise_grounded_answer"
                    if previous_output is not None
                    else "search_and_answer"
                ),
                status="completed",
                details={
                    "tool": "search_course_knowledge",
                    "tool_called": previous_output is None,
                    "evidence_count": len(draft.retrieval.hits),
                },
            ),
        }

    @staticmethod
    def _used_citations(draft: KnowledgeAgentOutput) -> list[AgentCitation]:
        used_numbers = {
            int(value)
            for value in CITATION_PATTERN.findall(draft.answer)
        }
        return [
            citation
            for citation in draft.citations
            if citation.number in used_numbers
        ]

    def _verification_node(
        self,
        state: AcademicAgentState,
    ) -> AcademicAgentState:
        draft = state["knowledge_output"]
        result = self.verification_agent.verify(
            draft,
            question=state["question"],
            course_id=state["course_id"],
            course_version=state["course_version"],
        )
        revision_count = int(state.get("revision_count", 0))
        if result.status == "REVISE":
            if revision_count >= self.max_revisions:
                result = VerificationAgentOutput(
                    status="BLOCK",
                    critique=(
                        "Đã đạt giới hạn sửa câu trả lời; không được tiếp tục loop."
                    ),
                )
            else:
                revision_count += 1

        response: AcademicAgentState = {
            "verification_output": result,
            "verification_status": result.status,
            "critique": result.critique,
            "revision_count": revision_count,
            "events": self._append_event(
                state,
                agent="VerificationAgent",
                action="verify_grounding",
                status=result.status,
                details={
                    "revision_count": revision_count,
                    "critique": result.critique,
                },
            ),
        }
        if result.status == "PASS":
            response["final_answer"] = draft.answer
            response["final_citations"] = self._used_citations(draft)
        elif result.status == "BLOCK":
            response["final_answer"] = BLOCKED_ANSWER
            response["final_citations"] = []
        return response

    @staticmethod
    def _route_after_verification(state: AcademicAgentState) -> str:
        return (
            "revise"
            if state.get("verification_status") == "REVISE"
            else "end"
        )

    def invoke(
        self,
        *,
        question: str,
        course_id: str,
        course_version: str,
        top_k: int = 5,
    ) -> AcademicAssistantResponse:
        if not question.strip():
            raise ValueError("question không được để trống.")
        if top_k <= 0 or top_k > 8:
            raise ValueError("top_k phải từ 1 đến 8.")
        with tracing_context(enabled=self.tracing_enabled):
            final_state = self.graph.invoke(
                {
                    "question": " ".join(question.split()),
                    "course_id": course_id,
                    "course_version": course_version,
                    "top_k": top_k,
                    "revision_count": 0,
                    "events": [],
                },
                config={
                    "recursion_limit": 12,
                    "run_name": "academic_multi_agent_qa",
                    "tags": ["academic", "multi-agent", course_id],
                    "metadata": {
                        "course_id": course_id,
                        "course_version": course_version,
                    },
                },
            )
        return AcademicAssistantResponse(
            course_id=course_id,
            course_version=course_version,
            route=final_state.get("route", "unsupported"),
            answer=final_state.get("final_answer", BLOCKED_ANSWER),
            citations=final_state.get("final_citations", []),
            verification_status=final_state.get(
                "verification_status",
                "BLOCK",
            ),
            revision_count=int(final_state.get("revision_count", 0)),
            agent_trace=final_state.get("events", []),
        )
