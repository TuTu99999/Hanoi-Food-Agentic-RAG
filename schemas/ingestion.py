from pydantic import BaseModel, ConfigDict, Field


class CitationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_title: str
    source_path: str
    source_type: str
    source_authority: str | None = None
    publication_year: int | None = None
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    start_paragraph: int | None = Field(default=None, ge=1)
    end_paragraph: int | None = Field(default=None, ge=1)


class AcademicChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    chunk_index: int = Field(ge=1)
    course_id: str
    course_version: str
    domain: str
    language: str
    knowledge_version: str
    document_id: str
    section_id: str
    chapter_id: str | None = None
    content: str = Field(min_length=1)
    vector_text: str = Field(min_length=1)
    word_count: int = Field(ge=1)
    citation: CitationMetadata


class IngestedSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    source_path: str
    file_type: str
    source_sha256: str
    metadata_status: str
    section_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)


class ChunkingSettings(BaseModel):
    max_words: int = Field(gt=0)
    overlap_words: int = Field(ge=0)


class CourseIngestionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    course_id: str
    course_version: str
    domain: str
    language: str
    knowledge_version: str
    document_count: int = Field(ge=1)
    section_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    chunking: ChunkingSettings
    sources: list[IngestedSourceSummary]
    chunks_sha256: str
