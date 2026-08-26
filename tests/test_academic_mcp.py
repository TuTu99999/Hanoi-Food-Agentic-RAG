import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "mcp-test-secret-at-least-32-bytes")
os.environ.setdefault("LLM_API_KEY", "mcp-test-llm-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("AUTH_COOKIE_SECURE", "false")
os.environ.setdefault("AUTH_COOKIE_SAMESITE", "lax")
os.environ.setdefault("DB_SCHEMA_CHECK", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from mcp import Client
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from academic_mcp.adapter import AcademicMcpToolAdapter, AcademicMcpToolError
from academic_mcp.config import (
    AcademicMcpConfigurationError,
    AcademicMcpSettings,
)
from academic_mcp.evaluation import evaluate_mcp_contract
from academic_mcp.server import create_academic_mcp_server
from database.base import Base
from database.models import (
    AssessmentAttemptModel,
    LearnerConceptMasteryModel,
    LearningEventModel,
    LearningPlanModel,
    RateLimitBucketModel,
    UserModel,
)
from schemas.assessment import CourseMasteryResponse
from schemas.assessment import AssessmentStartRequest
from tests.test_assessment_bkt import question_bank
from tests.test_assessment_bkt import workflow as assessment_workflow
from tests.test_planning_agent import StaticRegistry, learning_map
from tests.test_planning_agent import workflow as planning_workflow


class AcademicMcpConfigurationTests(unittest.TestCase):
    def test_stdio_identity_must_be_bound_at_startup(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ACADEMIC_MCP_USER_ID", None)
            with self.assertRaises(AcademicMcpConfigurationError):
                AcademicMcpSettings.from_env()

        with patch.dict(
            os.environ,
            {"ACADEMIC_MCP_USER_ID": "7"},
            clear=False,
        ):
            self.assertEqual(AcademicMcpSettings.from_env().user_id, 7)


class FakeMcpAdapter:
    def __init__(self) -> None:
        self.fail_mastery = False

    def get_mastery(self, *, course_id, course_version):
        if self.fail_mastery:
            raise AcademicMcpToolError("Lỗi an toàn dành cho model.")
        return CourseMasteryResponse(
            course_id=course_id,
            course_version=course_version,
            concepts=[],
        )


class AcademicMcpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_exposes_eight_scoped_structured_tools(self):
        server = create_academic_mcp_server(adapter=FakeMcpAdapter())
        async with Client(server) as client:
            result = await client.list_tools()

        tools = {tool.name: tool for tool in result.tools}
        self.assertEqual(
            set(tools),
            {
                "ask_course_knowledge",
                "start_assessment",
                "submit_assessment",
                "get_course_mastery",
                "create_learning_plan",
                "approve_learning_plan",
                "get_current_learning_plan",
                "list_learning_events",
            },
        )
        self.assertTrue(all(tool.output_schema for tool in tools.values()))
        self.assertTrue(
            all(
                "user_id" not in tool.input_schema.get("properties", {})
                for tool in tools.values()
            )
        )
        self.assertTrue(
            tools["get_course_mastery"].annotations.read_only_hint
        )
        confirmation = tools["approve_learning_plan"].input_schema[
            "properties"
        ]["confirmation"]
        self.assertEqual(confirmation["const"], "APPROVE")

        report = await evaluate_mcp_contract(server)
        self.assertEqual(report["tool_coverage_rate"], 1.0)
        self.assertEqual(report["structured_output_rate"], 1.0)
        self.assertEqual(report["annotation_accuracy"], 1.0)
        self.assertEqual(report["identity_argument_exposure_count"], 0)
        self.assertTrue(report["human_approval_guard"])

    async def test_client_receives_structured_output_and_safe_tool_error(self):
        adapter = FakeMcpAdapter()
        server = create_academic_mcp_server(adapter=adapter)
        async with Client(server) as client:
            success = await client.call_tool(
                "get_course_mastery",
                {
                    "course_id": "political_philosophy",
                    "course_version": "1.0.0",
                },
            )
            adapter.fail_mastery = True
            failure = await client.call_tool(
                "get_course_mastery",
                {
                    "course_id": "political_philosophy",
                    "course_version": "1.0.0",
                },
            )

        self.assertFalse(success.is_error)
        self.assertEqual(
            success.structured_content["course_id"],
            "political_philosophy",
        )
        self.assertTrue(failure.is_error)
        self.assertIn("Lỗi an toàn", failure.content[0].text)


class AcademicMcpAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://")
        cls.session_factory = sessionmaker(bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)
        cls.engine.dispose()

    def setUp(self):
        self.db = self.session_factory()
        for model in (
            LearningEventModel,
            LearningPlanModel,
            AssessmentAttemptModel,
            LearnerConceptMasteryModel,
            RateLimitBucketModel,
            UserModel,
        ):
            self.db.query(model).delete()
        first = UserModel(username="mcp-user-1", hashed_password="hash")
        second = UserModel(username="mcp-user-2", hashed_password="hash")
        self.db.add_all([first, second])
        self.db.commit()
        self.first_user_id = first.id
        self.second_user_id = second.id
        bank = question_bank()
        self.runtime = SimpleNamespace(
            assessment_workflow=assessment_workflow(),
            question_bank_registry=StaticRegistry(bank),
            planning_workflow=planning_workflow(),
            learning_map_registry=StaticRegistry(learning_map()),
        )
        self.adapter = AcademicMcpToolAdapter(
            self.session_factory,
            self.runtime,
            user_id=self.first_user_id,
        )

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_adapter_reads_only_the_identity_bound_to_the_process(self):
        self.db.add_all(
            [
                LearnerConceptMasteryModel(
                    user_id=self.first_user_id,
                    course_id="political_philosophy",
                    course_version="1.0.0",
                    concept_id="matter",
                    concept_name="Vật chất",
                    mastery_probability=0.75,
                    attempt_count=2,
                    correct_count=1,
                ),
                LearnerConceptMasteryModel(
                    user_id=self.second_user_id,
                    course_id="political_philosophy",
                    course_version="1.0.0",
                    concept_id="matter",
                    concept_name="Vật chất",
                    mastery_probability=0.99,
                    attempt_count=10,
                    correct_count=10,
                ),
            ]
        )
        self.db.commit()

        mastery = self.adapter.get_mastery(
            course_id="political_philosophy",
            course_version="1.0.0",
        )
        matter = next(
            item for item in mastery.concepts if item.concept_id == "matter"
        )
        self.assertEqual(matter.mastery_probability, 0.75)

    def test_missing_bound_identity_and_unconfirmed_approval_are_blocked(self):
        missing = AcademicMcpToolAdapter(
            self.session_factory,
            self.runtime,
            user_id=999999,
        )
        with self.assertRaises(AcademicMcpToolError):
            missing.validate_identity()
        with self.assertRaises(AcademicMcpToolError):
            self.adapter.approve_learning_plan(
                "00000000-0000-0000-0000-000000000001",
                confirmation="NO",
            )

    def test_assessment_tools_reuse_services_and_bound_user_scope(self):
        started = self.adapter.start_assessment(
            AssessmentStartRequest(
                course_id="political_philosophy",
                course_version="1.0.0",
                concept_id="matter",
            )
        )
        self.assertNotIn("correct_option_id", started.model_dump_json())
        attempt = (
            self.db.query(AssessmentAttemptModel)
            .filter(AssessmentAttemptModel.attempt_id == started.attempt_id)
            .one()
        )
        self.assertEqual(attempt.user_id, self.first_user_id)

        submitted = self.adapter.submit_assessment(
            started.attempt_id,
            selected_option_id="A",
        )
        self.assertTrue(submitted.is_correct)
        self.assertEqual(submitted.automation.reason, "NO_ACTIVE_PLAN")


if __name__ == "__main__":
    unittest.main()
