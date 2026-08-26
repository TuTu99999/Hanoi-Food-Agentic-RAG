import re
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


COURSE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dense: bool = True
    keyword: bool = True
    graph_expansion: bool = True


class AssessmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mastery_model: Literal["bkt"] = "bkt"
    allowed_question_types: list[
        Literal["multiple_choice", "short_answer", "concept_comparison"]
    ] = Field(default_factory=lambda: ["multiple_choice", "short_answer"])

    @field_validator("allowed_question_types")
    @classmethod
    def validate_question_types(cls, value: list[str]) -> list[str]:
        unique_values = list(dict.fromkeys(value))
        if not unique_values:
            raise ValueError("Phải có ít nhất một loại câu hỏi.")
        return unique_values


class AutomationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adaptive_replanning: bool = True
    reminders: bool = True


class CourseSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=11, max_length=500)
    document_id: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=3, max_length=300)
    source_type: Literal[
        "official_textbook",
        "syllabus",
        "lecture_notes",
        "question_bank",
        "reference",
    ] = "reference"
    source_authority: str | None = Field(default=None, max_length=300)
    publication_year: int | None = Field(default=None, ge=1800, le=2100)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != "documents"
        ):
            raise ValueError("Đường dẫn nguồn phải nằm trong thư mục documents.")
        return path.as_posix()

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"^[a-z][a-z0-9_]{2,79}$", normalized):
            raise ValueError(
                "document_id chỉ gồm chữ thường, số và dấu gạch dưới."
            )
        return normalized

    @field_validator("title")
    @classmethod
    def normalize_source_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Tên tài liệu không được để trống.")
        return normalized

    @field_validator("source_authority")
    @classmethod
    def normalize_source_authority(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split()) or None


class CourseManifest(BaseModel):
    """Cấu hình dùng chung để thêm một môn mà không sửa code agent."""

    model_config = ConfigDict(extra="forbid")

    course_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=3, max_length=200)
    domain: Literal["political_theory"] = "political_theory"
    version: str = Field(min_length=5, max_length=32)
    language: Literal["vi"] = "vi"
    description: str | None = Field(default=None, max_length=2000)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    assessment: AssessmentConfig = Field(default_factory=AssessmentConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    sources: list[CourseSourceConfig] = Field(default_factory=list)

    @field_validator("course_id")
    @classmethod
    def validate_course_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not COURSE_ID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "course_id chỉ gồm chữ thường, số, dấu gạch dưới và phải bắt đầu bằng chữ."
            )
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Tên môn học không được để trống.")
        return normalized

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        normalized = value.strip()
        if not VERSION_PATTERN.fullmatch(normalized):
            raise ValueError("version phải có dạng MAJOR.MINOR.PATCH, ví dụ 1.0.0.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("sources")
    @classmethod
    def validate_unique_sources(
        cls,
        value: list[CourseSourceConfig],
    ) -> list[CourseSourceConfig]:
        paths = [source.path.casefold() for source in value]
        document_ids = [source.document_id for source in value]
        if len(paths) != len(set(paths)):
            raise ValueError("Mỗi source path chỉ được khai báo một lần.")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Mỗi document_id chỉ được khai báo một lần.")
        return value


class CourseVersionResponse(BaseModel):
    version: str
    status: CourseStatus
    vector_alias: str
    graph_namespace: str
    manifest: CourseManifest
    created_at: datetime
    activated_at: datetime | None = None


class CourseResponse(BaseModel):
    course_id: str
    name: str
    domain: str
    language: str
    description: str | None = None
    created_at: datetime
    versions: list[CourseVersionResponse]


class CourseManifestValidationResponse(BaseModel):
    valid: Literal[True] = True
    course_id: str
    version: str
    vector_alias: str
    graph_namespace: str
