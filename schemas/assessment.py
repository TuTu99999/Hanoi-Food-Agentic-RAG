from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.agents import AgentTraceEvent
from schemas.automation import AutomationOutcome
from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from schemas.ingestion import CitationMetadata


MasteryLevel = Literal["weak", "developing", "mastered"]


class BKTParameters(BaseModel):
    """Bayesian Knowledge Tracing parameters shared by one question bank."""

    model_config = ConfigDict(extra="forbid")

    p_initial: float = Field(default=0.2, ge=0.0, le=1.0)
    p_learn: float = Field(default=0.15, ge=0.0, le=1.0)
    p_guess: float = Field(default=0.2, ge=0.0, le=1.0)
    p_slip: float = Field(default=0.1, ge=0.0, le=1.0)
    mastery_threshold: float = Field(default=0.8, gt=0.0, le=1.0)


class AssessmentOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=10)
    text: str = Field(min_length=1, max_length=500)

    @field_validator("option_id")
    @classmethod
    def normalize_option_id(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


class AssessmentQuestion(BaseModel):
    """Internal question schema. The correct answer never goes to the client."""

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=3, max_length=100)
    concept_id: str = Field(min_length=3, max_length=100)
    concept_name: str = Field(min_length=3, max_length=300)
    question_type: Literal["multiple_choice"] = "multiple_choice"
    difficulty: int = Field(default=1, ge=1, le=5)
    prompt: str = Field(min_length=5, max_length=2000)
    options: list[AssessmentOption] = Field(min_length=2, max_length=6)
    correct_option_id: str = Field(min_length=1, max_length=10)
    explanation: str = Field(min_length=5, max_length=3000)
    citation: CitationMetadata

    @field_validator("question_id", "concept_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not COURSE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("Định danh câu hỏi/concept không hợp lệ.")
        return normalized

    @field_validator("concept_name", "prompt", "explanation")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("correct_option_id")
    @classmethod
    def normalize_correct_option(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_question_contract(self):
        option_ids = [option.option_id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("option_id trong một câu hỏi phải duy nhất.")
        if self.correct_option_id not in option_ids:
            raise ValueError("correct_option_id không tồn tại trong options.")
        citation = self.citation
        if all(
            locator is None
            for locator in (
                citation.page_number,
                citation.start_line,
                citation.start_paragraph,
            )
        ):
            raise ValueError("Citation câu hỏi phải có trang, dòng hoặc đoạn.")
        return self


class AssessmentQuestionBank(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    course_id: str = Field(min_length=3, max_length=64)
    course_version: str = Field(min_length=5, max_length=32)
    bkt: BKTParameters = Field(default_factory=BKTParameters)
    questions: list[AssessmentQuestion] = Field(min_length=1)

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
    def validate_unique_questions(self):
        question_ids = [question.question_id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question_id trong ngân hàng phải duy nhất.")
        concept_names: dict[str, str] = {}
        for question in self.questions:
            previous = concept_names.setdefault(
                question.concept_id,
                question.concept_name,
            )
            if previous != question.concept_name:
                raise ValueError("Một concept_id không được có nhiều tên khác nhau.")
        return self


class PublicAssessmentQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    concept_id: str
    concept_name: str
    question_type: Literal["multiple_choice"]
    difficulty: int
    prompt: str
    options: list[AssessmentOption]
    citation: CitationMetadata


class AssessmentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: AssessmentQuestion
    mastery_before: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=500)


class AssessmentGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    submitted_option_id: str
    correct_option_id: str
    is_correct: bool
    feedback: str = Field(min_length=1, max_length=4000)


class AssessmentWorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["select_question", "grade_answer"]
    verification_status: Literal["PASS", "BLOCK"]
    selection: AssessmentSelection | None = None
    grade: AssessmentGrade | None = None
    mastery_before: float | None = Field(default=None, ge=0.0, le=1.0)
    mastery_after: float | None = Field(default=None, ge=0.0, le=1.0)
    agent_trace: list[AgentTraceEvent]


class AssessmentStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str = Field(min_length=3, max_length=64)
    course_version: str = Field(min_length=5, max_length=32)
    concept_id: str | None = Field(default=None, min_length=3, max_length=100)

    @field_validator("course_id", "concept_id")
    @classmethod
    def normalize_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not COURSE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("Định danh không hợp lệ.")
        return normalized

    @field_validator("course_version")
    @classmethod
    def normalize_version(cls, value: str) -> str:
        normalized = value.strip()
        if not VERSION_PATTERN.fullmatch(normalized):
            raise ValueError("course_version phải có dạng MAJOR.MINOR.PATCH.")
        return normalized


class AssessmentStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    course_id: str
    course_version: str
    question: PublicAssessmentQuestion
    mastery_before: float = Field(ge=0.0, le=1.0)
    selection_reason: str
    agent_trace: list[AgentTraceEvent]


class AssessmentSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_option_id: str = Field(min_length=1, max_length=10)

    @field_validator("selected_option_id")
    @classmethod
    def normalize_selected_option(cls, value: str) -> str:
        return value.strip().upper()


class AssessmentSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    course_id: str
    course_version: str
    concept_id: str
    concept_name: str
    is_correct: bool
    correct_option_id: str
    feedback: str
    mastery_before: float = Field(ge=0.0, le=1.0)
    mastery_after: float = Field(ge=0.0, le=1.0)
    mastery_level: MasteryLevel
    next_action: Literal["review_concept", "continue_practice", "concept_mastered"]
    verification_status: Literal["PASS"]
    agent_trace: list[AgentTraceEvent]
    automation: AutomationOutcome | None = None


class ConceptMasteryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: str
    concept_name: str
    mastery_probability: float = Field(ge=0.0, le=1.0)
    mastery_level: MasteryLevel
    attempt_count: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    updated_at: datetime | None = None


class CourseMasteryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_version: str
    concepts: list[ConceptMasteryResponse]


class AssessmentSelectionEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    mastery_by_concept: dict[str, float] = Field(default_factory=dict)
    attempt_count_by_question: dict[str, int] = Field(default_factory=dict)
    target_concept_id: str | None = None
    expected_concept_id: str = Field(min_length=3, max_length=100)
    expected_question_id: str = Field(min_length=3, max_length=100)

    @model_validator(mode="after")
    def validate_profile_values(self):
        if any(value < 0 or value > 1 for value in self.mastery_by_concept.values()):
            raise ValueError("Mastery trong evaluation phải từ 0 đến 1.")
        if any(value < 0 for value in self.attempt_count_by_question.values()):
            raise ValueError("Số lượt làm trong evaluation không được âm.")
        return self


class AssessmentGradingEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    question_id: str = Field(min_length=3, max_length=100)
    selected_option_id: str = Field(min_length=1, max_length=10)
    expected_is_correct: bool


class AssessmentEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection_cases: list[AssessmentSelectionEvaluationCase] = Field(
        default_factory=list
    )
    grading_cases: list[AssessmentGradingEvaluationCase] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_cases(self):
        all_ids = [
            case.case_id
            for case in [*self.selection_cases, *self.grading_cases]
        ]
        if not all_ids:
            raise ValueError("Cần ít nhất một assessment evaluation case.")
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("case_id trong assessment evaluation phải duy nhất.")
        return self


class AssessmentEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection_case_count: int = Field(ge=0)
    grading_case_count: int = Field(ge=0)
    concept_selection_accuracy: float = Field(ge=0, le=1)
    question_selection_accuracy: float = Field(ge=0, le=1)
    grading_accuracy: float = Field(ge=0, le=1)
    verification_pass_rate: float = Field(ge=0, le=1)
    bkt_boundedness_rate: float = Field(ge=0, le=1)
    cases: list[dict]
