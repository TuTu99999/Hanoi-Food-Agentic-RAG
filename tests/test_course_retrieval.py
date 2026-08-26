import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from qdrant_client import QdrantClient

from academic_retrieval.artifacts import (
    CourseArtifactError,
    build_course_embeddings,
    json_sha256,
    load_processed_course,
)
from academic_retrieval.evaluation import evaluate_academic_retrieval
from academic_retrieval.qdrant_store import (
    load_course_vector_artifact,
    point_id_from_chunk_id,
    upload_course_vectors,
)
from academic_retrieval.service import (
    AcademicHybridRetriever,
    AcademicRetrievalError,
)
from courses.naming import vector_alias_for, vector_collection_for
from ingestion.service import ingest_course_package
from schemas.indexing import AcademicRetrievalCase


class FakeEncoder:
    def __init__(self, dimension=3):
        self.dimension = dimension
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((list(texts), kwargs))
        vectors = []
        for index, _text in enumerate(texts):
            vector = [0.0] * self.dimension
            vector[index % self.dimension] = 1.0
            vectors.append(vector)
        return vectors


class FakeUploadClient:
    def __init__(self):
        self.collections = {}
        self.payload_indexes = []
        self.aliases = {}

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, vectors_config):
        self.collections[collection_name] = {
            "vectors_config": vectors_config,
            "points": [],
        }

    def create_payload_index(
        self,
        collection_name,
        field_name,
        field_schema,
        wait,
    ):
        self.payload_indexes.append(
            (collection_name, field_name, field_schema, wait)
        )

    def upload_points(self, collection_name, points, **_kwargs):
        self.collections[collection_name]["points"] = list(points)

    def count(self, collection_name, exact):
        return SimpleNamespace(
            count=len(self.collections[collection_name]["points"])
        )

    def retrieve(
        self,
        collection_name,
        ids,
        with_payload,
        with_vectors,
    ):
        selected_ids = set(ids)
        return [
            SimpleNamespace(id=point.id, payload=point.payload)
            for point in self.collections[collection_name]["points"]
            if point.id in selected_ids
        ]

    def get_aliases(self):
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name=alias, collection_name=collection)
                for alias, collection in self.aliases.items()
            ]
        )

    def update_collection_aliases(self, change_aliases_operations):
        for operation in change_aliases_operations:
            delete_alias = getattr(operation, "delete_alias", None)
            create_alias = getattr(operation, "create_alias", None)
            if delete_alias is not None:
                self.aliases.pop(delete_alias.alias_name, None)
            if create_alias is not None:
                self.aliases[create_alias.alias_name] = (
                    create_alias.collection_name
                )


class FakeSearchClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.search_calls = []
        self.closed = False

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [
            SimpleNamespace(payload=payload, score=0.91 - index * 0.01)
            for index, payload in enumerate(self.payloads)
        ]

    def close(self):
        self.closed = True


def write_course_package(
    root: Path,
    *,
    course_id: str = "political_philosophy",
) -> Path:
    documents = root / "documents"
    documents.mkdir(parents=True)
    (documents / "lesson.md").write_text(
        "# Chương 1\n"
        "Vật chất là một phạm trù triết học.\n"
        "## Ý thức\n"
        "Ý thức phản ánh thế giới khách quan và tác động trở lại vật chất.",
        encoding="utf-8",
    )
    (root / "course.yaml").write_text(
        "\n".join(
            [
                f"course_id: {course_id}",
                "name: Môn lý luận chính trị kiểm thử",
                "domain: political_theory",
                "version: 1.0.0",
                "language: vi",
                "sources:",
                "  - path: documents/lesson.md",
                "    document_id: official_textbook",
                "    title: Giáo trình chính thức",
                "    source_type: official_textbook",
                "    source_authority: Nhà xuất bản kiểm thử",
                "    publication_year: 2025",
            ]
        ),
        encoding="utf-8",
    )
    return root


def build_artifacts(workspace: Path, *, course_id="political_philosophy"):
    package = write_course_package(workspace / "package", course_id=course_id)
    ingestion_result = ingest_course_package(
        package,
        output_root=workspace / "data" / "courses",
    )
    embedding_result = build_course_embeddings(
        ingestion_result.output_directory,
        encoder=FakeEncoder(),
        model_name="fake-multilingual-model",
    )
    return ingestion_result, embedding_result


class CourseEmbeddingArtifactTests(unittest.TestCase):
    def test_builds_versioned_embeddings_without_loading_real_model(self):
        with tempfile.TemporaryDirectory(prefix="course-index-") as directory:
            workspace = Path(directory)
            ingestion_result, embedding_result = build_artifacts(workspace)

            self.assertEqual(
                embedding_result.manifest.knowledge_version,
                ingestion_result.manifest.knowledge_version,
            )
            self.assertEqual(embedding_result.manifest.vector_dimension, 3)
            self.assertEqual(
                embedding_result.manifest.point_count,
                ingestion_result.manifest.chunk_count,
            )
            self.assertTrue(embedding_result.vectors_path.is_file())
            self.assertTrue(embedding_result.manifest_path.is_file())

            loaded = load_course_vector_artifact(
                embedding_result.output_directory
            )
            self.assertEqual(len(loaded.rows), embedding_result.manifest.point_count)

            with self.assertRaises(CourseArtifactError):
                build_course_embeddings(
                    ingestion_result.output_directory,
                    encoder=FakeEncoder(),
                    model_name="fake-multilingual-model",
                )

    def test_rejects_tampered_processed_chunks(self):
        with tempfile.TemporaryDirectory(prefix="course-index-") as directory:
            workspace = Path(directory)
            package = write_course_package(workspace / "package")
            ingestion_result = ingest_course_package(
                package,
                output_root=workspace / "data" / "courses",
            )
            chunks = json.loads(
                ingestion_result.chunks_path.read_text(encoding="utf-8")
            )
            chunks[0]["content"] = "Nội dung đã bị sửa ngoài pipeline."
            ingestion_result.chunks_path.write_text(
                json.dumps(chunks, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaises(CourseArtifactError):
                load_processed_course(ingestion_result.output_directory)

    def test_rejects_wrong_vector_dimension_even_with_updated_hash(self):
        with tempfile.TemporaryDirectory(prefix="course-index-") as directory:
            _ingestion_result, embedding_result = build_artifacts(Path(directory))
            rows = json.loads(
                embedding_result.vectors_path.read_text(encoding="utf-8")
            )
            manifest = json.loads(
                embedding_result.manifest_path.read_text(encoding="utf-8")
            )
            rows[0]["vector"].append(0.0)
            manifest["vector_artifact_sha256"] = json_sha256(rows)
            embedding_result.vectors_path.write_text(
                json.dumps(rows, ensure_ascii=False),
                encoding="utf-8",
            )
            embedding_result.manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaises(CourseArtifactError):
                load_course_vector_artifact(embedding_result.output_directory)


class CourseQdrantUploadTests(unittest.TestCase):
    def test_uploads_immutable_collection_and_switches_course_alias(self):
        with tempfile.TemporaryDirectory(prefix="course-index-") as directory:
            _ingestion_result, embedding_result = build_artifacts(Path(directory))
            artifact = load_course_vector_artifact(
                embedding_result.output_directory
            )
            client = FakeUploadClient()

            result = upload_course_vectors(client, artifact)

            self.assertEqual(
                result.alias_name,
                vector_alias_for("political_philosophy"),
            )
            self.assertEqual(client.aliases[result.alias_name], result.collection_name)
            indexed_fields = {item[1] for item in client.payload_indexes}
            self.assertTrue(
                {"course_id", "course_version", "knowledge_version"}
                <= indexed_fields
            )
            points = client.collections[result.collection_name]["points"]
            self.assertEqual(len(points), result.point_count)
            self.assertEqual(
                points[0].id,
                point_id_from_chunk_id(points[0].payload["chunk_id"]),
            )
            self.assertIn("citation", points[0].payload)

            with self.assertRaises(RuntimeError):
                upload_course_vectors(client, artifact)

    def test_two_courses_receive_different_collections_and_aliases(self):
        first = vector_collection_for(
            "political_philosophy",
            "1.0.0",
            "political_philosophy-aaaaaaaaaaaa",
        )
        second = vector_collection_for(
            "hochiminh_thought",
            "1.0.0",
            "hochiminh_thought-bbbbbbbbbbbb",
        )
        self.assertNotEqual(first, second)
        self.assertNotEqual(
            vector_alias_for("political_philosophy"),
            vector_alias_for("hochiminh_thought"),
        )

    def test_local_qdrant_upload_alias_filter_and_search_work_together(self):
        with tempfile.TemporaryDirectory(prefix="course-qdrant-") as directory:
            workspace = Path(directory)
            ingestion_result, embedding_result = build_artifacts(workspace)
            artifact = load_course_vector_artifact(
                embedding_result.output_directory
            )
            processed = load_processed_course(ingestion_result.output_directory)
            client = QdrantClient(":memory:")
            try:
                with self.assertLogs(level="WARNING"):
                    upload_result = upload_course_vectors(client, artifact)
                retriever = AcademicHybridRetriever(
                    processed=processed,
                    embedding_manifest=embedding_result.manifest,
                    client=client,
                    encoder=FakeEncoder(),
                )
                search_result = retriever.search(
                    "vật chất",
                    course_id="political_philosophy",
                    modes=("dense",),
                )

                self.assertEqual(
                    search_result.collection_name,
                    upload_result.alias_name,
                )
                self.assertGreaterEqual(len(search_result.hits), 1)
                self.assertTrue(
                    all(
                        hit.course_id == "political_philosophy"
                        for hit in search_result.hits
                    )
                )
            finally:
                client.close()


class AcademicHybridRetrieverTests(unittest.TestCase):
    def _retriever(self, workspace: Path, payloads=None):
        ingestion_result, embedding_result = build_artifacts(workspace)
        processed = load_processed_course(ingestion_result.output_directory)
        if payloads is None:
            payloads = [processed.chunks[0].model_dump(mode="json")]
            payloads[0]["source_type"] = payloads[0]["citation"]["source_type"]
        client = FakeSearchClient(payloads)
        encoder = FakeEncoder()
        retriever = AcademicHybridRetriever(
            processed=processed,
            embedding_manifest=embedding_result.manifest,
            client=client,
            encoder=encoder,
        )
        return retriever, client, processed

    def test_hybrid_search_returns_grounded_citation_and_course_filter(self):
        with tempfile.TemporaryDirectory(prefix="course-search-") as directory:
            retriever, client, processed = self._retriever(Path(directory))
            result = retriever.search(
                "vật chất là gì",
                course_id="political_philosophy",
                top_k=3,
            )

            self.assertGreaterEqual(len(result.hits), 1)
            first = result.hits[0]
            self.assertEqual(first.course_id, "political_philosophy")
            self.assertEqual(first.knowledge_version, processed.manifest.knowledge_version)
            self.assertIn("dense", first.retrieval_sources)
            self.assertIn("keyword", first.retrieval_sources)
            self.assertEqual(first.citation.document_id, "official_textbook")
            self.assertIsNotNone(first.citation.start_line)

            query_filter = client.search_calls[0]["query_filter"]
            filter_keys = {condition.key for condition in query_filter.must}
            self.assertEqual(
                filter_keys,
                {"course_id", "course_version", "knowledge_version"},
            )

    def test_keyword_mode_does_not_call_qdrant_or_encoder(self):
        with tempfile.TemporaryDirectory(prefix="course-search-") as directory:
            retriever, client, _processed = self._retriever(Path(directory))
            result = retriever.search(
                "ý thức",
                course_id="political_philosophy",
                modes=("keyword",),
            )
            self.assertGreaterEqual(len(result.hits), 1)
            self.assertEqual(client.search_calls, [])
            self.assertEqual(retriever.encoder.calls, [])
            self.assertEqual(result.hits[0].retrieval_sources, ["keyword"])

    def test_rejects_wrong_requested_course_before_search(self):
        with tempfile.TemporaryDirectory(prefix="course-search-") as directory:
            retriever, client, _processed = self._retriever(Path(directory))
            with self.assertRaises(AcademicRetrievalError):
                retriever.search(
                    "vật chất",
                    course_id="hochiminh_thought",
                )
            self.assertEqual(client.search_calls, [])

    def test_rejects_cross_course_payload_returned_by_qdrant(self):
        with tempfile.TemporaryDirectory(prefix="course-search-") as directory:
            workspace = Path(directory)
            ingestion_result, embedding_result = build_artifacts(workspace)
            processed = load_processed_course(ingestion_result.output_directory)
            foreign_payload = processed.chunks[0].model_dump(mode="json")
            foreign_payload["course_id"] = "hochiminh_thought"
            client = FakeSearchClient([foreign_payload])
            retriever = AcademicHybridRetriever(
                processed=processed,
                embedding_manifest=embedding_result.manifest,
                client=client,
                encoder=FakeEncoder(),
            )

            with self.assertRaises(AcademicRetrievalError):
                retriever.search(
                    "vật chất",
                    course_id="political_philosophy",
                    modes=("dense",),
                )

    def test_evaluation_reports_recall_mrr_citation_and_no_leakage(self):
        with tempfile.TemporaryDirectory(prefix="course-eval-") as directory:
            retriever, _client, processed = self._retriever(Path(directory))
            case = AcademicRetrievalCase(
                case_id="definition_001",
                query="phạm trù triết học",
                course_id="political_philosophy",
                course_version="1.0.0",
                expected_chunk_ids=[processed.chunks[0].chunk_id],
                top_k=5,
            )

            report = evaluate_academic_retrieval(
                retriever,
                [case],
                modes=("keyword",),
            )

            self.assertEqual(report.hit_rate_at_k, 1.0)
            self.assertEqual(report.recall_at_k, 1.0)
            self.assertEqual(report.mean_reciprocal_rank, 1.0)
            self.assertEqual(report.citation_completeness, 1.0)
            self.assertEqual(report.cross_course_leakage_count, 0)


if __name__ == "__main__":
    unittest.main()
