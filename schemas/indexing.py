import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.ingestion import AcademicChunk, CitationMetadata


class EmbeddedAcademicChunk(AcademicChunk):
    vector: list[float] = Field(min_length=1)

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, value: list[float]) -> list[float]:
        if not all(math.isfinite(number) for number in value):
            raise ValueError("Embedding vector chỉ được chứa số hữu hạn.")
        return value


class CourseEmbeddingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    course_id: str
    course_version: str
    domain: str
    language: str
    knowledge_version: str
    embedding_model: str
    vector_dimension: int = Field(gt=0)
    point_count: int = Field(gt=0)
    source_chunks_sha256: str = Field(min_length=64, max_length=64)
    vector_artifact_sha256: str = Field(min_length=64, max_length=64)


class AcademicRetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    course_id: str
    course_version: str
    knowledge_version: str
    document_id: str
    section_id: str
    chapter_id: str | None = None
    content: str
    citation: CitationMetadata
    score: float
    dense_score: float = 0.0
    keyword_score: float = 0.0
    retrieval_sources: list[Literal["dense", "keyword"]]


class AcademicRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    course_id: str
    course_version: str
    knowledge_version: str
    collection_name: str
    branch_counts: dict[str, int]
    hits: list[AcademicRetrievalHit]


class AcademicRetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=2000)
    course_id: str = Field(min_length=3, max_length=64)
    course_version: str | None = None
    expected_chunk_ids: list[str] = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("expected_chunk_ids")
    @classmethod
    def unique_expected_chunks(cls, value: list[str]) -> list[str]:
        normalized = [chunk_id.strip() for chunk_id in value]
        if any(not chunk_id for chunk_id in normalized):
            raise ValueError("expected_chunk_ids không được chứa ID rỗng.")
        return list(dict.fromkeys(normalized))


class AcademicRetrievalEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    hit_rate_at_k: float = Field(ge=0, le=1)
    recall_at_k: float = Field(ge=0, le=1)
    mean_reciprocal_rank: float = Field(ge=0, le=1)
    citation_completeness: float = Field(ge=0, le=1)
    cross_course_leakage_count: int = Field(ge=0)
    empty_result_count: int = Field(ge=0)
    cases: list[dict]
