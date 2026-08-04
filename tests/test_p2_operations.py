import asyncio
import json
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch


os.environ["APP_ENV"] = "test"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "p2-test-secret"
os.environ["LLM_API_KEY"] = "p2-test-llm-api-key"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["AUTH_COOKIE_SAMESITE"] = "lax"
os.environ["DB_SCHEMA_CHECK"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.observability import JsonFormatter
from core.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    call_with_retry,
    call_with_retry_async,
)
from embedding.evaluate_retrieval import evaluate_threshold
from main import app, lifespan


class FakeHealthyRAG:
    def check_retrieval_ready(self):
        return None

    def llm_health_status(self):
        return "configured"


class TransientServiceError(RuntimeError):
    status_code = 503


class P2OperationsTests(unittest.TestCase):
    def setUp(self):
        app.state.rag_pipeline = FakeHealthyRAG()

    def test_request_id_is_generated_validated_and_returned(self):
        client = TestClient(app)

        generated = client.get("/health/live")
        generated_id = generated.headers["X-Request-ID"]
        uuid.UUID(generated_id)
        self.assertEqual(generated.status_code, 200)
        self.assertIn("X-Process-Time", generated.headers)

        loopback_health = TestClient(
            app,
            base_url="http://127.0.0.1",
        ).get("/health/live")
        self.assertEqual(loopback_health.status_code, 200)

        supplied = client.get(
            "/health/live",
            headers={"X-Request-ID": "client-request_123"},
        )
        self.assertEqual(
            supplied.headers["X-Request-ID"],
            "client-request_123",
        )

        invalid = client.get(
            "/health/live",
            headers={"X-Request-ID": "invalid request id"},
        )
        self.assertNotEqual(
            invalid.headers["X-Request-ID"],
            "invalid request id",
        )
        uuid.UUID(invalid.headers["X-Request-ID"])

    def test_metrics_endpoint_is_internal_monitoring_ready(self):
        client = TestClient(app)
        client.get("/metrics")
        response = client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "hanoi_food_http_requests_total",
            response.text,
        )
        self.assertIn("hanoi_food_chat_streams_total", response.text)
        self.assertNotIn('route="/metrics"', response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_monitoring_configs_and_dashboard_are_provisioned(self):
        project_root = Path(__file__).resolve().parents[1]
        prometheus_config = (
            project_root
            / "deploy"
            / "prometheus"
            / "prometheus.yml"
        ).read_text(encoding="utf-8")
        host_prometheus_config = (
            project_root
            / "deploy"
            / "prometheus"
            / "prometheus.host.yml"
        ).read_text(encoding="utf-8")
        datasource_config = (
            project_root
            / "deploy"
            / "grafana"
            / "provisioning"
            / "datasources"
            / "prometheus.yml"
        ).read_text(encoding="utf-8")
        dashboard_path = (
            project_root
            / "deploy"
            / "grafana"
            / "dashboards"
            / "hanoi-food-overview.json"
        )
        dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))

        self.assertIn("backend:8000", prometheus_config)
        self.assertIn(
            "host.docker.internal:8000",
            host_prometheus_config,
        )
        self.assertIn("metrics_path: /metrics", prometheus_config)
        self.assertIn("url: http://prometheus:9090", datasource_config)
        self.assertEqual(dashboard["uid"], "hanoi-food-ops")
        panel_titles = {
            panel["title"]
            for panel in dashboard["panels"]
        }
        self.assertIn("Backend", panel_titles)
        self.assertIn("API Latency p95", panel_titles)
        self.assertIn("Chat Stream Outcomes", panel_titles)

        queries = " ".join(
            target["expr"]
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        )
        self.assertIn("hanoi_food_http_requests_total", queries)
        self.assertIn("hanoi_food_chat_streams_total", queries)

        dashboard_text = dashboard_path.read_text(encoding="utf-8")
        self.assertNotIn("user_id", dashboard_text)
        self.assertNotIn("session_id", dashboard_text)

    def test_health_ready_reports_each_dependency_without_leaking_errors(self):
        client = TestClient(app)

        with patch("routers.health.check_postgresql"):
            healthy = client.get("/health/ready")
        self.assertEqual(healthy.status_code, 200)
        self.assertEqual(
            healthy.json(),
            {
                "status": "ready",
                "services": {
                    "postgresql": "ok",
                    "qdrant": "ok",
                    "llm": "configured",
                },
            },
        )

        with (
            patch("routers.health.check_postgresql"),
            patch(
                "routers.health.check_qdrant",
                side_effect=RuntimeError("TOP_SECRET_QDRANT_ERROR"),
            ),
        ):
            unavailable = client.get("/health/ready")

        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(
            unavailable.json()["services"]["qdrant"],
            "unavailable",
        )
        self.assertNotIn("TOP_SECRET_QDRANT_ERROR", unavailable.text)

    def test_health_ready_rejects_missing_rag(self):
        app.state.rag_pipeline = None
        with patch("routers.health.check_postgresql"):
            response = TestClient(app).get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["services"],
            {
                "postgresql": "ok",
                "qdrant": "unavailable",
                "llm": "unavailable",
            },
        )

    def test_lifespan_warms_and_closes_dependencies(self):
        fake_app = FastAPI()
        fake_rag = Mock()
        fake_rag.aclose = AsyncMock()

        async def exercise_lifespan():
            with (
                patch("main.verify_database_revision") as verify_database,
                patch("main.cleanup_expired_rate_limits_task") as cleanup_limits,
                patch("main.RAGPipeline", return_value=fake_rag),
                patch("main.engine.dispose") as dispose_engine,
            ):
                async with lifespan(fake_app):
                    self.assertIs(
                        fake_app.state.rag_pipeline,
                        fake_rag,
                    )

                verify_database.assert_called_once_with()
                cleanup_limits.assert_called_once_with()
                fake_rag.warmup.assert_called_once_with()
                fake_rag.aclose.assert_awaited_once_with()
                dispose_engine.assert_called_once_with()
                self.assertIsNone(fake_app.state.rag_pipeline)

        asyncio.run(exercise_lifespan())

    def test_rag_close_releases_all_clients(self):
        from rag.Rag import RAGPipeline

        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline.retriever = Mock()
        pipeline.ai_client = Mock()
        pipeline.async_ai_client = Mock()
        pipeline.async_ai_client.close = AsyncMock()

        asyncio.run(pipeline.aclose())

        pipeline.retriever.close.assert_called_once_with()
        pipeline.ai_client.close.assert_called_once_with()
        pipeline.async_ai_client.close.assert_awaited_once_with()

    def test_retry_and_circuit_breaker(self):
        attempts = []
        breaker = CircuitBreaker(2, 30)

        def eventually_succeeds():
            attempts.append(1)
            if len(attempts) < 3:
                raise TransientServiceError("temporary")
            return "ok"

        with patch("core.resilience.time.sleep"):
            result = call_with_retry(
                eventually_succeeds,
                attempts=3,
                base_seconds=0.1,
                max_seconds=1,
                circuit_breaker=breaker,
            )

        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(breaker.state, "closed")

        failing_breaker = CircuitBreaker(1, 30)
        with self.assertRaises(TransientServiceError):
            call_with_retry(
                lambda: (_ for _ in ()).throw(
                    TransientServiceError("down")
                ),
                attempts=1,
                base_seconds=0,
                max_seconds=0,
                circuit_breaker=failing_breaker,
            )
        self.assertEqual(failing_breaker.state, "open")
        with self.assertRaises(CircuitOpenError):
            call_with_retry(
                lambda: "must-not-run",
                attempts=1,
                base_seconds=0,
                max_seconds=0,
                circuit_breaker=failing_breaker,
            )

    def test_async_retry(self):
        call_count = 0
        breaker = CircuitBreaker(3, 30)

        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TransientServiceError("temporary")
            return "ok"

        async def exercise():
            with patch("core.resilience.asyncio.sleep", new=AsyncMock()):
                return await call_with_retry_async(
                    operation,
                    attempts=2,
                    base_seconds=0.1,
                    max_seconds=1,
                    circuit_breaker=breaker,
                )

        self.assertEqual(asyncio.run(exercise()), "ok")
        self.assertEqual(call_count, 2)

    def test_unhandled_error_is_generic_and_has_request_id(self):
        route_path = "/_test/p2-unhandled"
        if not any(
            getattr(route, "path", None) == route_path
            for route in app.routes
        ):
            def fail_route():
                raise RuntimeError("TOP_SECRET_APPLICATION_ERROR")

            app.add_api_route(route_path, fail_route, methods=["GET"])

        response = TestClient(
            app,
            raise_server_exceptions=False,
        ).get(route_path)

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("TOP_SECRET_APPLICATION_ERROR", response.text)
        self.assertEqual(
            response.json()["request_id"],
            response.headers["X-Request-ID"],
        )

    def test_json_formatter_emits_parseable_structure(self):
        formatter = JsonFormatter()
        record = __import__("logging").LogRecord(
            name="test",
            level=20,
            pathname=__file__,
            lineno=1,
            msg="event.name",
            args=(),
            exc_info=None,
        )
        payload = json.loads(formatter.format(record))

        self.assertEqual(payload["event"], "event.name")
        self.assertEqual(payload["level"], "INFO")
        self.assertIn("request_id", payload)
        self.assertIn("session_id", payload)

    def test_retrieval_evaluation_reports_quality_and_latency(self):
        class FakeRetriever:
            def __init__(self):
                self.last_call = None

            def search(self, **kwargs):
                self.last_call = kwargs
                return [
                    {
                        "parent_id": "food_001",
                        "district": "Hoàn Kiếm",
                        "price_min": 30000,
                        "price_max": 60000,
                        "opening_intervals": [
                            {
                                "opens": "06:00",
                                "closes": "22:00",
                                "closes_next_day": False,
                            }
                        ],
                    },
                    {
                        "parent_id": "food_002",
                        "district": "Hoàn Kiếm",
                        "price_min": 40000,
                        "price_max": 50000,
                        "opening_intervals": [
                            {
                                "opens": "08:00",
                                "closes": "23:00",
                                "closes_next_day": False,
                            }
                        ],
                    },
                ]

        retriever = FakeRetriever()
        report = evaluate_threshold(
            retriever,
            [
                {
                    "query": "test",
                    "district": "hoan kiem",
                    "price_max": 50000,
                    "open_at": "12:00",
                    "min_unique_parent_ids": 2,
                    "expected_parent_ids": ["food_001", "food_002"],
                }
            ],
            threshold=0.5,
            top_k=2,
        )

        self.assertEqual(report["accuracy"], 1.0)
        self.assertEqual(report["recall_at_2"], 1.0)
        self.assertEqual(report["district_filter_accuracy"], 1.0)
        self.assertEqual(report["constraint_filter_accuracy"], 1.0)
        self.assertEqual(
            report["recommendation_diversity_accuracy"],
            1.0,
        )
        self.assertEqual(
            report["group_accuracy"]["unclassified"]["accuracy"],
            1.0,
        )
        self.assertEqual(
            report["diversity"]["unique_returned_parent_ids"],
            2,
        )
        self.assertEqual(
            report["diversity"]["unique_top_result_parent_ids"],
            1,
        )
        self.assertGreaterEqual(report["latency_ms"]["p95"], 0)
        self.assertEqual(report["estimated_cost_usd"], 0.0)
        self.assertEqual(
            retriever.last_call["price_max_filter"],
            50000,
        )
        self.assertEqual(
            retriever.last_call["open_at_filter"],
            "12:00",
        )


if __name__ == "__main__":
    unittest.main()
