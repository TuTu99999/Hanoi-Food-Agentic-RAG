import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from qdrant_client.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    Distance,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from academic_retrieval.artifacts import CourseArtifactError, json_sha256
from courses.naming import vector_alias_for, vector_collection_for
from schemas.indexing import CourseEmbeddingManifest, EmbeddedAcademicChunk


COURSE_POINT_NAMESPACE = uuid.UUID("7b9ad8ce-b690-4eb8-97a5-66c1826e3efa")
PAYLOAD_INDEXES = (
    ("course_id", PayloadSchemaType.KEYWORD),
    ("course_version", PayloadSchemaType.KEYWORD),
    ("knowledge_version", PayloadSchemaType.KEYWORD),
    ("document_id", PayloadSchemaType.KEYWORD),
    ("chapter_id", PayloadSchemaType.KEYWORD),
    ("source_type", PayloadSchemaType.KEYWORD),
)


@dataclass(frozen=True)
class CourseVectorArtifact:
    directory: Path
    rows: tuple[EmbeddedAcademicChunk, ...]
    manifest: CourseEmbeddingManifest


@dataclass(frozen=True)
class CourseVectorUploadResult:
    collection_name: str
    alias_name: str
    point_count: int
    vector_dimension: int
    alias_switched: bool


def point_id_from_chunk_id(chunk_id: str) -> str:
    return str(uuid.uuid5(COURSE_POINT_NAMESPACE, chunk_id))


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise CourseArtifactError(f"Không tìm thấy artifact: {path}")
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise CourseArtifactError(f"Không thể đọc JSON hợp lệ: {path}") from exc


def load_course_vector_artifact(
    indexed_directory: str | Path,
) -> CourseVectorArtifact:
    directory = Path(indexed_directory).resolve()
    raw_rows = _read_json(directory / "vectors.json")
    raw_manifest = _read_json(directory / "embedding_manifest.json")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise CourseArtifactError("vectors.json phải là một danh sách không rỗng.")

    try:
        rows = tuple(
            EmbeddedAcademicChunk.model_validate(row)
            for row in raw_rows
        )
        manifest = CourseEmbeddingManifest.model_validate(raw_manifest)
    except ValidationError as exc:
        raise CourseArtifactError(f"Vector artifact không đúng schema: {exc}") from exc

    if len(rows) != manifest.point_count:
        raise CourseArtifactError("Số vector không khớp embedding manifest.")
    if json_sha256(raw_rows) != manifest.vector_artifact_sha256:
        raise CourseArtifactError("Hash vectors.json không khớp embedding manifest.")

    chunk_ids = [row.chunk_id for row in rows]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise CourseArtifactError("vectors.json chứa chunk_id trùng nhau.")

    for row in rows:
        if len(row.vector) != manifest.vector_dimension:
            raise CourseArtifactError(
                f"Vector {row.chunk_id} không đúng số chiều trong manifest."
            )
        if (
            row.course_id != manifest.course_id
            or row.course_version != manifest.course_version
            or row.domain != manifest.domain
            or row.language != manifest.language
            or row.knowledge_version != manifest.knowledge_version
        ):
            raise CourseArtifactError(
                f"Vector {row.chunk_id} không cùng định danh với manifest."
            )

    return CourseVectorArtifact(
        directory=directory,
        rows=rows,
        manifest=manifest,
    )


def _build_payload(row: EmbeddedAcademicChunk) -> dict[str, Any]:
    payload = row.model_dump(mode="json", exclude={"vector"})
    payload["source_type"] = row.citation.source_type
    return payload


def _build_points(rows: tuple[EmbeddedAcademicChunk, ...]):
    for row in rows:
        yield PointStruct(
            id=point_id_from_chunk_id(row.chunk_id),
            vector=row.vector,
            payload=_build_payload(row),
        )


def _create_payload_indexes(client: Any, collection_name: str) -> None:
    for field_name, field_schema in PAYLOAD_INDEXES:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )


def _switch_alias(client: Any, collection_name: str, alias_name: str) -> None:
    aliases = client.get_aliases().aliases
    current = next(
        (alias for alias in aliases if alias.alias_name == alias_name),
        None,
    )
    if current and current.collection_name == collection_name:
        return

    operations = []
    if current:
        operations.append(
            DeleteAliasOperation(
                delete_alias=DeleteAlias(alias_name=alias_name)
            )
        )
    operations.append(
        CreateAliasOperation(
            create_alias=CreateAlias(
                collection_name=collection_name,
                alias_name=alias_name,
            )
        )
    )
    client.update_collection_aliases(change_aliases_operations=operations)

    active = next(
        (
            alias
            for alias in client.get_aliases().aliases
            if alias.alias_name == alias_name
        ),
        None,
    )
    if not active or active.collection_name != collection_name:
        raise RuntimeError(f"Không thể chuyển Qdrant alias {alias_name}.")


def _validate_uploaded_collection(
    client: Any,
    collection_name: str,
    artifact: CourseVectorArtifact,
) -> None:
    actual_count = client.count(
        collection_name=collection_name,
        exact=True,
    ).count
    if actual_count != len(artifact.rows):
        raise RuntimeError(
            f"Qdrant có {actual_count} point, kỳ vọng {len(artifact.rows)}."
        )

    sample_indexes = sorted(
        {0, len(artifact.rows) // 2, len(artifact.rows) - 1}
    )
    sample_rows = [artifact.rows[index] for index in sample_indexes]
    sample_by_id = {row.chunk_id: row for row in sample_rows}
    records = client.retrieve(
        collection_name=collection_name,
        ids=[point_id_from_chunk_id(chunk_id) for chunk_id in sample_by_id],
        with_payload=[
            "chunk_id",
            "course_id",
            "course_version",
            "knowledge_version",
            "citation",
        ],
        with_vectors=False,
    )
    returned = {
        (record.payload or {}).get("chunk_id"): record.payload or {}
        for record in records
    }
    if set(returned) != set(sample_by_id):
        raise RuntimeError("Qdrant sample validation thiếu chunk đã upload.")
    for chunk_id, payload in returned.items():
        expected = sample_by_id[chunk_id]
        if (
            payload.get("course_id") != expected.course_id
            or payload.get("course_version") != expected.course_version
            or payload.get("knowledge_version") != expected.knowledge_version
            or not payload.get("citation")
        ):
            raise RuntimeError("Qdrant sample validation sai metadata hoặc citation.")


def upload_course_vectors(
    client: Any,
    artifact: CourseVectorArtifact,
    *,
    switch_alias: bool = True,
) -> CourseVectorUploadResult:
    manifest = artifact.manifest
    collection_name = vector_collection_for(
        manifest.course_id,
        manifest.course_version,
        manifest.knowledge_version,
    )
    alias_name = vector_alias_for(manifest.course_id)
    if collection_name == alias_name:
        raise ValueError("Tên collection vật lý không được trùng alias.")
    if client.collection_exists(collection_name=collection_name):
        raise RuntimeError(
            f"Collection {collection_name} đã tồn tại; không ghi đè index bất biến."
        )

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=manifest.vector_dimension,
            distance=Distance.COSINE,
        ),
    )
    _create_payload_indexes(client, collection_name)
    client.upload_points(
        collection_name=collection_name,
        points=_build_points(artifact.rows),
        batch_size=64,
        max_retries=3,
        wait=True,
    )
    _validate_uploaded_collection(client, collection_name, artifact)
    if switch_alias:
        _switch_alias(client, collection_name, alias_name)

    return CourseVectorUploadResult(
        collection_name=collection_name,
        alias_name=alias_name,
        point_count=len(artifact.rows),
        vector_dimension=manifest.vector_dimension,
        alias_switched=switch_alias,
    )
