import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from courses.package import CoursePackageError, load_course_package
from ingestion.chunker import build_academic_chunks
from ingestion.parsers import (
    DocumentMetadata,
    DocumentParseError,
    automatic_document_id,
    file_sha256,
    parse_document,
)
from schemas.ingestion import (
    AcademicChunk,
    ChunkingSettings,
    CourseIngestionManifest,
    IngestedSourceSummary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "courses"


class CourseIngestionError(ValueError):
    pass


@dataclass(frozen=True)
class CourseIngestionConfig:
    max_words: int = 220
    overlap_words: int = 30

    def __post_init__(self) -> None:
        if self.max_words <= 0:
            raise ValueError("max_words phải lớn hơn 0.")
        if self.overlap_words < 0 or self.overlap_words >= self.max_words:
            raise ValueError("overlap_words phải từ 0 đến max_words - 1.")


@dataclass(frozen=True)
class CourseIngestionResult:
    chunks: tuple[AcademicChunk, ...]
    manifest: CourseIngestionManifest
    output_directory: Path
    chunks_path: Path
    manifest_path: Path
    question_bank_path: Path | None
    learning_map_path: Path | None
    dry_run: bool


def _json_sha256(value) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8") as destination:
        json.dump(payload, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    temporary_path.replace(path)


def ingest_course_package(
    package_path: str | Path,
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    config: CourseIngestionConfig | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> CourseIngestionResult:
    resolved_config = config or CourseIngestionConfig()
    try:
        package = load_course_package(package_path)
    except CoursePackageError as exc:
        raise CourseIngestionError(str(exc)) from exc

    course_manifest = package.manifest
    source_configs = {
        source.path.casefold(): source
        for source in course_manifest.sources
    }
    all_sections = []
    source_records = []
    document_ids = set()

    for document_path in package.documents:
        source_path = document_path.relative_to(package.root).as_posix()
        source_config = source_configs.get(source_path.casefold())
        document_id = (
            source_config.document_id
            if source_config is not None
            else automatic_document_id(source_path)
        )
        if document_id in document_ids:
            raise CourseIngestionError(f"Trùng document_id: {document_id}")
        document_ids.add(document_id)

        metadata = DocumentMetadata(
            document_id=document_id,
            title=(
                source_config.title
                if source_config is not None
                else document_path.stem.replace("_", " ").replace("-", " ")
            ),
            source_path=source_path,
            source_type=(
                source_config.source_type
                if source_config is not None
                else "reference"
            ),
            source_authority=(
                source_config.source_authority
                if source_config is not None
                else None
            ),
            publication_year=(
                source_config.publication_year
                if source_config is not None
                else None
            ),
            source_sha256=file_sha256(document_path),
            metadata_status=("declared" if source_config is not None else "inferred"),
        )
        try:
            sections = parse_document(document_path, metadata)
        except DocumentParseError as exc:
            raise CourseIngestionError(str(exc)) from exc
        all_sections.extend(sections)
        source_records.append((metadata, sections))

    version_input = {
        "schema_version": 1,
        "course": course_manifest.model_dump(mode="json"),
        "chunking": {
            "max_words": resolved_config.max_words,
            "overlap_words": resolved_config.overlap_words,
        },
        "sources": [
            {
                "document_id": metadata.document_id,
                "source_path": metadata.source_path,
                "source_sha256": metadata.source_sha256,
            }
            for metadata, _sections in source_records
        ],
    }
    knowledge_version = (
        f"{course_manifest.course_id}-{_json_sha256(version_input)[:12]}"
    )
    chunks = build_academic_chunks(
        manifest=course_manifest,
        sections=all_sections,
        knowledge_version=knowledge_version,
        max_words=resolved_config.max_words,
        overlap_words=resolved_config.overlap_words,
    )
    if not chunks:
        raise CourseIngestionError("Course Package không tạo được chunk nào.")

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise CourseIngestionError("Pipeline tạo chunk_id bị trùng.")

    source_summaries = []
    for metadata, sections in source_records:
        source_summaries.append(
            IngestedSourceSummary(
                document_id=metadata.document_id,
                title=metadata.title,
                source_path=metadata.source_path,
                file_type=Path(metadata.source_path).suffix.casefold().lstrip("."),
                source_sha256=metadata.source_sha256,
                metadata_status=metadata.metadata_status,
                section_count=len(sections),
                chunk_count=sum(
                    chunk.document_id == metadata.document_id
                    for chunk in chunks
                ),
            )
        )

    serialized_chunks = [chunk.model_dump(mode="json") for chunk in chunks]
    ingestion_manifest = CourseIngestionManifest(
        course_id=course_manifest.course_id,
        course_version=course_manifest.version,
        domain=course_manifest.domain,
        language=course_manifest.language,
        knowledge_version=knowledge_version,
        document_count=len(source_records),
        section_count=len(all_sections),
        chunk_count=len(chunks),
        chunking=ChunkingSettings(
            max_words=resolved_config.max_words,
            overlap_words=resolved_config.overlap_words,
        ),
        sources=source_summaries,
        chunks_sha256=_json_sha256(serialized_chunks),
    )

    output_directory = (
        Path(output_root).resolve()
        / course_manifest.course_id
        / course_manifest.version
        / "processed"
    )
    chunks_path = output_directory / "chunks.json"
    manifest_path = output_directory / "ingestion_manifest.json"
    candidate_question_bank_path = (
        output_directory.parent / "assessment" / "questions.json"
    )
    question_bank_path = (
        candidate_question_bank_path
        if package.question_bank is not None
        else None
    )
    candidate_learning_map_path = (
        output_directory.parent / "planning" / "learning_map.json"
    )
    learning_map_path = (
        candidate_learning_map_path
        if package.learning_map is not None
        else None
    )
    if not dry_run:
        if (
            force
            and package.question_bank is None
            and candidate_question_bank_path.exists()
        ):
            raise CourseIngestionError(
                "Output đang có ngân hàng câu hỏi nhưng Course Package mới không có; "
                "hãy tăng version để tránh giữ dữ liệu đánh giá cũ."
            )
        if (
            force
            and package.learning_map is None
            and candidate_learning_map_path.exists()
        ):
            raise CourseIngestionError(
                "Output đang có Learning Map nhưng Course Package mới không có; "
                "hãy tăng version để tránh giữ dữ liệu kế hoạch cũ."
            )
        if not force and (
            chunks_path.exists()
            or manifest_path.exists()
            or (
                question_bank_path is not None
                and question_bank_path.exists()
            )
            or (
                learning_map_path is not None
                and learning_map_path.exists()
            )
        ):
            raise CourseIngestionError(
                "Output của phiên bản môn đã tồn tại. Tăng version hoặc dùng --force khi phát triển."
            )
        output_directory.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(chunks_path, serialized_chunks)
        _write_json_atomic(
            manifest_path,
            ingestion_manifest.model_dump(mode="json"),
        )
        if question_bank_path is not None:
            question_bank_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(
                question_bank_path,
                package.question_bank.model_dump(mode="json"),
            )
        if learning_map_path is not None:
            learning_map_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(
                learning_map_path,
                package.learning_map.model_dump(mode="json"),
            )

    return CourseIngestionResult(
        chunks=tuple(chunks),
        manifest=ingestion_manifest,
        output_directory=output_directory,
        chunks_path=chunks_path,
        manifest_path=manifest_path,
        question_bank_path=question_bank_path,
        learning_map_path=learning_map_path,
        dry_run=dry_run,
    )
