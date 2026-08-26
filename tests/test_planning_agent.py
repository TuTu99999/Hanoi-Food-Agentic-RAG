import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "planning-test-secret-at-least-32-bytes")
os.environ.setdefault("LLM_API_KEY", "planning-test-llm-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("AUTH_COOKIE_SECURE", "false")
os.environ.setdefault("AUTH_COOKIE_SAMESITE", "lax")
os.environ.setdefault("DB_SCHEMA_CHECK", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from academic_agents.planning import PlanningAgent
from academic_agents.planning_workflow import AcademicPlanningWorkflow
from academic_agents.verification import VerificationAgent
from assessment.question_bank import QuestionBankError
from core.security import get_current_user
from database.base import Base
from database.connection import get_db
from database.models import LearningPlanModel, UserModel
from ingestion.service import ingest_course_package
from planning.learning_map import (
    LearningMapError,
    LearningMapRegistry,
    load_learning_map,
)
from planning.evaluation import evaluate_planning_workflow
from routers.academic_assistant import get_academic_agent_runtime
from routers.planning import router
from schemas.assessment import BKTParameters
from schemas.ingestion import CitationMetadata
from schemas.planning import (
    LearningConcept,
    LearningMap,
    LearningPlanCreateRequest,
    PlanningEvaluationCase,
)
from services.academic_agent_service import (
    AcademicAgentLimitError,
    consume_academic_planning_limit,
)
from services.planning_service import (
    AcademicPlanningService,
    PlanningConflictError,
    PlanningConstraintError,
)


def citation(start_line: int = 1) -> CitationMetadata:
    return CitationMetadata(
        document_id="official_textbook",
        document_title="Giáo trình chính thức",
        source_path="documents/textbook.md",
        source_type="official_textbook",
        source_authority="Nhà xuất bản kiểm thử",
        publication_year=2025,
        section_title="Chương 1",
        start_line=start_line,
        end_line=start_line + 5,
    )


def learning_map(course_id: str = "political_philosophy") -> LearningMap:
    return LearningMap(
        course_id=course_id,
        course_version="1.0.0",
        concepts=[
            LearningConcept(
                concept_id="foundation",
                concept_name="Nền tảng",
                order=1,
                estimated_minutes=60,
                prerequisite_ids=[],
                learning_objective="Trình bày được kiến thức nền tảng.",
                citation=citation(1),
            ),
            LearningConcept(
                concept_id="matter",
                concept_name="Vật chất",
                order=2,
                estimated_minutes=90,
                prerequisite_ids=["foundation"],
                learning_objective="Giải thích được phạm trù vật chất.",
                citation=citation(10),
            ),
            LearningConcept(
                concept_id="consciousness",
                concept_name="Ý thức",
                order=3,
                estimated_minutes=60,
                prerequisite_ids=["matter"],
                learning_objective="Phân tích được nguồn gốc của ý thức.",
                citation=citation(20),
            ),
        ],
    )


def workflow() -> AcademicPlanningWorkflow:
    return AcademicPlanningWorkflow(
        planning_agent=PlanningAgent(),
        verification_agent=VerificationAgent(chat_model=None),
    )


class LearningMapTests(unittest.TestCase):
    def test_learning_map_rejects_missing_and_cyclic_prerequisites(self):
        payload = learning_map().model_dump(mode="json")
        payload["concepts"][0]["prerequisite_ids"] = ["missing"]
        with self.assertRaises(ValidationError):
            LearningMap.model_validate(payload)

        payload = learning_map().model_dump(mode="json")
        payload["concepts"][0]["prerequisite_ids"] = ["consciousness"]
        with self.assertRaises(ValidationError):
            LearningMap.model_validate(payload)

    def test_registry_checks_scope_path_and_caches(self):
        with tempfile.TemporaryDirectory(prefix="learning-map-") as directory:
            root = Path(directory)
            path = (
                root
                / "political_philosophy"
                / "1.0.0"
                / "planning"
                / "learning_map.json"
            )
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(learning_map().model_dump(mode="json")),
                encoding="utf-8",
            )
            registry = LearningMapRegistry(root)
            first = registry.get("political_philosophy", "1.0.0")
            second = registry.get("political_philosophy", "1.0.0")
            self.assertIs(first, second)
            with self.assertRaises(LearningMapError):
                load_learning_map(
                    path,
                    expected_course_id="hochiminh_thought",
                )
            with self.assertRaises(LearningMapError):
                registry.get("../unsafe", "1.0.0")

    def test_ingestion_normalizes_learning_map(self):
        with tempfile.TemporaryDirectory(prefix="planning-package-") as directory:
            workspace = Path(directory)
            package = workspace / "package"
            documents = package / "documents"
            planning = package / "planning"
            documents.mkdir(parents=True)
            planning.mkdir()
            (documents / "textbook.md").write_text(
                "# Chương 1\nNội dung giáo trình chính thức.",
                encoding="utf-8",
            )
            (package / "course.yaml").write_text(
                "\n".join(
                    [
                        "course_id: political_philosophy",
                        "name: Triết học Mác - Lênin",
                        "version: 1.0.0",
                    ]
                ),
                encoding="utf-8",
            )
            (planning / "learning_map.json").write_text(
                json.dumps(
                    learning_map().model_dump(mode="json"),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = ingest_course_package(
                package,
                output_root=workspace / "data",
            )
            self.assertIsNotNone(result.learning_map_path)
            self.assertTrue(result.learning_map_path.is_file())
            saved = load_learning_map(result.learning_map_path)
            self.assertEqual(len(saved.concepts), 3)


class PlanningWorkflowTests(unittest.TestCase):
    def test_plan_respects_prerequisites_capacity_and_agent_boundaries(self):
        result = workflow().create_plan(
            learning_map(),
            mastery_by_concept={
                "foundation": 0.9,
                "matter": 0.3,
                "consciousness": 0.2,
            },
            mastery_threshold=0.8,
            start_date=date(2026, 9, 1),
            target_date=date(2026, 9, 5),
            study_days=4,
            minutes_per_day=60,
        )
        self.assertEqual(result.verification_status, "PASS")
        first_sequences = {}
        for item in result.draft.items:
            first_sequences.setdefault(item.concept_id, item.sequence)
            daily = sum(
                other.duration_minutes
                for other in result.draft.items
                if other.study_date == item.study_date
            )
            self.assertLessEqual(daily, 60)
        self.assertLess(first_sequences["foundation"], first_sequences["matter"])
        self.assertLess(first_sequences["matter"], first_sequences["consciousness"])
        self.assertEqual(
            [event.agent for event in result.agent_trace],
            ["OrchestratorAgent", "PlanningAgent", "VerificationAgent"],
        )

    def test_focus_adds_prerequisite_closure(self):
        result = workflow().create_plan(
            learning_map(),
            mastery_by_concept={},
            mastery_threshold=0.8,
            start_date=date(2026, 9, 1),
            target_date=date(2026, 9, 6),
            study_days=5,
            minutes_per_day=60,
            focus_concept_ids=["consciousness"],
        )
        self.assertEqual(
            result.draft.priority_concept_ids,
            ["foundation", "matter", "consciousness"],
        )

    def test_insufficient_capacity_is_blocked(self):
        result = workflow().create_plan(
            learning_map(),
            mastery_by_concept={},
            mastery_threshold=0.8,
            start_date=date(2026, 9, 1),
            target_date=date(2026, 9, 2),
            study_days=1,
            minutes_per_day=15,
        )
        self.assertEqual(result.verification_status, "BLOCK")
        self.assertTrue(result.draft.unscheduled_concept_ids)

    def test_planning_evaluation_measures_constraints_and_selection(self):
        cases = [
            PlanningEvaluationCase(
                case_id="pass_001",
                mastery_by_concept={
                    "foundation": 0.9,
                    "matter": 0.3,
                    "consciousness": 0.2,
                },
                start_date=date(2026, 9, 1),
                target_date=date(2026, 9, 5),
                study_days=4,
                minutes_per_day=60,
                expected_status="PASS",
                expected_priority_concept_ids=[
                    "foundation",
                    "matter",
                    "consciousness",
                ],
            )
        ]
        report = evaluate_planning_workflow(
            workflow(),
            learning_map(),
            cases,
        )
        self.assertEqual(report.verification_outcome_accuracy, 1.0)
        self.assertEqual(report.priority_selection_accuracy, 1.0)
        self.assertEqual(report.daily_capacity_compliance_rate, 1.0)
        self.assertEqual(report.prerequisite_order_compliance_rate, 1.0)
        self.assertEqual(report.concept_coverage_rate, 1.0)


class StaticRegistry:
    def __init__(self, value):
        self.value = value

    def get(self, course_id, course_version):
        if (
            course_id != "political_philosophy"
            or course_version != "1.0.0"
        ):
            raise QuestionBankError("wrong scope")
        return self.value


class PlanningServiceTests(unittest.TestCase):
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
        self.db.query(LearningPlanModel).delete()
        self.db.query(UserModel).delete()
        user = UserModel(username="planner", hashed_password="hash")
        self.db.add(user)
        self.db.commit()
        self.user_id = user.id
        self.runtime = SimpleNamespace(
            planning_workflow=workflow(),
            learning_map_registry=StaticRegistry(learning_map()),
            question_bank_registry=StaticRegistry(
                SimpleNamespace(bkt=BKTParameters())
            ),
        )

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def request(self, **overrides):
        payload = {
            "course_id": "political_philosophy",
            "course_version": "1.0.0",
            "target_date": "2026-09-05",
            "study_days": 4,
            "minutes_per_day": 60,
        }
        payload.update(overrides)
        return LearningPlanCreateRequest.model_validate(payload)

    def test_create_requires_verification_then_user_approval(self):
        service = AcademicPlanningService(self.db, self.runtime)
        proposed = service.create(
            self.request(),
            user_id=self.user_id,
            today=date(2026, 9, 1),
        )
        self.assertEqual(proposed.status, "PROPOSED")
        self.assertEqual(proposed.verification_status, "PASS")
        self.assertEqual(
            [event.agent for event in proposed.agent_trace],
            ["OrchestratorAgent", "PlanningAgent", "VerificationAgent"],
        )

        approved = service.approve(proposed.plan_id, user_id=self.user_id)
        self.assertEqual(approved.status, "ACTIVE")
        current = service.get_current(
            user_id=self.user_id,
            course_id="political_philosophy",
            course_version="1.0.0",
        )
        self.assertEqual(current.plan_id, proposed.plan_id)
        with self.assertRaises(PlanningConflictError):
            service.approve(proposed.plan_id, user_id=self.user_id)

    def test_new_approved_plan_replaces_previous_active_plan(self):
        service = AcademicPlanningService(self.db, self.runtime)
        first = service.create(
            self.request(title="Kế hoạch 1"),
            user_id=self.user_id,
            today=date(2026, 9, 1),
        )
        service.approve(first.plan_id, user_id=self.user_id)
        second = service.create(
            self.request(title="Kế hoạch 2"),
            user_id=self.user_id,
            today=date(2026, 9, 1),
        )
        service.approve(second.plan_id, user_id=self.user_id)
        statuses = {
            plan.plan_id: plan.status
            for plan in self.db.query(LearningPlanModel).all()
        }
        self.assertEqual(statuses[first.plan_id], "REPLACED")
        self.assertEqual(statuses[second.plan_id], "ACTIVE")
        self.assertEqual(second.revision, 2)

    def test_invalid_time_or_insufficient_capacity_is_not_persisted(self):
        service = AcademicPlanningService(self.db, self.runtime)
        with self.assertRaises(PlanningConstraintError):
            service.create(
                self.request(target_date="2026-09-01"),
                user_id=self.user_id,
                today=date(2026, 9, 1),
            )
        with self.assertRaises(PlanningConstraintError):
            service.create(
                self.request(
                    target_date="2026-09-02",
                    study_days=1,
                    minutes_per_day=15,
                ),
                user_id=self.user_id,
                today=date(2026, 9, 1),
            )
        self.assertEqual(self.db.query(LearningPlanModel).count(), 0)


class PlanningApiTests(unittest.TestCase):
    def test_planning_limit_uses_separate_non_llm_scope(self):
        db = SimpleNamespace(rollback=lambda: None)
        allowed = SimpleNamespace(allowed=True, retry_after_seconds=10)
        with patch(
            "services.academic_agent_service.consume_rate_limit",
            return_value=allowed,
        ) as consume:
            consume_academic_planning_limit(db, user_id=7)
        self.assertEqual(consume.call_args.kwargs["scope"], "academic_planning.user")

        blocked = SimpleNamespace(allowed=False, retry_after_seconds=42)
        with patch(
            "services.academic_agent_service.consume_rate_limit",
            return_value=blocked,
        ):
            with self.assertRaises(AcademicAgentLimitError):
                consume_academic_planning_limit(db, user_id=7)

    def test_create_endpoint_uses_auth_runtime_and_rate_limit(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        fake_runtime = SimpleNamespace()
        fake_db = SimpleNamespace()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: fake_db
        app.dependency_overrides[get_academic_agent_runtime] = lambda: fake_runtime
        fake_response = {
            "plan_id": "00000000-0000-0000-0000-000000000001",
            "course_id": "political_philosophy",
            "course_version": "1.0.0",
            "title": "Kế hoạch",
            "status": "PROPOSED",
            "revision": 1,
            "draft": workflow().create_plan(
                learning_map(),
                mastery_by_concept={},
                mastery_threshold=0.8,
                start_date=date(2026, 9, 1),
                target_date=date(2026, 9, 5),
                study_days=4,
                minutes_per_day=60,
            ).draft.model_dump(mode="json"),
            "verification_status": "PASS",
            "verification_critique": "Hợp lệ",
            "agent_trace": [],
            "created_at": "2026-08-26T00:00:00",
            "approved_at": None,
        }
        service = SimpleNamespace(create=lambda payload, user_id: fake_response)
        with (
            patch("routers.planning._consume_limit") as consume,
            patch(
                "routers.planning.AcademicPlanningService",
                return_value=service,
            ),
        ):
            response = TestClient(app).post(
                "/api/academic-assistant/plans",
                json={
                    "course_id": "political_philosophy",
                    "course_version": "1.0.0",
                    "target_date": "2026-09-05",
                    "study_days": 4,
                    "minutes_per_day": 60,
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "PROPOSED")
        consume.assert_called_once_with(fake_db, 7)


if __name__ == "__main__":
    unittest.main()
