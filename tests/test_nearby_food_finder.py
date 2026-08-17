import math
import os
from types import SimpleNamespace
import unittest

from pydantic import ValidationError
from qdrant_client.models import PayloadSchemaType


os.environ["APP_ENV"] = "test"
os.environ["LANGSMITH_TRACING"] = "false"


from embedding.geo import distance_km, is_within_radius, valid_coordinates
from embedding.lexical_index import LexicalIndex
from embedding.retrieval_engine import (
    RetrievalConfigurationError,
    RetrievalEngine,
)
from embedding.upload_to_qdrant import build_payload, create_payload_indexes
from rag.agentic_graph import (
    DEFAULT_NEARBY_RADIUS_KM,
    HARD_FILTER_EMPTY,
    AgenticRAGWorkflow,
)
from schemas.chat import ChatRequest


USER_LATITUDE = 21.03
USER_LONGITUDE = 105.84


def catalog_row(
    parent_id: str,
    *,
    latitude: float | None,
    longitude: float | None,
) -> dict:
    return {
        "chunk_id": f"{parent_id}_chunk_001",
        "parent_id": parent_id,
        "chunk_index": 1,
        "domain": "food",
        "knowledge_version": "food-nearby-test",
        "title": "Phở thử nghiệm",
        "address": "1 Phố Kiểm Thử, Hà Nội",
        "district": "Hoàn Kiếm",
        "category": "Ẩm thực",
        "sub_category": "Mì/Bún/Phở",
        "price_range": "30.000đ - 60.000đ",
        "opening_hours": "06:00 - 22:00",
        "tags": ["Phở"],
        "description": "Quán phở dùng cho unit test tìm kiếm theo vị trí.",
        "latitude": latitude,
        "longitude": longitude,
    }


class FixedFoodRouter:
    confidence_threshold = 0.35

    @staticmethod
    def predict(_query: str) -> SimpleNamespace:
        return SimpleNamespace(
            intent="food_search",
            confidence=0.99,
            source="ml",
        )


class RecordingRetriever:
    def __init__(self):
        self.calls = []

    def search_with_metadata(self, **kwargs) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            documents=[],
            candidate_count=0,
            accepted_count=0,
            filter_match_count=0,
            branch_counts={"exact": 0, "keyword": 0, "semantic": 0},
            branch_errors=[],
            exact_shortcut_used=False,
        )


class RecordingPayloadIndexClient:
    def __init__(self):
        self.calls = []

    def create_payload_index(self, **kwargs) -> None:
        self.calls.append(dict(kwargs))


class GeoUtilityTests(unittest.TestCase):
    def test_coordinate_validation_rejects_non_finite_and_out_of_bounds(self):
        self.assertTrue(valid_coordinates(USER_LATITUDE, USER_LONGITUDE))
        self.assertTrue(valid_coordinates(-90, 180))

        for latitude, longitude in (
            (91, USER_LONGITUDE),
            (USER_LATITUDE, -181),
            (math.nan, USER_LONGITUDE),
            (USER_LATITUDE, math.inf),
            (None, USER_LONGITUDE),
        ):
            with self.subTest(latitude=latitude, longitude=longitude):
                self.assertFalse(valid_coordinates(latitude, longitude))

    def test_distance_and_radius_use_haversine_kilometers(self):
        self.assertEqual(
            distance_km(
                USER_LATITUDE,
                USER_LONGITUDE,
                USER_LATITUDE,
                USER_LONGITUDE,
            ),
            0.0,
        )

        about_one_kilometer = distance_km(
            USER_LATITUDE,
            USER_LONGITUDE,
            USER_LATITUDE + 0.009,
            USER_LONGITUDE,
        )
        self.assertIsNotNone(about_one_kilometer)
        self.assertGreater(about_one_kilometer, 0.9)
        self.assertLess(about_one_kilometer, 1.1)
        self.assertTrue(
            is_within_radius(
                USER_LATITUDE + 0.009,
                USER_LONGITUDE,
                USER_LATITUDE,
                USER_LONGITUDE,
                1.1,
            )
        )
        self.assertFalse(
            is_within_radius(
                USER_LATITUDE + 0.009,
                USER_LONGITUDE,
                USER_LATITUDE,
                USER_LONGITUDE,
                0.5,
            )
        )

    def test_invalid_place_coordinates_have_no_distance_or_radius_match(self):
        self.assertIsNone(
            distance_km(USER_LATITUDE, USER_LONGITUDE, None, None)
        )
        self.assertFalse(
            is_within_radius(
                None,
                None,
                USER_LATITUDE,
                USER_LONGITUDE,
                3,
            )
        )


class NearbySchemaTests(unittest.TestCase):
    def test_nearby_defaults_to_three_kilometers(self):
        request = ChatRequest(
            question="Tìm phở gần tôi",
            nearby={
                "latitude": USER_LATITUDE,
                "longitude": USER_LONGITUDE,
            },
        )

        self.assertIsNotNone(request.nearby)
        self.assertEqual(request.nearby.radius_km, 3)
        self.assertEqual(request.nearby.latitude, USER_LATITUDE)
        self.assertEqual(request.nearby.longitude, USER_LONGITUDE)

    def test_nearby_accepts_documented_radius_boundaries(self):
        for radius_km in (0.2, 20):
            with self.subTest(radius_km=radius_km):
                request = ChatRequest(
                    question="Tìm quán gần tôi",
                    nearby={
                        "latitude": USER_LATITUDE,
                        "longitude": USER_LONGITUDE,
                        "radius_km": radius_km,
                    },
                )
                self.assertEqual(request.nearby.radius_km, radius_km)

    def test_nearby_rejects_partial_invalid_and_non_finite_values(self):
        invalid_nearby_values = (
            {"latitude": USER_LATITUDE},
            {"latitude": 91, "longitude": USER_LONGITUDE},
            {"latitude": USER_LATITUDE, "longitude": 181},
            {
                "latitude": USER_LATITUDE,
                "longitude": USER_LONGITUDE,
                "radius_km": 0.19,
            },
            {
                "latitude": USER_LATITUDE,
                "longitude": USER_LONGITUDE,
                "radius_km": 20.01,
            },
            {"latitude": math.nan, "longitude": USER_LONGITUDE},
            {"latitude": USER_LATITUDE, "longitude": math.inf},
        )

        for nearby in invalid_nearby_values:
            with self.subTest(nearby=nearby):
                with self.assertRaises(ValidationError):
                    ChatRequest(question="Tìm quán gần tôi", nearby=nearby)


class LexicalGeoFilterTests(unittest.TestCase):
    def setUp(self):
        self.index = LexicalIndex(
            [
                catalog_row(
                    "near",
                    latitude=USER_LATITUDE + 0.005,
                    longitude=USER_LONGITUDE,
                ),
                catalog_row(
                    "far",
                    latitude=USER_LATITUDE + 0.1,
                    longitude=USER_LONGITUDE,
                ),
                catalog_row(
                    "missing",
                    latitude=None,
                    longitude=None,
                ),
            ]
        )

    def test_geo_filter_excludes_far_and_missing_coordinates(self):
        self.assertEqual(self.index.count_matching_filters(), 3)
        self.assertEqual(
            self.index.count_matching_filters(
                user_latitude=USER_LATITUDE,
                user_longitude=USER_LONGITUDE,
                radius_km=2,
            ),
            1,
        )

    def test_exact_and_keyword_branches_apply_the_same_geo_filter(self):
        parameters = {
            "user_latitude": USER_LATITUDE,
            "user_longitude": USER_LONGITUDE,
            "radius_km": 2,
        }

        exact_results = self.index.exact_search(
            "Phở thử nghiệm",
            **parameters,
        )
        keyword_results = self.index.keyword_search("phở", **parameters)

        self.assertEqual(
            [document["parent_id"] for document in exact_results],
            ["near"],
        )
        self.assertEqual(
            [document["parent_id"] for document in keyword_results],
            ["near"],
        )


class RetrievalGeoFilterTests(unittest.TestCase):
    def test_readiness_requires_the_location_geo_index(self):
        engine = RetrievalEngine.__new__(RetrievalEngine)
        engine.collection_name = "hanoi_food_current"
        engine.lexical_index = SimpleNamespace(
            knowledge_version="food-nearby-test"
        )
        engine.client = SimpleNamespace(
            get_collection=lambda _name: SimpleNamespace(
                payload_schema={
                    "location": SimpleNamespace(
                        data_type=PayloadSchemaType.GEO
                    )
                }
            ),
            scroll=lambda **_kwargs: (
                [
                    SimpleNamespace(
                        payload={
                            "knowledge_version": "food-nearby-test"
                        }
                    )
                ],
                None,
            ),
        )

        engine.check_ready()
        engine.client.get_collection = lambda _name: SimpleNamespace(
            payload_schema={}
        )
        with self.assertRaises(RetrievalConfigurationError):
            engine.check_ready()

    def test_location_filter_requires_complete_valid_values(self):
        self.assertFalse(
            RetrievalEngine._validate_location_filter(
                user_latitude=None,
                user_longitude=None,
                radius_km=None,
            )
        )
        self.assertTrue(
            RetrievalEngine._validate_location_filter(
                user_latitude=USER_LATITUDE,
                user_longitude=USER_LONGITUDE,
                radius_km=3,
            )
        )

        invalid_filters = (
            (USER_LATITUDE, None, 3),
            (None, USER_LONGITUDE, 3),
            (USER_LATITUDE, USER_LONGITUDE, None),
            (91, USER_LONGITUDE, 3),
            (USER_LATITUDE, USER_LONGITUDE, 0.1),
        )
        for latitude, longitude, radius_km in invalid_filters:
            with self.subTest(
                latitude=latitude,
                longitude=longitude,
                radius_km=radius_km,
            ):
                with self.assertRaises(ValueError):
                    RetrievalEngine._validate_location_filter(
                        user_latitude=latitude,
                        user_longitude=longitude,
                        radius_km=radius_km,
                    )

    def test_qdrant_filter_uses_geo_radius_in_meters(self):
        search_filter = RetrievalEngine._build_filter(
            district="Hoàn Kiếm",
            domain="food",
            category=None,
            user_latitude=USER_LATITUDE,
            user_longitude=USER_LONGITUDE,
            radius_km=2.5,
        )
        conditions = {condition.key: condition for condition in search_filter.must}
        location_condition = conditions["location"].geo_radius

        self.assertEqual(location_condition.center.lat, USER_LATITUDE)
        self.assertEqual(location_condition.center.lon, USER_LONGITUDE)
        self.assertEqual(location_condition.radius, 2500)

    def test_location_ranking_adds_distance_and_drops_outside_radius(self):
        documents = [
            {
                "parent_id": "far",
                "latitude": USER_LATITUDE + 0.018,
                "longitude": USER_LONGITUDE,
                "ranking_score": 0.02,
            },
            {
                "parent_id": "near",
                "latitude": USER_LATITUDE + 0.002,
                "longitude": USER_LONGITUDE,
                "ranking_score": 0.02,
            },
            {
                "parent_id": "outside",
                "latitude": USER_LATITUDE + 0.1,
                "longitude": USER_LONGITUDE,
                "ranking_score": 0.5,
            },
            {
                "parent_id": "missing",
                "latitude": None,
                "longitude": None,
                "ranking_score": 0.5,
            },
        ]

        ranked = RetrievalEngine._rank_with_location(
            documents,
            top_k=5,
            user_latitude=USER_LATITUDE,
            user_longitude=USER_LONGITUDE,
            radius_km=3,
        )

        self.assertEqual(
            [document["parent_id"] for document in ranked],
            ["near", "far"],
        )
        self.assertLess(ranked[0]["distance_km"], ranked[1]["distance_km"])
        self.assertGreater(
            ranked[0]["proximity_score"],
            ranked[1]["proximity_score"],
        )
        self.assertNotIn("distance_km", documents[0])


class GeoPayloadTests(unittest.TestCase):
    def test_build_payload_adds_qdrant_location_without_vector(self):
        row = {
            "chunk_id": "food_001_chunk_001",
            "latitude": USER_LATITUDE,
            "longitude": USER_LONGITUDE,
            "vector": [0.1, 0.2],
        }

        payload = build_payload(row)

        self.assertNotIn("vector", payload)
        self.assertEqual(
            payload["location"],
            {"lat": USER_LATITUDE, "lon": USER_LONGITUDE},
        )
        self.assertNotIn("location", row)

    def test_build_payload_omits_location_for_invalid_coordinates(self):
        payload = build_payload(
            {
                "chunk_id": "food_001_chunk_001",
                "latitude": None,
                "longitude": USER_LONGITUDE,
                "vector": [0.1, 0.2],
            }
        )

        self.assertNotIn("location", payload)

    def test_payload_indexes_include_geo_location(self):
        client = RecordingPayloadIndexClient()

        create_payload_indexes(client, "hanoi_food_test")

        calls_by_field = {
            call["field_name"]: call
            for call in client.calls
        }
        self.assertIn("location", calls_by_field)
        self.assertEqual(
            calls_by_field["location"]["field_schema"],
            PayloadSchemaType.GEO,
        )
        self.assertTrue(calls_by_field["location"]["wait"])


class AgenticNearbyBehaviorTests(unittest.TestCase):
    def test_nearby_phrases_and_radius_units_are_understood(self):
        self.assertTrue(
            AgenticRAGWorkflow._requests_nearby("Tìm quán phở gần tôi")
        )
        self.assertTrue(
            AgenticRAGWorkflow._requests_nearby(
                "Có quán ăn nào quanh vị trí hiện tại?"
            )
        )
        self.assertTrue(
            AgenticRAGWorkflow._requests_nearby("Quán bún gần chỗ mình")
        )
        self.assertTrue(
            AgenticRAGWorkflow._requests_nearby("Find pho near me")
        )
        self.assertFalse(
            AgenticRAGWorkflow._requests_nearby("Tìm quán ở Cầu Giấy")
        )
        self.assertEqual(
            AgenticRAGWorkflow._extract_radius_km("trong bán kính 2,5 km"),
            2.5,
        )
        self.assertEqual(
            AgenticRAGWorkflow._extract_radius_km("quanh đây 800m"),
            0.8,
        )
        self.assertIsNone(
            AgenticRAGWorkflow._extract_radius_km("trong bán kính 50 km")
        )

    def test_nearby_filter_validation_supports_default_radius(self):
        self.assertTrue(
            AgenticRAGWorkflow._validate_nearby_filter(
                user_latitude=USER_LATITUDE,
                user_longitude=USER_LONGITUDE,
                radius_km=None,
            )
        )
        self.assertFalse(
            AgenticRAGWorkflow._validate_nearby_filter(
                user_latitude=None,
                user_longitude=None,
                radius_km=None,
            )
        )

        for parameters in (
            {
                "user_latitude": USER_LATITUDE,
                "user_longitude": None,
                "radius_km": 3,
            },
            {
                "user_latitude": None,
                "user_longitude": None,
                "radius_km": 3,
            },
            {
                "user_latitude": USER_LATITUDE,
                "user_longitude": USER_LONGITUDE,
                "radius_km": 21,
            },
        ):
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValueError):
                    AgenticRAGWorkflow._validate_nearby_filter(**parameters)

    def test_radius_only_query_requests_location_instead_of_retrieving(self):
        retriever = RecordingRetriever()
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedFoodRouter(),
        )

        result = workflow.invoke("Tìm phở trong bán kính 2 km")

        self.assertFalse(result.should_generate)
        self.assertEqual(result.evidence_reason, HARD_FILTER_EMPTY)
        self.assertIn("gần tôi", result.direct_answer.casefold())
        self.assertEqual(retriever.calls, [])

    def test_coordinates_use_default_radius_and_reach_retrieval(self):
        retriever = RecordingRetriever()
        workflow = AgenticRAGWorkflow(
            retriever,
            min_score=0.5,
            query_router=FixedFoodRouter(),
        )

        result = workflow.invoke(
            "Tìm phở gần tôi",
            user_latitude=USER_LATITUDE,
            user_longitude=USER_LONGITUDE,
        )

        self.assertTrue(result.nearby_filter_applied)
        self.assertEqual(result.radius_km, DEFAULT_NEARBY_RADIUS_KM)
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(
            retriever.calls[0]["radius_km"],
            DEFAULT_NEARBY_RADIUS_KM,
        )
        self.assertEqual(
            retriever.calls[0]["user_latitude"],
            USER_LATITUDE,
        )
        self.assertEqual(
            retriever.calls[0]["user_longitude"],
            USER_LONGITUDE,
        )


class RAGNearbyContextTests(unittest.TestCase):
    def test_rag_passes_location_without_putting_user_coordinates_in_prompt(self):
        from rag.Rag import RAGPipeline

        workflow = RecordingAgenticWorkflow()
        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline._get_agentic_workflow = lambda: workflow

        direct_answer, messages, context = pipeline._prepare_messages(
            user_question="Tìm phở gần tôi",
            user_latitude=USER_LATITUDE,
            user_longitude=USER_LONGITUDE,
            radius_km=3,
        )

        self.assertIsNone(direct_answer)
        self.assertEqual(workflow.calls[0]["user_latitude"], USER_LATITUDE)
        self.assertEqual(workflow.calls[0]["user_longitude"], USER_LONGITUDE)
        self.assertEqual(workflow.calls[0]["radius_km"], 3)
        self.assertEqual(context[0]["distance_km"], 1.25)
        prompt = messages[-1]["content"]
        self.assertIn('"distance_km": 1.25', prompt)
        self.assertNotIn(str(USER_LATITUDE), prompt)
        self.assertNotIn(str(USER_LONGITUDE), prompt)


class RecordingAgenticWorkflow:
    def __init__(self):
        self.calls = []

    def invoke(self, **kwargs) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            documents=[
                {
                    "domain": "food",
                    "title": "Phở gần đây",
                    "address": "1 Phố Kiểm Thử, Hà Nội",
                    "district": "Hoàn Kiếm",
                    "category": "Ẩm thực",
                    "latitude": 21.041,
                    "longitude": 105.861,
                    "distance_km": 1.25,
                    "content": "Quán phở dùng cho kiểm thử.",
                }
            ],
            district=None,
            intent="food_search",
            intent_source="ml",
            intent_confidence=0.99,
            evidence_reason="sufficient",
            retry_count=0,
            branch_counts={"keyword": 1},
            exact_shortcut_used=False,
            nearby_filter_applied=True,
            radius_km=3,
            should_generate=True,
            direct_answer=None,
        )


if __name__ == "__main__":
    unittest.main()
