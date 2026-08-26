from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from schemas.indexing import AcademicRetrievalResult


AgentRoute = Literal["knowledge", "direct", "unsupported"]
VerificationStatus = Literal["PASS", "REVISE", "BLOCK"]


class AcademicKnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    course_id: str = Field(min_length=3, max_length=64)
    course_version: str = Field(min_length=5, max_length=32)
    top_k: int = Field(default=5, ge=1, le=8)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("query không được để trống.")
        return normalized

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


class AcademicKnowledgeSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: Literal["search_course_knowledge"] = "search_course_knowledge"
    result: AcademicRetrievalResult


class OrchestratorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: AgentRoute
    reason: str = Field(min_length=1, max_length=300)


class AgentCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1)
    chunk_id: str
    document_id: str
    document_title: str
    source_path: str
    source_type: str
    source_authority: str | None = None
    publication_year: int | None = None
    section_title: str | None = None
    page_number: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    start_paragraph: int | None = None
    end_paragraph: int | None = None


class KnowledgeAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    citations: list[AgentCitation]
    retrieval: AcademicRetrievalResult


class VerificationAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    critique: str = Field(min_length=1, max_length=1000)


class AgentTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    agent: Literal[
        "OrchestratorAgent",
        "KnowledgeAgent",
        "AssessmentAgent",
        "PlanningAgent",
        "VerificationAgent",
        "System",
    ]
    action: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=50)
    details: dict[str, Any] = Field(default_factory=dict)


class AcademicAssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    course_id: str = Field(min_length=3, max_length=64)
    course_version: str = Field(min_length=5, max_length=32)
    top_k: int | None = Field(default=None, ge=1, le=8)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Câu hỏi không được để trống.")
        return normalized

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


class AcademicAssistantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_version: str
    route: AgentRoute
    answer: str
    citations: list[AgentCitation]
    verification_status: VerificationStatus | Literal["NOT_REQUIRED"]
    revision_count: int = Field(ge=0)
    agent_trace: list[AgentTraceEvent]


class AcademicAgentEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2000)
    course_id: str = Field(min_length=3, max_length=64)
    course_version: str = Field(min_length=5, max_length=32)
    expected_route: AgentRoute
    expected_verification_status: (
        VerificationStatus | Literal["NOT_REQUIRED"]
    )
    top_k: int = Field(default=5, ge=1, le=8)


class AcademicAgentEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    routing_accuracy: float = Field(ge=0, le=1)
    tool_selection_accuracy: float = Field(ge=0, le=1)
    verification_outcome_accuracy: float = Field(ge=0, le=1)
    constraint_satisfaction_rate: float = Field(ge=0, le=1)
    average_revision_count: float = Field(ge=0)
    loop_violation_count: int = Field(ge=0)
    cases: list[dict[str, Any]]
