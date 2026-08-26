from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.agents import AgentTraceEvent
from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from schemas.ingestion import CitationMetadata


PlanStatus = Literal["PROPOSED", "ACTIVE", "REPLACED", "COMPLETED"]
ProposalKind = Literal["INITIAL", "REPLAN"]


class LearningConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: str = Field(min_length=3, max_length=100)
    concept_name: str = Field(min_length=3, max_length=300)
    order: int = Field(ge=1)
    estimated_minutes: int = Field(ge=15, le=480)
    prerequisite_ids: list[str] = Field(default_factory=list)
    learning_objective: str = Field(min_length=5, max_length=1000)
    citation: CitationMetadata

    @field_validator("concept_id")
    @classmethod
    def validate_concept_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not COURSE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("concept_id không hợp lệ.")
        return normalized

    @field_validator("prerequisite_ids")
    @classmethod
    def normalize_prerequisites(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in value]
        if any(not COURSE_ID_PATTERN.fullmatch(item) for item in normalized):
            raise ValueError("prerequisite_id không hợp lệ.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("prerequisite_ids không được trùng.")
        return normalized

    @field_validator("concept_name", "learning_objective")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def validate_citation(self):
        if self.concept_id in self.prerequisite_ids:
            raise ValueError("Concept không thể là prerequisite của chính nó.")
        if all(
            locator is None
            for locator in (
                self.citation.page_number,
                self.citation.start_line,
                self.citation.start_paragraph,
            )
        ):
            raise ValueError("Concept phải có citation kèm vị trí đối chiếu.")
        return self


class LearningMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    course_id: str = Field(min_length=3, max_length=64)
    course_version: str = Field(min_length=5, max_length=32)
    concepts: list[LearningConcept] = Field(min_length=1)

    @field_validator("course_id")
    @classmethod
    def validate_course_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not COURSE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("course_id không hợp lệ.")
        return normalized

    @field_validator("course_version")
    @classmethod
    def validate_course_version(cls, value: str) -> str:
        normalized = value.strip()
        if not VERSION_PATTERN.fullmatch(normalized):
            raise ValueError("course_version phải có dạng MAJOR.MINOR.PATCH.")
        return normalized

    @model_validator(mode="after")
    def validate_graph(self):
        concept_ids = [concept.concept_id for concept in self.concepts]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("concept_id trong Learning Map phải duy nhất.")
        known = set(concept_ids)
        for concept in self.concepts:
            missing = set(concept.prerequisite_ids) - known
            if missing:
                raise ValueError(
                    "Prerequisite không tồn tại: " + ", ".join(sorted(missing))
                )

        prerequisites = {
            concept.concept_id: set(concept.prerequisite_ids)
            for concept in self.concepts
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(concept_id: str) -> None:
            if concept_id in visiting:
                raise ValueError("Learning Map có vòng lặp prerequisite.")
            if concept_id in visited:
                return
            visiting.add(concept_id)
            for prerequisite_id in prerequisites[concept_id]:
                visit(prerequisite_id)
            visiting.remove(concept_id)
            visited.add(concept_id)

        for concept_id in concept_ids:
            visit(concept_id)
        return self


class LearningPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str = Field(min_length=3, max_length=64)
    course_version: str = Field(min_length=5, max_length=32)
    target_date: date
    study_days: int | None = Field(default=None, ge=1, le=365)
    minutes_per_day: int = Field(ge=15, le=480)
    focus_concept_ids: list[str] = Field(default_factory=list, max_length=50)
    title: str | None = Field(default=None, max_length=200)

    @field_validator("course_id")
    @classmethod
    def normalize_course_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not COURSE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("course_id không hợp lệ.")
        return normalized

    @field_validator("course_version")
    @classmethod
    def normalize_version(cls, value: str) -> str:
        normalized = value.strip()
        if not VERSION_PATTERN.fullmatch(normalized):
            raise ValueError("course_version phải có dạng MAJOR.MINOR.PATCH.")
        return normalized

    @field_validator("focus_concept_ids")
    @classmethod
    def normalize_focus(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip().lower() for item in value))
        if any(not COURSE_ID_PATTERN.fullmatch(item) for item in normalized):
            raise ValueError("focus_concept_id không hợp lệ.")
        return normalized

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split()) or None


class LearningPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    study_date: date
    concept_id: str
    concept_name: str
    duration_minutes: int = Field(ge=1, le=480)
    activity: Literal["learn", "practice", "review"]
    reason: str
    prerequisite_ids: list[str]
    citation: CitationMetadata


class LearningPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    target_date: date
    study_days: int = Field(ge=1)
    minutes_per_day: int = Field(ge=15, le=480)
    capacity_minutes: int = Field(ge=1)
    required_minutes: int = Field(ge=1)
    scheduled_minutes: int = Field(ge=0)
    priority_concept_ids: list[str]
    unscheduled_concept_ids: list[str]
    items: list[LearningPlanItem]


class PlanningWorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["create_plan"] = "create_plan"
    verification_status: Literal["PASS", "BLOCK"]
    critique: str
    draft: LearningPlanDraft
    agent_trace: list[AgentTraceEvent]


class LearningPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    course_id: str
    course_version: str
    title: str
    status: PlanStatus
    revision: int = Field(ge=1)
    proposal_kind: ProposalKind = "INITIAL"
    parent_plan_id: str | None = None
    trigger_event_id: str | None = None
    draft: LearningPlanDraft
    verification_status: Literal["PASS"]
    verification_critique: str
    agent_trace: list[AgentTraceEvent]
    created_at: datetime
    approved_at: datetime | None = None


class LearningPlanApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    status: Literal["ACTIVE"]
    approved_at: datetime


class PlanningEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    mastery_by_concept: dict[str, float] = Field(default_factory=dict)
    mastery_threshold: float = Field(default=0.8, gt=0, le=1)
    initial_mastery: float = Field(default=0.2, ge=0, le=1)
    start_date: date
    target_date: date
    study_days: int = Field(ge=1, le=365)
    minutes_per_day: int = Field(ge=15, le=480)
    focus_concept_ids: list[str] = Field(default_factory=list)
    expected_status: Literal["PASS", "BLOCK"]
    expected_priority_concept_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case(self):
        if self.start_date >= self.target_date:
            raise ValueError("Evaluation start_date phải trước target_date.")
        if any(value < 0 or value > 1 for value in self.mastery_by_concept.values()):
            raise ValueError("Evaluation mastery phải từ 0 đến 1.")
        return self


class PlanningEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    verification_outcome_accuracy: float = Field(ge=0, le=1)
    priority_selection_accuracy: float = Field(ge=0, le=1)
    daily_capacity_compliance_rate: float = Field(ge=0, le=1)
    prerequisite_order_compliance_rate: float = Field(ge=0, le=1)
    concept_coverage_rate: float = Field(ge=0, le=1)
    cases: list[dict]
