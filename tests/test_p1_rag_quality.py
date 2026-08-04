import asyncio
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ["APP_ENV"] = "test"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "p1-test-secret"
os.environ["LLM_API_KEY"] = "p1-test-llm-api-key"
os.environ["LLM_REASONING_EFFORT"] = "minimal"
os.environ["LLM_MAX_OUTPUT_TOKENS"] = "800"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["AUTH_COOKIE_SAMESITE"] = "lax"

from embedding.process_data import build_chunks, count_tokens, json_sha256
from embedding.retrieval_engine import RetrievalEngine, normalize_text
from embedding.upload_to_qdrant import (
    point_id_from_chunk_id,
    validate_vector_rows,
)
from core.resilience import CircuitBreaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WordTokenizer:
    """Small reversible tokenizer for deterministic chunking unit tests."""

    def __init__(self):
        self.token_to_id = {}
        self.id_to_token = {}

    def encode(self, text, add_special_tokens=False):
        del add_special_tokens
        token_ids = []
        for token in re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE):
            if token not in self.token_to_id:
                token_id = len(self.token_to_id) + 1
                self.token_to_id[token] = token_id
                self.id_to_token[token_id] = token
            token_ids.append(self.token_to_id[token])
        return token_ids

    def decode(self, token_ids):
        return " ".join(self.id_to_token[token_id] for token_id in token_ids)


class FakeEmbeddingModel:
    def encode(self, _query):
        return SimpleNamespace(tolist=lambda: [0.1, 0.2, 0.3])


class FakeQdrantClient:
    def __init__(self, results):
        self.results = results
        self.last_call = None

    def search(self, **kwargs):
        self.last_call = kwargs
        return self.results


class FakeRagRetriever:
    def __init__(self):
        self.last_call = None

    def search(self, **kwargs):
        self.last_call = kwargs
        return [
            {
                "score": 0.8,
                "match_score": 0.2,
                "ranking_score": 1.0,
                "domain": "food",
                "title": "Bánh mì sốt vang Đình Ngang",
                "address": "252 Hàng Bông, Hoàn Kiếm, Hà Nội",
                "district": "Hoàn Kiếm",
                "category": "Ẩm thực",
                "sub_category": "Bánh mì",
                "price_range": "35.000đ",
                "opening_hours": "06:00 - 22:00",
                "tags": ["bánh mì"],
                "content": "Quán nằm tại góc Đình Ngang.",
            }
        ]

    def search_with_metadata(self, **kwargs):
        documents = self.search(**kwargs)
        return SimpleNamespace(
            documents=documents,
            candidate_count=len(documents),
            accepted_count=len(documents),
            filter_match_count=1,
            branch_counts={"semantic": len(documents)},
            branch_errors=[],
            exact_shortcut_used=False,
        )


class FakeAsyncCompletionStream:
    def __init__(self, deltas, finish_reason=None):
        self.deltas = list(deltas)
        self.index = 0
        self.finish_reason = finish_reason
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.deltas):
            raise StopAsyncIteration

        content = self.deltas[self.index]
        self.index += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=content),
                    finish_reason=(
                        self.finish_reason
                        if self.index == len(self.deltas)
                        else None
                    ),
                )
            ]
        )

    async def close(self):
        self.closed = True


class CloseFailingCompletionStream(FakeAsyncCompletionStream):
    async def close(self):
        self.closed = True
        raise RuntimeError("cleanup failed")


class FakeAsyncCompletions:
    def __init__(self, response_stream):
        self.response_stream = response_stream
        self.last_call = None

    async def create(self, **kwargs):
        self.last_call = kwargs
        return self.response_stream


def make_hit(score, **payload):
    return SimpleNamespace(score=score, payload=payload)


class P1RagQualityTests(unittest.TestCase):
    def test_token_aware_chunks_include_overlap_and_metadata(self):
        tokenizer = WordTokenizer()
        item = {
            "id": "food_test",
            "title": "Quán kiểm thử",
            "category": "Ẩm thực",
            "sub_category": "Món Việt",
            "district": "Hoàn Kiếm",
            "address": "1 Phố Kiểm Thử, Hà Nội",
            "price_range": "30.000đ - 50.000đ",
            "opening_hours": "08:00 - 22:00",
            "description": (
                "Một hai ba bốn năm sáu bảy tám. "
                "Chín mười mười một mười hai mười ba mười bốn. "
                "Mười lăm mười sáu mười bảy mười tám mười chín hai mươi. "
                "Hai mốt hai hai hai ba hai bốn hai năm hai sáu."
            ),
            "tags": ["Kiểm thử", "Món Việt"],
        }

        chunks = build_chunks(
            items=[item],
            domain="food",
            tokenizer=tokenizer,
            max_tokens=60,
            overlap_tokens=4,
        )

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["parent_id"], "food_test")
        self.assertEqual(chunks[0]["domain"], "food")
        self.assertEqual(chunks[0]["district_normalized"], "hoan kiem")
        self.assertEqual(chunks[0]["category_normalized"], "am thuc")
        self.assertEqual(chunks[0]["tags"], ["Kiểm thử", "Món Việt"])
        self.assertTrue(chunks[0]["knowledge_version"].startswith("food-"))
        self.assertEqual(
            chunks[0]["verification_status"],
            "unverified",
        )
        self.assertIsNone(chunks[0]["source_url"])
        self.assertIn("Món Việt", chunks[0]["vector_text"])
        self.assertIn("30.000đ - 50.000đ", chunks[0]["vector_text"])
        self.assertTrue(
            all(
                count_tokens(tokenizer, chunk["vector_text"]) <= 60
                for chunk in chunks
            )
        )

        first_body = tokenizer.encode(chunks[0]["description"])
        second_body = tokenizer.encode(chunks[1]["description"])
        overlap = max(
            (
                size
                for size in range(1, min(4, len(first_body), len(second_body)) + 1)
                if first_body[-size:] == second_body[:size]
            ),
            default=0,
        )
        self.assertGreater(overlap, 0)

    def test_processed_data_covers_every_raw_parent(self):
        all_chunk_ids = set()
        for domain in ("food",):
            raw_path = PROJECT_ROOT / "data" / "raw" / f"{domain}_raw.json"
            chunk_path = (
                PROJECT_ROOT / "data" / "processed" / f"{domain}_chunks.json"
            )
            with raw_path.open("r", encoding="utf-8") as file:
                raw_items = json.load(file)
            with chunk_path.open("r", encoding="utf-8") as file:
                chunks = json.load(file)
            manifest_path = (
                PROJECT_ROOT
                / "data"
                / "processed"
                / f"{domain}_manifest.json"
            )
            with manifest_path.open("r", encoding="utf-8") as file:
                manifest = json.load(file)

            raw_parent_ids = {
                item["id"]
                for item in raw_items
                if (
                    domain != "food"
                    or normalize_text(item["category"]) == "am thuc"
                )
            }
            chunk_parent_ids = {chunk["parent_id"] for chunk in chunks}
            self.assertEqual(chunk_parent_ids, raw_parent_ids)
            if domain == "food":
                self.assertEqual(len(chunk_parent_ids), 418)
                self.assertEqual(len(chunks), 773)
                self.assertEqual(
                    len(
                        {
                            chunk["knowledge_version"]
                            for chunk in chunks
                        }
                    ),
                    1,
                )
                self.assertEqual(
                    manifest["knowledge_version"],
                    chunks[0]["knowledge_version"],
                )
                self.assertEqual(
                    manifest["dataset_sha256"],
                    json_sha256(raw_items),
                )
                self.assertEqual(
                    manifest["lexical_artifact_sha256"],
                    json_sha256(chunks),
                )

            for chunk in chunks:
                self.assertNotIn(chunk["chunk_id"], all_chunk_ids)
                all_chunk_ids.add(chunk["chunk_id"])
                self.assertEqual(chunk["domain"], domain)
                self.assertIn("district_normalized", chunk)
                self.assertIn("category_normalized", chunk)
                if domain == "food":
                    self.assertIn("sub_category_normalized", chunk)
                    self.assertIn("tags_normalized", chunk)
                    self.assertIn("price_min", chunk)
                    self.assertIn("price_max", chunk)
                    self.assertIn("opening_intervals", chunk)
                    self.assertIn("source_url", chunk)
                    self.assertIn("last_verified_at", chunk)
                    self.assertIn("verification_status", chunk)

    def test_retrieval_filters_reranks_and_groups_entities(self):
        results = [
            make_hit(
                0.70,
                chunk_id="food_wrong_chunk_001",
                chunk_index=1,
                parent_id="food_wrong",
                domain="food",
                title="Xôi rán nướng lòng Bà Thảo",
                address="Hoàn Kiếm, Hà Nội",
                district="Hoàn Kiếm",
                category="Ẩm thực",
                description="Kết quả semantic cao nhưng sai tên quán.",
            ),
            make_hit(
                0.47,
                chunk_id="food_025_chunk_001",
                chunk_index=1,
                parent_id="food_025",
                domain="food",
                title="Bánh mì sốt vang Đình Ngang",
                address="252 Hàng Bông, Hoàn Kiếm, Hà Nội",
                district="Hoàn Kiếm",
                category="Ẩm thực",
                description="Địa chỉ quán là 252 Hàng Bông.",
            ),
            make_hit(
                0.40,
                chunk_id="food_025_chunk_002",
                chunk_index=2,
                parent_id="food_025",
                domain="food",
                title="Bánh mì sốt vang Đình Ngang",
                address="252 Hàng Bông, Hoàn Kiếm, Hà Nội",
                district="Hoàn Kiếm",
                category="Ẩm thực",
                description="Quán nằm tại góc Đình Ngang.",
            ),
            make_hit(
                0.49,
                chunk_id="food_noise_chunk_001",
                parent_id="food_noise",
                title="Kết quả nhiễu",
                address="Hà Nội",
                district="Hoàn Kiếm",
                description="Không được vượt qua threshold.",
            ),
        ]
        client = FakeQdrantClient(results)
        retriever = RetrievalEngine.__new__(RetrievalEngine)
        retriever.client = client
        retriever.model = FakeEmbeddingModel()
        retriever.collection_name = "hanoi_food_current"
        retriever.retry_attempts = 1
        retriever.retry_base_seconds = 0
        retriever.retry_max_seconds = 0
        retriever.circuit_breaker = CircuitBreaker(3, 30)

        documents = retriever.search(
            query="cho t vị trí Bánh mì sốt vang Đình Ngan",
            top_k=3,
            district_filter="hoan kiem",
            domain_filter="food",
            min_score=0.5,
        )

        self.assertEqual(documents[0]["parent_id"], "food_025")
        self.assertEqual(
            documents[0]["chunk_ids"],
            ["food_025_chunk_001", "food_025_chunk_002"],
        )
        self.assertIn("252 Hàng Bông", documents[0]["content"])
        self.assertIn("góc Đình Ngang", documents[0]["content"])
        self.assertNotIn(
            "food_noise",
            {document["parent_id"] for document in documents},
        )

        conditions = client.last_call["query_filter"].must
        filter_values = {
            condition.key: condition.match.value
            for condition in conditions
        }
        self.assertEqual(filter_values["district_normalized"], "hoan kiem")
        self.assertEqual(filter_values["domain"], "food")
        self.assertEqual(
            client.last_call["collection_name"],
            "hanoi_food_current",
        )

    def test_normalization_and_point_ids_are_stable(self):
        self.assertEqual(normalize_text("  Hoàn-Kiếm  "), "hoan kiem")
        first = point_id_from_chunk_id("food_001_chunk_001")
        second = point_id_from_chunk_id("food_001_chunk_001")
        other = point_id_from_chunk_id("food_001_chunk_002")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

        vector_size = validate_vector_rows(
            [
                {
                    "chunk_id": "food_001_chunk_001",
                    "parent_id": "food_001",
                    "domain": "food",
                    "knowledge_version": "food-test-v1",
                    "title": "Phở Thìn",
                    "title_normalized": "pho thin",
                    "address": "Hà Nội",
                    "address_normalized": "ha noi",
                    "district": "Hoàn Kiếm",
                    "district_normalized": "hoan kiem",
                    "price_range": "N/A",
                    "price_min": None,
                    "price_max": None,
                    "price_currency": "VND",
                    "price_status": "unknown",
                    "opening_hours": "N/A",
                    "opening_intervals": [],
                    "opening_status": "unknown",
                    "opening_schedule_scope": "unknown",
                    "category": "Ẩm thực",
                    "category_normalized": "am thuc",
                    "sub_category": "Phở",
                    "sub_category_normalized": "pho",
                    "tags": [],
                    "tags_normalized": [],
                    "description": "Mô tả",
                    "vector_text": "Phở Thìn tại Hà Nội",
                    "source_name": None,
                    "source_url": None,
                    "retrieved_at": None,
                    "last_verified_at": None,
                    "license": None,
                    "verification_status": "unverified",
                    "vector": [0.1, 0.2, 0.3],
                },
                {
                    "chunk_id": "food_001_chunk_002",
                    "parent_id": "food_001",
                    "domain": "food",
                    "knowledge_version": "food-test-v1",
                    "title": "Phở Thìn",
                    "title_normalized": "pho thin",
                    "address": "Hà Nội",
                    "address_normalized": "ha noi",
                    "district": "Hoàn Kiếm",
                    "district_normalized": "hoan kiem",
                    "price_range": "60.000đ - 100.000đ",
                    "price_min": 60000,
                    "price_max": 100000,
                    "price_currency": "VND",
                    "price_status": "known",
                    "opening_hours": "06:00 - 13:00",
                    "opening_intervals": [
                        {
                            "opens": "06:00",
                            "closes": "13:00",
                            "closes_next_day": False,
                        }
                    ],
                    "opening_status": "known",
                    "opening_schedule_scope": "daily_assumed",
                    "category": "Ẩm thực",
                    "category_normalized": "am thuc",
                    "sub_category": "Phở",
                    "sub_category_normalized": "pho",
                    "tags": [],
                    "tags_normalized": [],
                    "description": "Mô tả",
                    "vector_text": "Phở Thìn tại Hà Nội",
                    "source_name": None,
                    "source_url": None,
                    "retrieved_at": None,
                    "last_verified_at": None,
                    "license": None,
                    "verification_status": "unverified",
                    "vector": [0.4, 0.5, 0.6],
                },
            ]
        )
        self.assertEqual(vector_size, 3)

    def test_rag_stream_forwards_real_deltas_and_bounded_history(self):
        from rag.Rag import RAGPipeline

        retriever = FakeRagRetriever()
        response_stream = FakeAsyncCompletionStream(
            ["Địa chỉ ", "là 252 Hàng Bông."]
        )
        completions = FakeAsyncCompletions(response_stream)

        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline.retriever = retriever
        pipeline.async_ai_client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        pipeline.llm_model = "test-model"
        pipeline.llm_circuit_breaker = CircuitBreaker(3, 30)

        history = [
            {
                "role": "user",
                "content": "Cho tôi địa chỉ Bánh mì sốt vang Đình Ngang",
            },
            {
                "role": "assistant",
                "content": "Bạn muốn hỏi thêm thông tin nào?",
            },
        ]

        async def collect_deltas():
            return [
                delta
                async for delta in pipeline.stream(
                    user_question="Quán đó ở đâu?",
                    collection_name="hanoi_food_current",
                    district="Hoàn Kiếm",
                    history=history,
                )
            ]

        deltas = asyncio.run(collect_deltas())

        self.assertEqual(deltas, ["Địa chỉ ", "là 252 Hàng Bông."])
        self.assertTrue(response_stream.closed)
        self.assertTrue(completions.last_call["stream"])
        self.assertEqual(
            completions.last_call["reasoning_effort"],
            "minimal",
        )
        self.assertEqual(completions.last_call["max_tokens"], 800)
        self.assertEqual(
            completions.last_call["messages"][1:3],
            history,
        )
        self.assertIn(
            history[0]["content"],
            retriever.last_call["query"],
        )

    def test_stream_cleanup_error_does_not_mask_answer(self):
        from rag.Rag import RAGPipeline

        response_stream = CloseFailingCompletionStream(["Kết quả hợp lệ"])
        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline.retriever = FakeRagRetriever()
        pipeline.async_ai_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=FakeAsyncCompletions(response_stream)
            )
        )
        pipeline.llm_model = "test-model"
        pipeline.llm_circuit_breaker = CircuitBreaker(3, 30)

        async def collect_deltas():
            return [
                delta
                async for delta in pipeline.stream(
                    user_question="Tìm quán ăn",
                    collection_name="hanoi_food_current",
                    district="Cầu Giấy",
                    history=[],
                )
            ]

        self.assertEqual(
            asyncio.run(collect_deltas()),
            ["Kết quả hợp lệ"],
        )
        self.assertTrue(response_stream.closed)

    def test_stream_rejects_truncated_llm_answer(self):
        from rag.Rag import RAGPipeline

        response_stream = FakeAsyncCompletionStream(
            ["Câu trả lời đang dở"],
            finish_reason="length",
        )
        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline.retriever = FakeRagRetriever()
        pipeline.async_ai_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=FakeAsyncCompletions(response_stream)
            )
        )
        pipeline.llm_model = "test-model"
        pipeline.llm_circuit_breaker = CircuitBreaker(3, 30)

        async def collect_deltas():
            return [
                delta
                async for delta in pipeline.stream(
                    user_question="Tìm quán ăn",
                    collection_name="hanoi_food_current",
                    district="Cầu Giấy",
                    history=[],
                )
            ]

        with self.assertRaisesRegex(RuntimeError, "cắt ngắn"):
            asyncio.run(collect_deltas())
        self.assertTrue(response_stream.closed)

    def test_short_topic_switch_does_not_contaminate_search_query(self):
        from rag.Rag import RAGPipeline

        history = [
            {
                "role": "user",
                "content": "Tìm quán phở ở Hoàn Kiếm",
            }
        ]

        search_query = RAGPipeline._build_search_query(
            "Tư vấn laptop gaming",
            history,
        )

        self.assertEqual(search_query, "Tư vấn laptop gaming")

    def test_retrieval_engine_uses_configured_model_and_qdrant_url(self):
        with (
            patch(
                "embedding.retrieval_engine.QdrantClient"
            ) as qdrant_client,
            patch(
                "embedding.retrieval_engine.SentenceTransformer"
            ) as sentence_transformer,
        ):
            RetrievalEngine(
                qdrant_url="http://qdrant:6333",
                qdrant_api_key="test-key",
                collection_name="test-collection",
                embedding_model="test-embedding-model",
            )

        qdrant_client.assert_called_once_with(
            url="http://qdrant:6333",
            api_key="test-key",
            timeout=1.0,
        )
        sentence_transformer.assert_called_once_with(
            "test-embedding-model",
            local_files_only=True,
        )

    def test_retrieval_engine_reads_qdrant_url_without_explicit_arguments(self):
        with (
            patch.dict(
                os.environ,
                {
                    "QDRANT_URL": "http://qdrant:6333",
                    "QDRANT_API_KEY": "environment-key",
                    "QDRANT_PORT": "tcp://10.0.0.1:6333",
                },
            ),
            patch(
                "embedding.retrieval_engine.QdrantClient"
            ) as qdrant_client,
            patch("embedding.retrieval_engine.SentenceTransformer"),
        ):
            RetrievalEngine()

        qdrant_client.assert_called_once_with(
            url="http://qdrant:6333",
            api_key="environment-key",
            timeout=1.0,
        )

    def test_rag_clients_use_application_settings(self):
        from core.config import settings
        from rag.Rag import RAGPipeline

        with (
            patch.object(settings, "LLM_API_KEY", "test-token"),
            patch.object(settings, "LLM_BASE_URL", "https://llm.example/v1"),
            patch.object(settings, "LLM_MODEL", "test-llm"),
            patch.object(settings, "LLM_TIMEOUT_SECONDS", 17),
            patch("rag.Rag.OpenAI") as sync_client,
            patch("rag.Rag.AsyncOpenAI") as async_client,
        ):
            pipeline = RAGPipeline()

        expected_options = {
            "base_url": "https://llm.example/v1",
            "api_key": "test-token",
            "timeout": 17,
            "max_retries": 0,
        }
        sync_client.assert_called_once_with(**expected_options)
        async_client.assert_called_once_with(**expected_options)
        self.assertEqual(pipeline.llm_model, "test-llm")


if __name__ == "__main__":
    unittest.main()
