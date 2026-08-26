import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "assessment-test-secret-at-least-32-bytes")
os.environ.setdefault("LLM_API_KEY", "assessment-test-llm-key")
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

from academic_agents.assessment import AssessmentAgent, AssessmentAgentError
from academic_agents.assessment_workflow import AcademicAssessmentWorkflow
from academic_agents.verification import VerificationAgent
from assessment.bkt import classify_mastery, update_bkt
from assessment.evaluation import evaluate_assessment_workflow
from assessment.question_bank import (
    QuestionBankError,
    QuestionBankRegistry,
    load_question_bank,
)
from core.security import get_current_user
from database.base import Base
from database.connection import get_db
from database.models import (
    AssessmentAttemptModel,
    LearnerConceptMasteryModel,
    UserModel,
)
from ingestion.service import ingest_course_package
from routers.academic_assistant import get_academic_agent_runtime
from routers.assessments import router
from schemas.assessment import (
    AssessmentGrade,
    AssessmentEvaluationSuite,
    AssessmentQuestion,
    AssessmentQuestionBank,
    AssessmentStartRequest,
    BKTParameters,
)
from schemas.ingestion import CitationMetadata
from services.assessment_service import (
    AcademicAssessmentService,
    AssessmentConflictError,
)
from services.academic_agent_service import (
    AcademicAgentLimitError,
    consume_academic_assessment_limit,
)


def question(
    question_id: str,
    concept_id: str,
    concept_name: str,
    *,
    difficulty: int = 1,
    correct: str = "A",
) -> AssessmentQuestion:
    return AssessmentQuestion(
        question_id=question_id,
        concept_id=concept_id,
        concept_name=concept_name,
        difficulty=difficulty,
        prompt=f"Câu hỏi kiểm tra {concept_name} là gì?",
        options=[
            {"option_id": "A", "text": "Phương án A"},
            {"option_id": "B", "text": "Phương án B"},
        ],
        correct_option_id=correct,
        explanation="Giải thích dựa trên giáo trình chính thức.",
        citation=CitationMetadata(
            document_id="official_textbook",
            document_title="Giáo trình chính thức",
            source_path="documents/textbook.md",
            source_type="official_textbook",
            source_authority="Nhà xuất bản kiểm thử",
            publication_year=2025,
            section_title="Chương 1",
            start_line=1,
            end_line=10,
        ),
    )


def question_bank(
    course_id: str = "political_philosophy",
) -> AssessmentQuestionBank:
    return AssessmentQuestionBank(
        course_id=course_id,
        course_version="1.0.0",
        questions=[
            question("matter_q001", "matter", "Vật chất", difficulty=1),
            question("matter_q002", "matter", "Vật chất", difficulty=3),
            question(
                "consciousness_q001",
                "consciousness",
                "Ý thức",
                difficulty=2,
                correct="B",
            ),
        ],
    )


def workflow() -> AcademicAssessmentWorkflow:
    return AcademicAssessmentWorkflow(
        assessment_agent=AssessmentAgent(),
        verification_agent=VerificationAgent(chat_model=None),
    )


class BKTTests(unittest.TestCase):
    def test_standard_bkt_update_for_correct_and_incorrect_observation(self):
        parameters = BKTParameters()
        self.assertEqual(
            update_bkt(0.2, is_correct=True, parameters=parameters),
            0.6,
        )
        self.assertEqual(
            update_bkt(0.2, is_correct=False, parameters=parameters),
            0.175758,
        )

    def test_mastery_classification_uses_configured_threshold(self):
        self.assertEqual(classify_mastery(0.49), "weak")
        self.assertEqual(classify_mastery(0.6), "developing")
        self.assertEqual(classify_mastery(0.8), "mastered")


class QuestionBankTests(unittest.TestCase):
    def test_schema_rejects_wrong_answer_and_missing_locator(self):
        payload = question("matter_q001", "matter", "Vật chất").model_dump()
        payload["correct_option_id"] = "C"
        with self.assertRaises(ValidationError):
            AssessmentQuestion.model_validate(payload)

        payload = question("matter_q001", "matter", "Vật chất").model_dump()
        payload["citation"].update(
            page_number=None,
            start_line=None,
            start_paragraph=None,
        )
        with self.assertRaises(ValidationError):
            AssessmentQuestion.model_validate(payload)

    def test_loader_checks_course_scope_and_registry_caches(self):
        with tempfile.TemporaryDirectory(prefix="question-bank-") as directory:
            root = Path(directory)
            bank_path = (
                root
                / "political_philosophy"
                / "1.0.0"
                / "assessment"
                / "questions.json"
            )
            bank_path.parent.mkdir(parents=True)
            bank_path.write_text(
                json.dumps(question_bank().model_dump(mode="json")),
                encoding="utf-8",
            )
            registry = QuestionBankRegistry(root)
            first = registry.get("political_philosophy", "1.0.0")
            second = registry.get("political_philosophy", "1.0.0")
            self.assertIs(first, second)
            with self.assertRaises(QuestionBankError):
                load_question_bank(
                    bank_path,
                    expected_course_id="hochiminh_thought",
                )
            with self.assertRaises(QuestionBankError):
                registry.get("../unsafe", "1.0.0")

    def test_ingestion_normalizes_optional_question_bank(self):
        with tempfile.TemporaryDirectory(prefix="assessment-package-") as directory:
            workspace = Path(directory)
            package = workspace / "package"
            documents = package / "documents"
            assessment = package / "assessment"
            documents.mkdir(parents=True)
            assessment.mkdir()
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
            (assessment / "questions.json").write_text(
                json.dumps(
                    question_bank().model_dump(mode="json"),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = ingest_course_package(
                package,
                output_root=workspace / "data",
            )
            self.assertIsNotNone(result.question_bank_path)
            self.assertTrue(result.question_bank_path.is_file())
            saved = load_question_bank(
                result.question_bank_path,
                expected_course_id="political_philosophy",
            )
            self.assertEqual(len(saved.questions), 3)


class AssessmentWorkflowTests(unittest.TestCase):
    def test_selects_weakest_concept_and_avoids_most_repeated_question(self):
        result = workflow().select_question(
            question_bank(),
            mastery_by_concept={"matter": 0.7, "consciousness": 0.2},
            attempt_count_by_question={"consciousness_q001": 0},
        )
        self.assertEqual(result.verification_status, "PASS")
        self.assertEqual(
            result.selection.question.question_id,
            "consciousness_q001",
        )
        self.assertEqual(
            [event.agent for event in result.agent_trace],
            ["OrchestratorAgent", "AssessmentAgent", "VerificationAgent"],
        )

        repeated = workflow().select_question(
            question_bank(),
            mastery_by_concept={"matter": 0.7},
            attempt_count_by_question={"matter_q001": 3, "matter_q002": 0},
            target_concept_id="matter",
        )
        self.assertEqual(repeated.selection.question.question_id, "matter_q002")

    def test_targeting_unknown_concept_is_rejected(self):
        with self.assertRaises(AssessmentAgentError):
            workflow().select_question(
                question_bank(),
                mastery_by_concept={},
                attempt_count_by_question={},
                target_concept_id="not_in_bank",
            )

    def test_grading_is_verified_and_tampering_is_blocked(self):
        selected_question = question_bank().questions[0]
        result = workflow().grade_answer(
            selected_question,
            selected_option_id="a",
            mastery_before=0.2,
            bkt_parameters=BKTParameters(),
        )
        self.assertEqual(result.verification_status, "PASS")
        self.assertTrue(result.grade.is_correct)
        self.assertEqual(result.mastery_after, 0.6)
        self.assertEqual(result.agent_trace[-1].action, "update_bkt_mastery")

        tampered = AssessmentGrade(
            question_id=selected_question.question_id,
            submitted_option_id="B",
            correct_option_id="A",
            is_correct=True,
            feedback="Kết quả đã bị sửa.",
        )
        verified = VerificationAgent.verify_assessment_grade(
            selected_question,
            tampered,
        )
        self.assertEqual(verified.status, "BLOCK")

    def test_evaluation_reports_selection_grading_and_bkt_metrics(self):
        suite = AssessmentEvaluationSuite.model_validate(
            {
                "selection_cases": [
                    {
                        "case_id": "select_001",
                        "mastery_by_concept": {
                            "matter": 0.2,
                            "consciousness": 0.7,
                        },
                        "attempt_count_by_question": {},
                        "expected_concept_id": "matter",
                        "expected_question_id": "matter_q001",
                    }
                ],
                "grading_cases": [
                    {
                        "case_id": "grade_001",
                        "question_id": "matter_q001",
                        "selected_option_id": "A",
                        "expected_is_correct": True,
                    }
                ],
            }
        )
        report = evaluate_assessment_workflow(
            workflow(),
            question_bank(),
            suite,
        )
        self.assertEqual(report.concept_selection_accuracy, 1.0)
        self.assertEqual(report.question_selection_accuracy, 1.0)
        self.assertEqual(report.grading_accuracy, 1.0)
        self.assertEqual(report.verification_pass_rate, 1.0)
        self.assertEqual(report.bkt_boundedness_rate, 1.0)


class StaticQuestionBankRegistry:
    def __init__(self, bank):
        self.bank = bank

    def get(self, course_id, course_version):
        if (
            course_id != self.bank.course_id
            or course_version != self.bank.course_version
        ):
            raise QuestionBankError("wrong scope")
        return self.bank


class AssessmentServiceTests(unittest.TestCase):
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
        self.db.query(AssessmentAttemptModel).delete()
        self.db.query(LearnerConceptMasteryModel).delete()
        self.db.query(UserModel).delete()
        user = UserModel(username="student", hashed_password="hash")
        self.db.add(user)
        self.db.commit()
        self.user_id = user.id
        self.runtime = SimpleNamespace(
            assessment_workflow=workflow(),
            question_bank_registry=StaticQuestionBankRegistry(question_bank()),
        )

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_start_hides_answer_submit_updates_bkt_and_rejects_replay(self):
        service = AcademicAssessmentService(self.db, self.runtime)
        started = service.start(
            AssessmentStartRequest(
                course_id="political_philosophy",
                course_version="1.0.0",
                concept_id="matter",
            ),
            user_id=self.user_id,
        )
        serialized = started.model_dump_json()
        self.assertNotIn("correct_option_id", serialized)
        self.assertEqual(started.mastery_before, 0.2)

        submitted = service.submit(
            started.attempt_id,
            selected_option_id="A",
            user_id=self.user_id,
        )
        self.assertTrue(submitted.is_correct)
        self.assertEqual(submitted.mastery_before, 0.2)
        self.assertEqual(submitted.mastery_after, 0.6)
        self.assertEqual(submitted.mastery_level, "developing")
        self.assertEqual(submitted.next_action, "continue_practice")

        with self.assertRaises(AssessmentConflictError):
            service.submit(
                started.attempt_id,
                selected_option_id="A",
                user_id=self.user_id,
            )

        mastery = service.get_mastery(
            user_id=self.user_id,
            course_id="political_philosophy",
            course_version="1.0.0",
        )
        matter = next(
            item for item in mastery.concepts if item.concept_id == "matter"
        )
        consciousness = next(
            item
            for item in mastery.concepts
            if item.concept_id == "consciousness"
        )
        self.assertEqual((matter.attempt_count, matter.correct_count), (1, 1))
        self.assertEqual(consciousness.mastery_probability, 0.2)

    def test_incorrect_answer_updates_only_the_current_user_and_course(self):
        service = AcademicAssessmentService(self.db, self.runtime)
        started = service.start(
            AssessmentStartRequest(
                course_id="political_philosophy",
                course_version="1.0.0",
                concept_id="matter",
            ),
            user_id=self.user_id,
        )
        submitted = service.submit(
            started.attempt_id,
            selected_option_id="B",
            user_id=self.user_id,
        )
        self.assertFalse(submitted.is_correct)
        self.assertEqual(submitted.mastery_after, 0.175758)
        self.assertEqual(submitted.next_action, "review_concept")
        self.assertEqual(
            self.db.query(LearnerConceptMasteryModel).count(),
            1,
        )


class AssessmentApiTests(unittest.TestCase):
    def test_assessment_limit_uses_own_scope_without_llm_budget(self):
        db = SimpleNamespace(rollback=lambda: None)
        allowed = SimpleNamespace(allowed=True, retry_after_seconds=10)
        with patch(
            "services.academic_agent_service.consume_rate_limit",
            return_value=allowed,
        ) as consume:
            consume_academic_assessment_limit(db, user_id=7)
        self.assertEqual(consume.call_count, 1)
        self.assertEqual(
            consume.call_args.kwargs["scope"],
            "academic_assessment.user",
        )

        blocked = SimpleNamespace(allowed=False, retry_after_seconds=42)
        with patch(
            "services.academic_agent_service.consume_rate_limit",
            return_value=blocked,
        ):
            with self.assertRaises(AcademicAgentLimitError) as raised:
                consume_academic_assessment_limit(db, user_id=7)
        self.assertEqual(raised.exception.retry_after_seconds, 42)

    def test_start_endpoint_uses_auth_runtime_and_rate_limit(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        fake_runtime = SimpleNamespace()
        fake_db = SimpleNamespace()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: fake_db
        app.dependency_overrides[get_academic_agent_runtime] = lambda: fake_runtime

        fake_response = SimpleNamespace()
        service = SimpleNamespace(start=lambda payload, user_id: fake_response)
        expected_payload = {
            "attempt_id": "00000000-0000-0000-0000-000000000001",
            "course_id": "political_philosophy",
            "course_version": "1.0.0",
            "question": {
                "question_id": "matter_q001",
                "concept_id": "matter",
                "concept_name": "Vật chất",
                "question_type": "multiple_choice",
                "difficulty": 1,
                "prompt": "Vật chất là gì?",
                "options": [
                    {"option_id": "A", "text": "Đáp án A"},
                    {"option_id": "B", "text": "Đáp án B"},
                ],
                "citation": question(
                    "matter_q001", "matter", "Vật chất"
                ).citation.model_dump(mode="json"),
            },
            "mastery_before": 0.2,
            "selection_reason": "Chọn concept yếu.",
            "agent_trace": [],
        }
        service.start = lambda payload, user_id: expected_payload
        with (
            patch("routers.assessments._consume_limit") as consume,
            patch(
                "routers.assessments.AcademicAssessmentService",
                return_value=service,
            ) as service_factory,
        ):
            result = TestClient(app).post(
                "/api/academic-assistant/assessments/start",
                json={
                    "course_id": "political_philosophy",
                    "course_version": "1.0.0",
                },
            )
        self.assertEqual(result.status_code, 201)
        self.assertNotIn("correct_option_id", result.text)
        consume.assert_called_once_with(fake_db, 7)
        service_factory.assert_called_once_with(fake_db, fake_runtime)


if __name__ == "__main__":
    unittest.main()
