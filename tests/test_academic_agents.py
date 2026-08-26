import asyncio
import os
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch


AGENT_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="academic-agent-")
AGENT_TEST_DATABASE = Path(
    AGENT_TEST_DIRECTORY.name,
    "academic-agent.sqlite3",
).resolve()
os.environ["DATABASE_URL"] = (
    f"sqlite:///{AGENT_TEST_DATABASE.as_posix()}"
)
os.environ["APP_ENV"] = "test"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["JWT_SECRET_KEY"] = "academic-agent-test-secret"
os.environ["LLM_API_KEY"] = "academic-agent-test-llm-key"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["TRUSTED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["AUTH_COOKIE_SAMESITE"] = "lax"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["DB_SCHEMA_CHECK"] = "false"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from academic_agents.knowledge import KnowledgeAgent
from academic_agents.evaluation import evaluate_academic_agent_workflow
from academic_agents.llm import OpenAICompatibleChatModel
from academic_agents.orchestrator import AcademicAgentWorkflow
from academic_agents.routing import OrchestratorAgent
from academic_agents.runtime import (
    AcademicRetrieverRegistry,
    AcademicRuntimeConfigurationError,
)
from academic_agents.tool import AcademicRetrievalTool
from academic_agents.verification import VerificationAgent
from core.security import get_current_user
from database.connection import get_db
from routers.academic_assistant import router
from schemas.agents import (
    AcademicAgentEvaluationCase,
    AcademicAssistantRequest,
    AcademicAssistantResponse,
    AcademicKnowledgeSearchOutput,
)
from schemas.indexing import AcademicRetrievalHit, AcademicRetrievalResult
from schemas.ingestion import CitationMetadata
from services.academic_agent_service import (
    AcademicAgentLimitError,
    consume_academic_agent_budget,
)


class FakeChatModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeChatModel hết response.")
        return self.responses.pop(0)


class FakeRetriever:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return self.result


def retrieval_result(*, with_hits=True, course_id="political_philosophy"):
    hits = []
    if with_hits:
        hits = [
            AcademicRetrievalHit(
                chunk_id=f"{course_id}__1_0_0__textbook__chunk_0001",
                course_id=course_id,
                course_version="1.0.0",
                knowledge_version=f"{course_id}-aaaaaaaaaaaa",
                document_id="textbook",
                section_id="chapter_1",
                chapter_id="chuong_1",
                content="Vật chất là một phạm trù triết học.",
                citation=CitationMetadata(
                    document_id="textbook",
                    document_title="Giáo trình chính thức",
                    source_path="documents/textbook.md",
                    source_type="official_textbook",
                    source_authority="Nhà xuất bản kiểm thử",
                    publication_year=2025,
                    section_title="Chương 1",
                    start_line=1,
                    end_line=5,
                ),
                score=0.03,
                dense_score=0.9,
                keyword_score=1.2,
                retrieval_sources=["dense", "keyword"],
            )
        ]
    return AcademicRetrievalResult(
        query="Vật chất là gì?",
        course_id=course_id,
        course_version="1.0.0",
        knowledge_version=f"{course_id}-aaaaaaaaaaaa",
        collection_name=f"course_{course_id}_current",
        branch_counts={"dense": len(hits), "keyword": len(hits)},
        hits=hits,
    )


def build_workflow(responses, *, result=None, max_revisions=2):
    model = FakeChatModel(responses)
    retriever = FakeRetriever(result or retrieval_result())
    tool = AcademicRetrievalTool(lambda _course_id, _version: retriever)
    workflow = AcademicAgentWorkflow(
        orchestrator_agent=OrchestratorAgent(model),
        knowledge_agent=KnowledgeAgent(model, tool),
        verification_agent=VerificationAgent(model),
        max_revisions=max_revisions,
    )
    return workflow, model, retriever


class AcademicAgentWorkflowTests(unittest.TestCase):
    def test_grounded_question_uses_three_agents_and_one_tool_call(self):
        workflow, model, retriever = build_workflow(
            [
                '{"route":"knowledge","reason":"Cần tra cứu giáo trình"}',
                "Vật chất là một phạm trù triết học [1].",
                '{"status":"PASS","critique":"Đủ căn cứ"}',
            ]
        )

        response = workflow.invoke(
            question="Vật chất là gì?",
            course_id="political_philosophy",
            course_version="1.0.0",
        )

        self.assertEqual(response.route, "knowledge")
        self.assertEqual(response.verification_status, "PASS")
        self.assertEqual(response.revision_count, 0)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(
            [event.agent for event in response.agent_trace],
            ["OrchestratorAgent", "KnowledgeAgent", "VerificationAgent"],
        )

    def test_direct_route_skips_knowledge_and_verification(self):
        workflow, model, retriever = build_workflow(
            ['{"route":"direct","reason":"Lời chào"}']
        )
        response = workflow.invoke(
            question="Xin chào",
            course_id="political_philosophy",
            course_version="1.0.0",
        )

        self.assertEqual(response.route, "direct")
        self.assertEqual(response.verification_status, "NOT_REQUIRED")
        self.assertEqual(response.citations, [])
        self.assertEqual(retriever.calls, [])
        self.assertEqual(len(model.calls), 1)

    def test_unsupported_route_is_blocked_without_retrieval(self):
        workflow, _model, retriever = build_workflow(
            ['{"route":"unsupported","reason":"Ngoài phạm vi"}']
        )
        response = workflow.invoke(
            question="Tư vấn mua cổ phiếu",
            course_id="political_philosophy",
            course_version="1.0.0",
        )
        self.assertEqual(response.route, "unsupported")
        self.assertEqual(response.verification_status, "BLOCK")
        self.assertEqual(retriever.calls, [])

    def test_missing_citation_is_revised_without_repeating_tool(self):
        workflow, model, retriever = build_workflow(
            [
                '{"route":"knowledge","reason":"Câu hỏi kiến thức"}',
                "Vật chất là một phạm trù triết học.",
                "Vật chất là một phạm trù triết học [1].",
                '{"status":"PASS","critique":"Đã bổ sung citation"}',
            ]
        )
        response = workflow.invoke(
            question="Vật chất là gì?",
            course_id="political_philosophy",
            course_version="1.0.0",
        )

        self.assertEqual(response.verification_status, "PASS")
        self.assertEqual(response.revision_count, 1)
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(len(model.calls), 4)
        verification_events = [
            event
            for event in response.agent_trace
            if event.agent == "VerificationAgent"
        ]
        self.assertEqual(
            [event.status for event in verification_events],
            ["REVISE", "PASS"],
        )

    def test_revision_loop_blocks_after_two_attempts(self):
        workflow, model, retriever = build_workflow(
            [
                '{"route":"knowledge","reason":"Câu hỏi kiến thức"}',
                "Câu trả lời chưa có nguồn.",
                "Vẫn chưa có nguồn.",
                "Tiếp tục chưa có nguồn.",
            ]
        )
        response = workflow.invoke(
            question="Vật chất là gì?",
            course_id="political_philosophy",
            course_version="1.0.0",
        )

        self.assertEqual(response.verification_status, "BLOCK")
        self.assertEqual(response.revision_count, 2)
        self.assertEqual(response.citations, [])
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(len(model.calls), 4)
        self.assertLessEqual(len(response.agent_trace), 7)

    def test_empty_retrieval_is_blocked_without_generation(self):
        workflow, model, retriever = build_workflow(
            ['{"route":"knowledge","reason":"Cần tra cứu"}'],
            result=retrieval_result(with_hits=False),
        )
        response = workflow.invoke(
            question="Khái niệm không có trong tài liệu?",
            course_id="political_philosophy",
            course_version="1.0.0",
        )
        self.assertEqual(response.verification_status, "BLOCK")
        self.assertEqual(response.citations, [])
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(len(model.calls), 1)

    def test_semantic_verifier_can_request_revision(self):
        workflow, _model, retriever = build_workflow(
            [
                '{"route":"knowledge","reason":"Cần tra cứu"}',
                "Nội dung chưa chính xác [1].",
                '{"status":"REVISE","critique":"Diễn giải chưa khớp evidence"}',
                "Vật chất là một phạm trù triết học [1].",
                '{"status":"PASS","critique":"Đã khớp evidence"}',
            ]
        )
        response = workflow.invoke(
            question="Vật chất là gì?",
            course_id="political_philosophy",
            course_version="1.0.0",
        )
        self.assertEqual(response.verification_status, "PASS")
        self.assertEqual(response.revision_count, 1)
        self.assertEqual(len(retriever.calls), 1)

    def test_invalid_verifier_output_fails_closed(self):
        workflow, _model, _retriever = build_workflow(
            [
                '{"route":"knowledge","reason":"Cần tra cứu"}',
                "Vật chất là một phạm trù triết học [1].",
                "not-json",
            ]
        )
        response = workflow.invoke(
            question="Vật chất là gì?",
            course_id="political_philosophy",
            course_version="1.0.0",
        )
        self.assertEqual(response.verification_status, "BLOCK")
        self.assertEqual(response.citations, [])

    def test_agent_evaluation_measures_routing_tools_and_constraints(self):
        workflow, _model, _retriever = build_workflow(
            [
                '{"route":"knowledge","reason":"Cần tra cứu"}',
                "Vật chất là một phạm trù triết học [1].",
                '{"status":"PASS","critique":"Đủ căn cứ"}',
                '{"route":"direct","reason":"Lời chào"}',
            ]
        )
        cases = [
            AcademicAgentEvaluationCase(
                case_id="knowledge_001",
                question="Vật chất là gì?",
                course_id="political_philosophy",
                course_version="1.0.0",
                expected_route="knowledge",
                expected_verification_status="PASS",
            ),
            AcademicAgentEvaluationCase(
                case_id="direct_001",
                question="Xin chào",
                course_id="political_philosophy",
                course_version="1.0.0",
                expected_route="direct",
                expected_verification_status="NOT_REQUIRED",
            ),
        ]
        report = evaluate_academic_agent_workflow(workflow, cases)
        self.assertEqual(report.routing_accuracy, 1.0)
        self.assertEqual(report.tool_selection_accuracy, 1.0)
        self.assertEqual(report.verification_outcome_accuracy, 1.0)
        self.assertEqual(report.constraint_satisfaction_rate, 1.0)
        self.assertEqual(report.loop_violation_count, 0)


class AcademicToolAndModelTests(unittest.TestCase):
    def test_tool_rejects_retrieval_result_from_another_course(self):
        retriever = FakeRetriever(retrieval_result(course_id="hochiminh_thought"))
        tool = AcademicRetrievalTool(lambda _course_id, _version: retriever)
        from schemas.agents import AcademicKnowledgeSearchInput

        with self.assertRaises(RuntimeError):
            tool.run(
                AcademicKnowledgeSearchInput(
                    query="Vật chất là gì?",
                    course_id="political_philosophy",
                    course_version="1.0.0",
                )
            )

    def test_openai_compatible_chat_adapter_uses_provider_model(self):
        calls = []

        class Completions:
            def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="  Kết quả  ")
                        )
                    ]
                )

        provider = SimpleNamespace(
            model="kimi-test",
            sync_client=SimpleNamespace(
                chat=SimpleNamespace(completions=Completions())
            ),
        )
        model = OpenAICompatibleChatModel(
            provider,
            max_output_tokens=500,
            reasoning_effort="low",
        )
        result = model.complete(
            system_prompt="system",
            user_prompt="user",
        )
        self.assertEqual(result, "Kết quả")
        self.assertEqual(calls[0]["model"], "kimi-test")
        self.assertEqual(calls[0]["reasoning_effort"], "low")

    def test_retriever_registry_loads_and_caches_multiple_courses_generically(self):
        with tempfile.TemporaryDirectory(prefix="agent-registry-") as directory:
            data_root = Path(directory)
            for course_id in ("political_philosophy", "hochiminh_thought"):
                (data_root / course_id / "1.0.0" / "processed").mkdir(
                    parents=True
                )
                (data_root / course_id / "1.0.0" / "indexed").mkdir()

            registry = AcademicRetrieverRegistry(
                data_root=data_root,
                qdrant_url="http://qdrant:6333",
                qdrant_api_key=None,
                timeout_seconds=1,
                local_files_only=True,
            )
            fake_retrievers = [Mock(), Mock()]
            with patch(
                "academic_agents.runtime.AcademicHybridRetriever.from_artifacts",
                side_effect=fake_retrievers,
            ) as factory:
                first = registry.get("political_philosophy", "1.0.0")
                cached = registry.get("political_philosophy", "1.0.0")
                second = registry.get("hochiminh_thought", "1.0.0")

            self.assertIs(first, cached)
            self.assertIs(second, fake_retrievers[1])
            self.assertEqual(factory.call_count, 2)
            self.assertNotEqual(
                factory.call_args_list[0].kwargs["collection_name"],
                factory.call_args_list[1].kwargs["collection_name"],
            )
            registry.close()
            first.close.assert_called_once_with()
            second.close.assert_called_once_with()

    def test_retriever_registry_rejects_unsafe_course_identity(self):
        with tempfile.TemporaryDirectory(prefix="agent-registry-") as directory:
            registry = AcademicRetrieverRegistry(
                data_root=directory,
                qdrant_url="http://qdrant:6333",
                qdrant_api_key=None,
                timeout_seconds=1,
                local_files_only=True,
            )
            with self.assertRaises(AcademicRuntimeConfigurationError):
                registry.get("../other_course", "1.0.0")


class AcademicAssistantApiTests(unittest.TestCase):
    def test_academic_budget_commits_allowed_and_rejected_requests(self):
        db = SimpleNamespace(commit=Mock(), rollback=Mock())
        allowed = SimpleNamespace(allowed=True, retry_after_seconds=10)
        with patch(
            "services.academic_agent_service.consume_rate_limit",
            side_effect=[allowed, allowed, allowed],
        ) as consume:
            consume_academic_agent_budget(db, user_id=7)
        self.assertEqual(consume.call_count, 3)
        db.commit.assert_called_once_with()

        db.commit.reset_mock()
        blocked = SimpleNamespace(allowed=False, retry_after_seconds=42)
        with patch(
            "services.academic_agent_service.consume_rate_limit",
            side_effect=[blocked, allowed, allowed],
        ) as consume:
            with self.assertRaises(AcademicAgentLimitError) as raised:
                consume_academic_agent_budget(db, user_id=7)
        self.assertEqual(raised.exception.retry_after_seconds, 42)
        self.assertEqual(consume.call_count, 1)
        db.commit.assert_called_once_with()

    def test_api_uses_injected_runtime_and_requires_auth_dependency(self):
        response_payload = AcademicAssistantResponse(
            course_id="political_philosophy",
            course_version="1.0.0",
            route="direct",
            answer="Xin chào",
            citations=[],
            verification_status="NOT_REQUIRED",
            revision_count=0,
            agent_trace=[],
        )

        class Runtime:
            def __init__(self):
                self.requests = []

            def ask(self, request: AcademicAssistantRequest):
                self.requests.append(request)
                return response_payload

        runtime = Runtime()
        app = FastAPI()
        app.state.academic_agent_runtime = runtime
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
        fake_db = SimpleNamespace(close=Mock())
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        with patch(
            "routers.academic_assistant.consume_academic_agent_budget"
        ) as consume_budget:
            response = client.post(
                "/api/academic-assistant/ask",
                json={
                    "question": "Xin chào",
                    "course_id": "political_philosophy",
                    "course_version": "1.0.0",
                },
            )
            invalid = client.post(
                "/api/academic-assistant/ask",
                json={
                    "question": "Xin chào",
                    "course_id": "../other_course",
                    "course_version": "1.0.0",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["route"], "direct")
        self.assertEqual(len(runtime.requests), 1)
        consume_budget.assert_called_once_with(fake_db, user_id=1)
        fake_db.close.assert_called_once_with()
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(len(runtime.requests), 1)

    def test_enabled_runtime_is_started_and_closed_with_application(self):
        from main import lifespan

        fake_app = SimpleNamespace(state=SimpleNamespace())
        fake_rag = SimpleNamespace(
            warmup=Mock(),
            aclose=AsyncMock(),
        )
        fake_runtime = SimpleNamespace(aclose=AsyncMock())

        async def exercise():
            with (
                patch("main.verify_database_revision"),
                patch("main.cleanup_expired_rate_limits_task", return_value=0),
                patch("main.RAGPipeline", return_value=fake_rag),
                patch(
                    "main.AcademicAgentRuntime.from_settings",
                    return_value=fake_runtime,
                ) as runtime_factory,
                patch("main.settings.ACADEMIC_AGENT_ENABLED", True),
                patch("main.engine.dispose") as dispose_engine,
            ):
                async with lifespan(fake_app):
                    self.assertIs(
                        fake_app.state.academic_agent_runtime,
                        fake_runtime,
                    )

                runtime_factory.assert_called_once_with(
                    __import__("main").settings
                )
                fake_runtime.aclose.assert_awaited_once_with()
                fake_rag.aclose.assert_awaited_once_with()
                dispose_engine.assert_called_once_with()
                self.assertIsNone(fake_app.state.academic_agent_runtime)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
