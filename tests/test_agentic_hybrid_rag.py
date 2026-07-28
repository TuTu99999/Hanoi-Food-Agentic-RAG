from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest

from embedding.catalog_schema import (
    is_open_at,
    parse_opening_hours,
    parse_price_range,
)
from embedding.lexical_index import LexicalIndex
from embedding.retrieval_engine import RetrievalEngine
from rag.agentic_graph import (
    HARD_FILTER_EMPTY,
    LOW_RELEVANCE,
    OUT_OF_SCOPE,
    SUFFICIENT,
    AgenticRAGWorkflow,
)
from rag.query_router import QueryRouter


def catalog_row(
    parent_id: str,
    title: str,
    *,
    description: str,
    district: str = "Hoàn Kiếm",
    sub_category: str = "Món Việt",
) -> dict:
    return {
        "chunk_id": f"{parent_id}_chunk_001",
        "parent_id": parent_id,
        "chunk_index": 1,
        "domain": "food",
        "title": title,
        "address": f"1 Phố {title}, {district}, Hà Nội",
        "district": district,
        "category": "Ẩm thực",
        "sub_category": sub_category,
        "price_range": "30.000đ - 60.000đ",
        "opening_hours": "06:00 - 22:00",
        "tags": [sub_category],
        "description": description,
    }


def evidence_document(
    parent_id: str = "food_001",
    *,
    title: str = "Phở Thìn Bờ Hồ",
    semantic_score: float = 0.8,
    domain: str = "food",
) -> dict:
    return {
        "parent_id": parent_id,
        "domain": domain,
        "title": title,
        "address": "61 Đinh Tiên Hoàng, Hoàn Kiếm, Hà Nội",
        "district": "Hoàn Kiếm",
        "semantic_score": semantic_score,
        "score": semantic_score,
        "exact_score": 0.0,
        "keyword_coverage": 0.0,
        "price_range": "60.000đ - 100.000đ",
        "price_min": 60000,
        "price_max": 100000,
        "price_status": "known",
        "opening_hours": "06:00 - 22:00",
        "opening_intervals": [
            {
                "opens": "06:00",
                "closes": "22:00",
                "closes_next_day": False,
            }
        ],
        "opening_status": "known",
        "content": "Quán phở truyền thống tại Hà Nội.",
    }


def retrieval_result(
    documents: list[dict],
    *,
    filter_match_count: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        documents=documents,
        candidate_count=len(documents),
        accepted_count=len(documents),
        filter_match_count=filter_match_count,
        branch_counts={"semantic": len(documents)},
        branch_errors=[],
        exact_shortcut_used=False,
    )


class FixedRouter:
    confidence_threshold = 0.58

    def __init__(
        self,
        intent: str = "food_search",
        confidence: float = 0.99,
        source: str = "ml",
    ):
        self.prediction = SimpleNamespace(
            intent=intent,
            confidence=confidence,
            source=source,
        )

    def predict(self, _query: str) -> SimpleNamespace:
        return self.prediction


class RecordingRetriever:
    def __init__(self, results: list[SimpleNamespace]):
        self.results = list(results)
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def search_with_metadata(self, **kwargs) -> SimpleNamespace:
        with self._lock:
            self.calls.append(dict(kwargs))
            index = min(len(self.calls) - 1, len(self.results) - 1)
            return self.results[index]


class FailingEmbeddingModel:
    def encode(self, _query):
        raise AssertionError("Exact shortcut must not create an embedding.")


class AgenticHybridRAGTests(unittest.TestCase):
    def test_catalog_parsers_normalize_price_and_split_hours(self):
        price = parse_price_range("60.000đ - 100.000đ")
        hours = parse_opening_hours(
            "06:00 - 13:00 | 17:00 - 23:00"
        )

        self.assertEqual(price["price_min"], 60000)
        self.assertEqual(price["price_max"], 100000)
        self.assertEqual(price["price_status"], "known")
        self.assertEqual(
            hours["opening_intervals"],
            [
                {
                    "opens": "06:00",
                    "closes": "13:00",
                    "closes_next_day": False,
                },
                {
                    "opens": "17:00",
                    "closes": "23:00",
                    "closes_next_day": False,
                },
            ],
        )

    def test_opening_hours_parser_marks_overnight_interval(self):
        result = parse_opening_hours("11:00 - 02:00 (đêm)")

        self.assertEqual(result["opening_status"], "known")
        self.assertEqual(
            result["opening_intervals"],
            [
                {
                    "opens": "11:00",
                    "closes": "02:00",
                    "closes_next_day": True,
                }
            ],
        )

    def test_opening_hours_parser_rejects_invalid_or_partial_values(self):
        self.assertEqual(
            parse_opening_hours("06:00 - 22:00 ghi chú")[
                "opening_status"
            ],
            "unknown",
        )
        self.assertEqual(
            parse_opening_hours("24:00 - 02:00")["opening_status"],
            "invalid",
        )
        self.assertEqual(
            parse_opening_hours("08:00 - 08:00")["opening_status"],
            "invalid",
        )

    def test_open_at_supports_normal_and_overnight_intervals(self):
        normal = parse_opening_hours("06:00 - 22:00")[
            "opening_intervals"
        ]
        overnight = parse_opening_hours("18:00 - 02:00")[
            "opening_intervals"
        ]

        self.assertTrue(is_open_at(normal, "21:59"))
        self.assertFalse(is_open_at(normal, "22:00"))
        self.assertTrue(is_open_at(overnight, "23:00"))
        self.assertTrue(is_open_at(overnight, "01:30"))
        self.assertFalse(is_open_at(overnight, "12:00"))

    def test_lexical_index_handles_typo_and_no_accent_exact_query(self):
        index = LexicalIndex(
            [
                catalog_row(
                    "food_025",
                    "Bánh mì sốt vang Đình Ngang",
                    description="Quán nằm tại góc Đình Ngang.",
                    sub_category="Bánh mì",
                ),
                catalog_row(
                    "food_003",
                    "Cà phê Giảng",
                    description="Quán cà phê trứng lâu đời.",
                    sub_category="Cà phê",
                ),
            ]
        )

        results = index.exact_search(
            "cho t dia chi banh mi sot vang dinh ngan"
        )

        self.assertTrue(results)
        self.assertEqual(results[0]["parent_id"], "food_025")
        self.assertGreaterEqual(results[0]["exact_score"], 0.84)

    def test_bm25_returns_an_independent_lexical_candidate(self):
        index = LexicalIndex(
            [
                catalog_row(
                    "food_bun_cha",
                    "Bún chả Hương Liên",
                    description=(
                        "Bún chả truyền thống với thịt nướng và nước chấm."
                    ),
                    sub_category="Bún chả",
                ),
                catalog_row(
                    "food_sushi",
                    "Sushi Sakura",
                    description="Nhà hàng Nhật chuyên sushi và sashimi.",
                    sub_category="Món Nhật",
                ),
            ]
        )

        results = index.keyword_search("bun cha truyen thong")

        self.assertTrue(results)
        self.assertEqual(results[0]["parent_id"], "food_bun_cha")
        self.assertIn("keyword", results[0]["retrieval_sources"])
        self.assertGreater(results[0]["keyword_score"], 0)

    def test_exact_shortcut_does_not_call_embedding(self):
        engine = RetrievalEngine.__new__(RetrievalEngine)
        engine.lexical_index = LexicalIndex(
            [
                catalog_row(
                    "food_025",
                    "Bánh mì sốt vang Đình Ngang",
                    description="Quán nằm tại góc Đình Ngang.",
                    sub_category="Bánh mì",
                )
            ]
        )
        engine.model = FailingEmbeddingModel()

        result = engine.search_with_metadata(
            query="địa chỉ Bánh mì sốt vang Đình Ngang",
            top_k=3,
            search_modes=("exact", "keyword", "semantic"),
            allow_exact_shortcut=True,
        )

        self.assertTrue(result.exact_shortcut_used)
        self.assertEqual(result.documents[0]["parent_id"], "food_025")
        self.assertEqual(result.branch_counts, {"exact": 1})

    def test_exact_shortcut_requires_one_unambiguous_entity(self):
        engine = RetrievalEngine.__new__(RetrievalEngine)
        engine.lexical_index = LexicalIndex(
            [
                catalog_row(
                    "food_first",
                    "Quán Ngon",
                    description="Cơ sở thứ nhất.",
                ),
                catalog_row(
                    "food_second",
                    "Quán Ngon",
                    description="Cơ sở thứ hai.",
                ),
            ]
        )
        semantic_queries = []

        def semantic_search(**kwargs):
            semantic_queries.append(kwargs["query"])
            return [], 0

        engine._semantic_search = semantic_search

        result = engine.search_with_metadata(
            query="địa chỉ Quán Ngon",
            top_k=3,
            search_modes=("exact", "keyword", "semantic"),
            allow_exact_shortcut=True,
        )

        self.assertFalse(result.exact_shortcut_used)
        self.assertEqual(semantic_queries, ["địa chỉ Quán Ngon"])

    def test_rrf_is_deterministic_and_ignores_raw_score_scale(self):
        first_groups = {
            "exact": [
                {"parent_id": "a", "exact_score": 0.99},
                {"parent_id": "b", "exact_score": 0.95},
            ],
            "semantic": [
                {"parent_id": "b", "semantic_score": 0.91},
                {"parent_id": "a", "semantic_score": 0.80},
            ],
        }
        scaled_groups = {
            "exact": [
                {"parent_id": "a", "exact_score": 9999},
                {"parent_id": "b", "exact_score": 5000},
            ],
            "semantic": [
                {"parent_id": "b", "semantic_score": 0.0009},
                {"parent_id": "a", "semantic_score": 0.0001},
            ],
        }

        first = RetrievalEngine._fuse_rankings(first_groups, top_k=2)
        repeated = RetrievalEngine._fuse_rankings(first_groups, top_k=2)
        scaled = RetrievalEngine._fuse_rankings(scaled_groups, top_k=2)

        self.assertEqual(
            [document["parent_id"] for document in first],
            [document["parent_id"] for document in repeated],
        )
        self.assertEqual(
            [document["parent_id"] for document in first],
            [document["parent_id"] for document in scaled],
        )
        self.assertEqual(
            [document["ranking_score"] for document in first],
            [document["ranking_score"] for document in scaled],
        )

    def test_qdrant_filter_applies_price_before_vector_search(self):
        search_filter = RetrievalEngine._build_filter(
            district="Hoàn Kiếm",
            domain="food",
            category=None,
            price_max=50000,
        )
        conditions = {
            condition.key: condition
            for condition in search_filter.must
        }

        self.assertEqual(
            conditions["district_normalized"].match.value,
            "hoan kiem",
        )
        self.assertEqual(conditions["domain"].match.value, "food")
        self.assertEqual(conditions["price_max"].range.lte, 50000)

    def test_workflow_forces_food_and_drops_travel_documents(self):
        retriever = RecordingRetriever(
            [
                retrieval_result(
                    [
                        evidence_document(
                            "travel_001",
                            title="Hồ Hoàn Kiếm",
                            domain="travel",
                        ),
                        evidence_document(),
                    ]
                )
            ]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(),
        )

        result = workflow.invoke("tìm quán phở ngon")

        self.assertEqual(retriever.calls[0]["domain_filter"], "food")
        self.assertEqual(
            retriever.calls[0]["search_modes"],
            ("exact", "keyword", "semantic"),
        )
        self.assertEqual(
            [document["domain"] for document in result.documents],
            ["food"],
        )

    def test_sufficient_evidence_does_not_retry(self):
        retriever = RecordingRetriever(
            [retrieval_result([evidence_document()])]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(),
        )

        result = workflow.invoke("tìm quán phở ngon")

        self.assertEqual(result.evidence_reason, SUFFICIENT)
        self.assertTrue(result.should_generate)
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(len(retriever.calls), 1)

    def test_workflow_keeps_only_documents_with_sufficient_evidence(self):
        weak_document = evidence_document(
            parent_id="food_weak",
            semantic_score=0.2,
        )
        strong_document = evidence_document(
            parent_id="food_strong",
            semantic_score=0.8,
        )
        retriever = RecordingRetriever(
            [retrieval_result([weak_document, strong_document])]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(),
        )

        result = workflow.invoke("tìm quán phở ngon")

        self.assertEqual(result.evidence_reason, SUFFICIENT)
        self.assertEqual(
            [document["parent_id"] for document in result.documents],
            ["food_strong"],
        )
        self.assertEqual(result.accepted_count, 1)

    def test_low_relevance_retries_exactly_once(self):
        retriever = RecordingRetriever(
            [
                retrieval_result([]),
                retrieval_result([]),
            ]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(),
        )

        result = workflow.invoke("cho tôi một quán thật lạ")

        self.assertEqual(result.evidence_reason, LOW_RELEVANCE)
        self.assertFalse(result.should_generate)
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(len(retriever.calls), 2)
        self.assertNotEqual(
            retriever.calls[0]["query"],
            retriever.calls[1]["query"],
        )

    def test_empty_hard_filter_does_not_retry(self):
        retriever = RecordingRetriever(
            [retrieval_result([], filter_match_count=0)]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(),
        )

        result = workflow.invoke(
            "tìm quán phở tại Hoàn Kiếm",
            district="Hoàn Kiếm",
        )

        self.assertEqual(result.evidence_reason, HARD_FILTER_EMPTY)
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(len(retriever.calls), 1)

    def test_price_and_opening_filters_are_hard_constraints(self):
        retriever = RecordingRetriever(
            [retrieval_result([], filter_match_count=0)]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(),
        )

        result = workflow.invoke(
            "tìm quán phở dưới 50k còn mở lúc 23h"
        )

        self.assertEqual(result.evidence_reason, HARD_FILTER_EMPTY)
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(retriever.calls[0]["price_max_filter"], 50000)
        self.assertEqual(retriever.calls[0]["open_at_filter"], "23:00")

    def test_keyword_overlap_is_not_evidence_for_router_fallback(self):
        weak_document = evidence_document(semantic_score=0.2)
        weak_document["keyword_coverage"] = 1.0
        retriever = RecordingRetriever(
            [
                retrieval_result([weak_document]),
                retrieval_result([weak_document]),
            ]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(
                intent="unknown",
                confidence=0.0,
                source="fallback",
            ),
        )

        result = workflow.invoke("lập báo cáo hoạt động tháng này")

        self.assertEqual(result.evidence_reason, LOW_RELEVANCE)
        self.assertFalse(result.should_generate)
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(len(retriever.calls), 2)

    def test_keyword_overlap_cannot_override_wrong_ml_route(self):
        weak_document = evidence_document(semantic_score=0.2)
        weak_document["keyword_coverage"] = 1.0
        retriever = RecordingRetriever(
            [
                retrieval_result([weak_document]),
                retrieval_result([weak_document]),
            ]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(
                intent="entity_lookup",
                confidence=0.99,
                source="ml",
            ),
        )

        result = workflow.invoke("giá điện thoại bao nhiêu")

        self.assertEqual(result.evidence_reason, LOW_RELEVANCE)
        self.assertFalse(result.should_generate)
        self.assertEqual(result.retry_count, 1)

    def test_out_of_scope_query_skips_retrieval(self):
        retriever = RecordingRetriever(
            [retrieval_result([evidence_document()])]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(intent="out_of_scope"),
        )

        result = workflow.invoke("hướng dẫn tôi viết code Python")

        self.assertEqual(result.evidence_reason, OUT_OF_SCOPE)
        self.assertFalse(result.should_generate)
        self.assertEqual(retriever.calls, [])

    def test_travel_query_is_out_of_scope_for_food_only_runtime(self):
        retriever = RecordingRetriever(
            [retrieval_result([evidence_document()])]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(
                intent="planning",
                confidence=0.2,
                source="low_confidence",
            ),
        )

        result = workflow.invoke("địa điểm du lịch Hồ Gươm")

        self.assertEqual(result.evidence_reason, OUT_OF_SCOPE)
        self.assertEqual(retriever.calls, [])

    def test_out_of_scope_phrase_matching_uses_word_boundaries(self):
        self.assertTrue(
            AgenticRAGWorkflow._is_clear_out_of_scope(
                "hướng dẫn viết code Python"
            )
        )
        self.assertFalse(
            AgenticRAGWorkflow._is_clear_out_of_scope(
                "quán Barcode có món gì"
            )
        )

    def test_food_signal_distinguishes_chao_from_chao_dish(self):
        self.assertFalse(
            AgenticRAGWorkflow._has_food_signal("chào bạn nhé")
        )
        self.assertTrue(
            AgenticRAGWorkflow._has_food_signal("tìm cháo gà ngon")
        )
        self.assertTrue(
            AgenticRAGWorkflow._has_food_signal("tim chao suon")
        )
        self.assertTrue(
            AgenticRAGWorkflow._has_food_signal("quán nào còn mở")
        )

    def test_invalid_provided_district_is_not_used_as_filter(self):
        retriever = RecordingRetriever(
            [retrieval_result([evidence_document()])]
        )
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedRouter(),
        )

        result = workflow.invoke(
            "tìm quán phở ngon",
            district="Atlantis",
        )

        self.assertIsNone(result.district)
        self.assertIsNone(retriever.calls[0]["district_filter"])

    def test_missing_router_dataset_falls_back_without_startup_error(self):
        router = QueryRouter(
            dataset_path=Path("does-not-exist-query-router.jsonl")
        )

        prediction = router.predict("tìm quán phở ngon")

        self.assertEqual(prediction.intent, "unknown")
        self.assertEqual(prediction.confidence, 0.0)
        self.assertEqual(prediction.source, "fallback")

    def test_concurrent_workflow_invocations_do_not_leak_state(self):
        class EchoRetriever:
            def search_with_metadata(self, **kwargs):
                query = kwargs["query"]
                return retrieval_result(
                    [
                        evidence_document(
                            parent_id=f"food_{query}",
                            title=query,
                        )
                    ]
                )

        workflow = AgenticRAGWorkflow(
            EchoRetriever(),
            min_score=0.5,
            query_router=FixedRouter(),
        )
        queries = [f"quán kiểm thử {index}" for index in range(12)]

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(workflow.invoke, queries))

        self.assertEqual(
            [result.documents[0]["title"] for result in results],
            queries,
        )
        self.assertTrue(
            all(result.retry_count == 0 for result in results)
        )


if __name__ == "__main__":
    unittest.main()
