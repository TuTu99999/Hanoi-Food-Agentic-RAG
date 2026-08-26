from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sentence_transformers import SentenceTransformer

from academic_retrieval.artifacts import (
    CourseArtifactError,
    ProcessedCourseData,
    load_processed_course,
)
from academic_retrieval.lexical import AcademicLexicalIndex
from academic_retrieval.qdrant_store import load_course_vector_artifact
from courses.naming import vector_alias_for
from schemas.indexing import (
    AcademicRetrievalHit,
    AcademicRetrievalResult,
    CourseEmbeddingManifest,
)
from schemas.ingestion import AcademicChunk


RRF_K = 60


class AcademicRetrievalError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Candidate:
    chunk: AcademicChunk
    dense_score: float = 0.0
    keyword_score: float = 0.0


class AcademicHybridRetriever:
    """Hybrid vector/BM25 retrieval scoped to exactly one course version."""

    def __init__(
        self,
        *,
        processed: ProcessedCourseData,
        embedding_manifest: CourseEmbeddingManifest,
        client: Any,
        encoder: Any,
        collection_name: str | None = None,
    ) -> None:
        ingestion_manifest = processed.manifest
        if (
            embedding_manifest.course_id != ingestion_manifest.course_id
            or embedding_manifest.course_version
            != ingestion_manifest.course_version
            or embedding_manifest.knowledge_version
            != ingestion_manifest.knowledge_version
            or embedding_manifest.source_chunks_sha256
            != ingestion_manifest.chunks_sha256
        ):
            raise CourseArtifactError(
                "Embedding artifact không khớp processed course artifact."
            )

        self.processed = processed
        self.embedding_manifest = embedding_manifest
        self.client = client
        self.encoder = encoder
        self.collection_name = collection_name or vector_alias_for(
            ingestion_manifest.course_id
        )
        self.lexical_index = AcademicLexicalIndex(processed.chunks)

    @classmethod
    def from_artifacts(
        cls,
        processed_directory: str,
        indexed_directory: str,
        *,
        qdrant_url: str,
        qdrant_api_key: str | None = None,
        timeout_seconds: float = 3.0,
        local_files_only: bool = True,
        collection_name: str | None = None,
    ) -> "AcademicHybridRetriever":
        processed = load_processed_course(processed_directory)
        vector_artifact = load_course_vector_artifact(indexed_directory)
        client = QdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key,
            timeout=timeout_seconds,
        )
        encoder = SentenceTransformer(
            vector_artifact.manifest.embedding_model,
            local_files_only=local_files_only,
        )
        return cls(
            processed=processed,
            embedding_manifest=vector_artifact.manifest,
            client=client,
            encoder=encoder,
            collection_name=collection_name,
        )

    @staticmethod
    def _query_vector(encoder: Any, query: str) -> list[float]:
        vectors = encoder.encode(
            [query],
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        if len(vectors) != 1:
            raise AcademicRetrievalError(
                "Embedding model không trả đúng một query vector."
            )
        vector = vectors[0]
        raw_vector = vector.tolist() if hasattr(vector, "tolist") else vector
        if not isinstance(raw_vector, (list, tuple)) or not raw_vector:
            raise AcademicRetrievalError("Query vector không hợp lệ.")
        try:
            return [float(value) for value in raw_vector]
        except (TypeError, ValueError) as exc:
            raise AcademicRetrievalError("Query vector không phải số.") from exc

    def _qdrant_filter(self, document_id: str | None) -> Filter:
        manifest = self.processed.manifest
        conditions = [
            FieldCondition(
                key="course_id",
                match=MatchValue(value=manifest.course_id),
            ),
            FieldCondition(
                key="course_version",
                match=MatchValue(value=manifest.course_version),
            ),
            FieldCondition(
                key="knowledge_version",
                match=MatchValue(value=manifest.knowledge_version),
            ),
        ]
        if document_id:
            conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            )
        return Filter(must=conditions)

    def _chunk_from_payload(self, payload: dict[str, Any]) -> AcademicChunk:
        cleaned_payload = dict(payload)
        cleaned_payload.pop("source_type", None)
        try:
            chunk = AcademicChunk.model_validate(cleaned_payload)
        except Exception as exc:
            raise AcademicRetrievalError(
                "Qdrant trả payload học thuật không đúng schema."
            ) from exc

        manifest = self.processed.manifest
        if (
            chunk.course_id != manifest.course_id
            or chunk.course_version != manifest.course_version
            or chunk.knowledge_version != manifest.knowledge_version
        ):
            raise AcademicRetrievalError(
                "Phát hiện kết quả retrieval bị lẫn môn hoặc sai knowledge version."
            )
        return chunk

    def _dense_search(
        self,
        query: str,
        *,
        limit: int,
        min_score: float,
        document_id: str | None,
    ) -> list[_Candidate]:
        vector = self._query_vector(self.encoder, query)
        if len(vector) != self.embedding_manifest.vector_dimension:
            raise AcademicRetrievalError(
                "Query vector không cùng số chiều với course index."
            )
        points = self.client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            query_filter=self._qdrant_filter(document_id),
            limit=limit,
            with_payload=True,
            with_vectors=False,
            score_threshold=min_score,
        )
        candidates = []
        for point in points:
            payload = point.payload or {}
            candidates.append(
                _Candidate(
                    chunk=self._chunk_from_payload(payload),
                    dense_score=float(point.score),
                )
            )
        return candidates

    @staticmethod
    def _fuse(
        dense: list[_Candidate],
        keyword: list[_Candidate],
        top_k: int,
    ) -> list[AcademicRetrievalHit]:
        fused: dict[str, dict[str, Any]] = {}
        for source, candidates in (("dense", dense), ("keyword", keyword)):
            for rank, candidate in enumerate(candidates, start=1):
                chunk_id = candidate.chunk.chunk_id
                entry = fused.setdefault(
                    chunk_id,
                    {
                        "chunk": candidate.chunk,
                        "score": 0.0,
                        "dense_score": 0.0,
                        "keyword_score": 0.0,
                        "retrieval_sources": [],
                    },
                )
                entry["score"] += 1.0 / (RRF_K + rank)
                entry["dense_score"] = max(
                    entry["dense_score"],
                    candidate.dense_score,
                )
                entry["keyword_score"] = max(
                    entry["keyword_score"],
                    candidate.keyword_score,
                )
                if source not in entry["retrieval_sources"]:
                    entry["retrieval_sources"].append(source)

        ranked = sorted(
            fused.values(),
            key=lambda entry: (
                entry["score"],
                entry["dense_score"],
                entry["keyword_score"],
            ),
            reverse=True,
        )[:top_k]
        return [
            AcademicRetrievalHit(
                chunk_id=entry["chunk"].chunk_id,
                course_id=entry["chunk"].course_id,
                course_version=entry["chunk"].course_version,
                knowledge_version=entry["chunk"].knowledge_version,
                document_id=entry["chunk"].document_id,
                section_id=entry["chunk"].section_id,
                chapter_id=entry["chunk"].chapter_id,
                content=entry["chunk"].content,
                citation=entry["chunk"].citation,
                score=round(entry["score"], 8),
                dense_score=round(entry["dense_score"], 6),
                keyword_score=round(entry["keyword_score"], 6),
                retrieval_sources=entry["retrieval_sources"],
            )
            for entry in ranked
        ]

    def search(
        self,
        query: str,
        *,
        course_id: str,
        course_version: str | None = None,
        knowledge_version: str | None = None,
        top_k: int = 5,
        min_dense_score: float = 0.25,
        document_id: str | None = None,
        modes: tuple[str, ...] = ("dense", "keyword"),
    ) -> AcademicRetrievalResult:
        normalized_query = " ".join(query.split())
        if not normalized_query:
            raise ValueError("query không được để trống.")
        if len(normalized_query) > 2000:
            raise ValueError("query không được vượt quá 2000 ký tự.")
        if top_k <= 0 or top_k > 20:
            raise ValueError("top_k phải từ 1 đến 20.")
        if not 0 <= min_dense_score <= 1:
            raise ValueError("min_dense_score phải từ 0 đến 1.")
        requested_modes = tuple(dict.fromkeys(modes))
        if not requested_modes or any(
            mode not in {"dense", "keyword"}
            for mode in requested_modes
        ):
            raise ValueError("modes chỉ nhận dense và keyword.")

        manifest = self.processed.manifest
        if course_id != manifest.course_id:
            raise AcademicRetrievalError(
                "Retriever đang được scope cho course_id khác."
            )
        if course_version and course_version != manifest.course_version:
            raise AcademicRetrievalError(
                "Retriever đang được scope cho course_version khác."
            )
        if knowledge_version and knowledge_version != manifest.knowledge_version:
            raise AcademicRetrievalError(
                "Retriever đang được scope cho knowledge_version khác."
            )

        candidate_limit = min(60, max(top_k * 3, top_k))
        dense = (
            self._dense_search(
                normalized_query,
                limit=candidate_limit,
                min_score=min_dense_score,
                document_id=document_id,
            )
            if "dense" in requested_modes
            else []
        )
        keyword = []
        if "keyword" in requested_modes:
            keyword = [
                _Candidate(
                    chunk=match.chunk,
                    keyword_score=match.score,
                )
                for match in self.lexical_index.search(
                    normalized_query,
                    limit=candidate_limit,
                    document_id=document_id,
                )
            ]

        hits = self._fuse(dense, keyword, top_k)
        return AcademicRetrievalResult(
            query=normalized_query,
            course_id=manifest.course_id,
            course_version=manifest.course_version,
            knowledge_version=manifest.knowledge_version,
            collection_name=self.collection_name,
            branch_counts={"dense": len(dense), "keyword": len(keyword)},
            hits=hits,
        )

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
