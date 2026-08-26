import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError
from sentence_transformers import SentenceTransformer

from schemas.indexing import (
    CourseEmbeddingManifest,
    EmbeddedAcademicChunk,
)
from schemas.ingestion import AcademicChunk, CourseIngestionManifest


class CourseArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedCourseData:
    directory: Path
    chunks: tuple[AcademicChunk, ...]
    manifest: CourseIngestionManifest


@dataclass(frozen=True)
class CourseEmbeddingBuildResult:
    rows: tuple[EmbeddedAcademicChunk, ...]
    manifest: CourseEmbeddingManifest
    output_directory: Path
    vectors_path: Path
    manifest_path: Path


def json_sha256(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise CourseArtifactError(f"Không tìm thấy artifact: {path}")
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise CourseArtifactError(f"Không thể đọc JSON hợp lệ: {path}") from exc


def _write_json_atomic(path: Path, payload: Any) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8") as destination:
        json.dump(payload, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    temporary_path.replace(path)


def _has_citation_locator(chunk: AcademicChunk) -> bool:
    citation = chunk.citation
    return any(
        value is not None
        for value in (
            citation.page_number,
            citation.start_line,
            citation.start_paragraph,
        )
    )


def load_processed_course(processed_directory: str | Path) -> ProcessedCourseData:
    directory = Path(processed_directory).resolve()
    chunks_path = directory / "chunks.json"
    manifest_path = directory / "ingestion_manifest.json"
    raw_chunks = _read_json(chunks_path)
    raw_manifest = _read_json(manifest_path)
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise CourseArtifactError("chunks.json phải là một danh sách không rỗng.")

    try:
        chunks = tuple(AcademicChunk.model_validate(row) for row in raw_chunks)
        manifest = CourseIngestionManifest.model_validate(raw_manifest)
    except ValidationError as exc:
        raise CourseArtifactError(f"Processed artifact không đúng schema: {exc}") from exc

    if len(chunks) != manifest.chunk_count:
        raise CourseArtifactError("Số chunk không khớp ingestion manifest.")
    if json_sha256(raw_chunks) != manifest.chunks_sha256:
        raise CourseArtifactError("Hash chunks.json không khớp ingestion manifest.")

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise CourseArtifactError("chunks.json chứa chunk_id trùng nhau.")

    for chunk in chunks:
        identity = (
            chunk.course_id,
            chunk.course_version,
            chunk.domain,
            chunk.language,
            chunk.knowledge_version,
        )
        expected_identity = (
            manifest.course_id,
            manifest.course_version,
            manifest.domain,
            manifest.language,
            manifest.knowledge_version,
        )
        if identity != expected_identity:
            raise CourseArtifactError(
                f"Chunk {chunk.chunk_id} không cùng định danh với ingestion manifest."
            )
        if chunk.document_id != chunk.citation.document_id:
            raise CourseArtifactError(
                f"Chunk {chunk.chunk_id} có citation sai document_id."
            )
        source_path = PurePosixPath(chunk.citation.source_path)
        if source_path.is_absolute() or ".." in source_path.parts:
            raise CourseArtifactError(
                f"Chunk {chunk.chunk_id} có source_path không an toàn."
            )
        if not _has_citation_locator(chunk):
            raise CourseArtifactError(
                f"Chunk {chunk.chunk_id} thiếu vị trí citation."
            )

    return ProcessedCourseData(
        directory=directory,
        chunks=chunks,
        manifest=manifest,
    )


def _to_vector_list(vector: Any, chunk_id: str) -> list[float]:
    raw_vector = vector.tolist() if hasattr(vector, "tolist") else vector
    if not isinstance(raw_vector, (list, tuple)) or not raw_vector:
        raise CourseArtifactError(
            f"Embedding model trả vector không hợp lệ cho {chunk_id}."
        )
    try:
        return [float(value) for value in raw_vector]
    except (TypeError, ValueError) as exc:
        raise CourseArtifactError(
            f"Embedding model trả vector không phải số cho {chunk_id}."
        ) from exc


def build_course_embeddings(
    processed_directory: str | Path,
    *,
    output_directory: str | Path | None = None,
    model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    batch_size: int = 32,
    local_files_only: bool = True,
    force: bool = False,
    encoder: Any | None = None,
) -> CourseEmbeddingBuildResult:
    if batch_size <= 0:
        raise ValueError("batch_size phải lớn hơn 0.")
    resolved_model_name = model_name.strip()
    if not resolved_model_name:
        raise ValueError("model_name không được để trống.")

    processed = load_processed_course(processed_directory)
    target_directory = (
        Path(output_directory).resolve()
        if output_directory is not None
        else processed.directory.parent / "indexed"
    )
    vectors_path = target_directory / "vectors.json"
    manifest_path = target_directory / "embedding_manifest.json"
    if not force and (vectors_path.exists() or manifest_path.exists()):
        raise CourseArtifactError(
            "Embedding artifact của phiên bản này đã tồn tại. "
            "Tăng course version hoặc dùng --force khi phát triển."
        )

    resolved_encoder = encoder or SentenceTransformer(
        resolved_model_name,
        local_files_only=local_files_only,
    )
    texts = [chunk.vector_text for chunk in processed.chunks]
    vectors = resolved_encoder.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    if len(vectors) != len(processed.chunks):
        raise CourseArtifactError(
            "Embedding model trả số vector không bằng số chunk."
        )

    rows = []
    vector_dimension = None
    for chunk, vector in zip(processed.chunks, vectors):
        vector_list = _to_vector_list(vector, chunk.chunk_id)
        if vector_dimension is None:
            vector_dimension = len(vector_list)
        elif len(vector_list) != vector_dimension:
            raise CourseArtifactError("Các embedding vector không cùng số chiều.")
        rows.append(
            EmbeddedAcademicChunk(
                **chunk.model_dump(mode="python"),
                vector=vector_list,
            )
        )

    serialized_rows = [row.model_dump(mode="json") for row in rows]
    embedding_manifest = CourseEmbeddingManifest(
        course_id=processed.manifest.course_id,
        course_version=processed.manifest.course_version,
        domain=processed.manifest.domain,
        language=processed.manifest.language,
        knowledge_version=processed.manifest.knowledge_version,
        embedding_model=resolved_model_name,
        vector_dimension=vector_dimension or 0,
        point_count=len(rows),
        source_chunks_sha256=processed.manifest.chunks_sha256,
        vector_artifact_sha256=json_sha256(serialized_rows),
    )

    target_directory.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(vectors_path, serialized_rows)
    _write_json_atomic(
        manifest_path,
        embedding_manifest.model_dump(mode="json"),
    )
    return CourseEmbeddingBuildResult(
        rows=tuple(rows),
        manifest=embedding_manifest,
        output_directory=target_directory,
        vectors_path=vectors_path,
        manifest_path=manifest_path,
    )
