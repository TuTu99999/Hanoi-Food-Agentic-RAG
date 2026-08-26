from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.agents import AgentTraceEvent


LearningEventType = Literal[
    "MASTERY_UPDATED",
    "REPLAN_REQUIRED",
    "PLAN_PROPOSED",
    "PLAN_APPROVED",
]
ReplanReason = Literal[
    "NO_ACTIVE_PLAN",
    "ANSWER_CORRECT",
    "MASTERY_NOT_WEAK",
    "WEAKNESS_DETECTED",
    "PENDING_REPLAN_EXISTS",
    "REPLAN_BLOCKED",
]


class AutomationOutcome(BaseModel):
    """Observable result of the closed-loop policy after one answer."""

    model_config = ConfigDict(extra="forbid")

    mastery_event_id: str
    replan_required: bool
    reason: ReplanReason
    proposed_plan_id: str | None = None
    reused_existing_proposal: bool = False
    message: str = Field(min_length=1, max_length=1000)
    agent_trace: list[AgentTraceEvent] = Field(default_factory=list)


class LearningEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    course_id: str
    course_version: str
    event_type: LearningEventType
    aggregate_type: str
    aggregate_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any]
    created_at: datetime


class LearningEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[LearningEventResponse]


class ReplanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replan_required: bool
    create_proposal: bool
    auto_activate: Literal[False] = False
    reason: ReplanReason


class AutomationEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    is_correct: bool
    mastery_after: float = Field(ge=0.0, le=1.0)
    has_active_plan: bool
    has_pending_replan: bool = False
    expected_replan_required: bool
    expected_create_proposal: bool


class AutomationEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    trigger_accuracy: float = Field(ge=0.0, le=1.0)
    proposal_decision_accuracy: float = Field(ge=0.0, le=1.0)
    duplicate_prevention_rate: float = Field(ge=0.0, le=1.0)
    human_approval_compliance_rate: float = Field(ge=0.0, le=1.0)
    cases: list[dict[str, Any]]
