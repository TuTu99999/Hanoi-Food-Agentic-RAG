import os
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "automation-test-secret-at-least-32-bytes")
os.environ.setdefault("LLM_API_KEY", "automation-test-llm-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("AUTH_COOKIE_SECURE", "false")
os.environ.setdefault("AUTH_COOKIE_SAMESITE", "lax")
os.environ.setdefault("DB_SCHEMA_CHECK", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from automation.evaluation import evaluate_automation_policy
from automation.policy import decide_replan
from core.security import get_current_user
from database.base import Base
from database.connection import get_db
from database.models import (
    LearningEventModel,
    LearningPlanModel,
    UserModel,
)
from routers.automation import router
from schemas.assessment import AssessmentStartRequest, BKTParameters
from schemas.automation import AutomationEvaluationCase
from schemas.planning import LearningPlanCreateRequest
from services.assessment_service import AcademicAssessmentService
from services.planning_service import AcademicPlanningService
from tests.test_assessment_bkt import question_bank
from tests.test_assessment_bkt import workflow as assessment_workflow
from tests.test_planning_agent import StaticRegistry, learning_map
from tests.test_planning_agent import workflow as planning_workflow


class ClosedLoopPolicyTests(unittest.TestCase):
    def test_policy_is_explainable_and_prevents_duplicate_proposals(self):
        create = decide_replan(
            is_correct=False,
            mastery_after=0.2,
            has_active_plan=True,
            has_pending_replan=False,
        )
        self.assertTrue(create.replan_required)
        self.assertTrue(create.create_proposal)
        self.assertEqual(create.reason, "WEAKNESS_DETECTED")

        duplicate = decide_replan(
            is_correct=False,
            mastery_after=0.2,
            has_active_plan=True,
            has_pending_replan=True,
        )
        self.assertTrue(duplicate.replan_required)
        self.assertFalse(duplicate.create_proposal)
        self.assertEqual(duplicate.reason, "PENDING_REPLAN_EXISTS")

    def test_policy_evaluation_reports_core_automation_metrics(self):
        cases = [
            AutomationEvaluationCase(
                case_id="weak_with_active",
                is_correct=False,
                mastery_after=0.2,
                has_active_plan=True,
                expected_replan_required=True,
                expected_create_proposal=True,
            ),
            AutomationEvaluationCase(
                case_id="reuse_pending",
                is_correct=False,
                mastery_after=0.2,
                has_active_plan=True,
                has_pending_replan=True,
                expected_replan_required=True,
                expected_create_proposal=False,
            ),
            AutomationEvaluationCase(
                case_id="no_active",
                is_correct=False,
                mastery_after=0.2,
                has_active_plan=False,
                expected_replan_required=False,
                expected_create_proposal=False,
            ),
        ]
        report = evaluate_automation_policy(cases)
        self.assertEqual(report.trigger_accuracy, 1.0)
        self.assertEqual(report.proposal_decision_accuracy, 1.0)
        self.assertEqual(report.duplicate_prevention_rate, 1.0)
        self.assertEqual(report.human_approval_compliance_rate, 1.0)


class ClosedLoopServiceTests(unittest.TestCase):
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
        self.db.query(LearningEventModel).delete()
        self.db.query(LearningPlanModel).delete()
        self.db.query(UserModel).delete()
        user = UserModel(username="automation-student", hashed_password="hash")
        self.db.add(user)
        self.db.commit()
        self.user_id = user.id
        bank = question_bank()
        self.runtime = SimpleNamespace(
            assessment_workflow=assessment_workflow(),
            question_bank_registry=StaticRegistry(bank),
            planning_workflow=planning_workflow(),
            learning_map_registry=StaticRegistry(learning_map()),
        )

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _activate_plan(self, *, target_date="2026-09-10"):
        service = AcademicPlanningService(self.db, self.runtime)
        proposed = service.create(
            LearningPlanCreateRequest(
                course_id="political_philosophy",
                course_version="1.0.0",
                target_date=target_date,
                study_days=8,
                minutes_per_day=60,
            ),
            user_id=self.user_id,
            today=date(2026, 9, 1),
        )
        service.approve(proposed.plan_id, user_id=self.user_id)
        return proposed

    def _submit_wrong(self, *, today=date(2026, 9, 2)):
        service = AcademicAssessmentService(self.db, self.runtime)
        started = service.start(
            AssessmentStartRequest(
                course_id="political_philosophy",
                course_version="1.0.0",
                concept_id="matter",
            ),
            user_id=self.user_id,
        )
        return service.submit(
            started.attempt_id,
            selected_option_id="B",
            user_id=self.user_id,
            today=today,
        )

    def test_wrong_weak_answer_proposes_verified_revision_for_approval(self):
        active = self._activate_plan()
        submitted = self._submit_wrong()

        self.assertTrue(submitted.automation.replan_required)
        self.assertEqual(submitted.automation.reason, "WEAKNESS_DETECTED")
        self.assertIsNotNone(submitted.automation.proposed_plan_id)
        statuses = {
            plan.plan_id: plan.status
            for plan in self.db.query(LearningPlanModel).all()
        }
        self.assertEqual(statuses[active.plan_id], "ACTIVE")
        revision = (
            self.db.query(LearningPlanModel)
            .filter(
                LearningPlanModel.plan_id
                == submitted.automation.proposed_plan_id
            )
            .one()
        )
        self.assertEqual(revision.status, "PROPOSED")
        self.assertEqual(revision.proposal_kind, "REPLAN")
        self.assertEqual(revision.parent_plan_id, active.plan_id)
        self.assertIsNotNone(revision.trigger_event_id)
        self.assertEqual(
            [event.agent for event in submitted.automation.agent_trace],
            [
                "OrchestratorAgent",
                "OrchestratorAgent",
                "PlanningAgent",
                "VerificationAgent",
            ],
        )

        event_types = [
            event.event_type
            for event in self.db.query(LearningEventModel)
            .order_by(LearningEventModel.id)
            .all()
        ]
        self.assertIn("MASTERY_UPDATED", event_types)
        self.assertIn("REPLAN_REQUIRED", event_types)
        self.assertEqual(event_types.count("PLAN_PROPOSED"), 2)

    def test_pending_revision_is_reused_and_not_duplicated(self):
        self._activate_plan()
        first = self._submit_wrong()
        second = self._submit_wrong()

        self.assertEqual(
            second.automation.proposed_plan_id,
            first.automation.proposed_plan_id,
        )
        self.assertTrue(second.automation.reused_existing_proposal)
        self.assertEqual(second.automation.reason, "PENDING_REPLAN_EXISTS")
        self.assertEqual(self.db.query(LearningPlanModel).count(), 2)

    def test_approval_replaces_active_plan_and_records_event(self):
        active = self._activate_plan()
        submitted = self._submit_wrong()
        AcademicPlanningService(self.db, self.runtime).approve(
            submitted.automation.proposed_plan_id,
            user_id=self.user_id,
        )

        self.assertEqual(
            self.db.query(LearningPlanModel)
            .filter(LearningPlanModel.plan_id == active.plan_id)
            .one()
            .status,
            "REPLACED",
        )
        self.assertEqual(
            self.db.query(LearningPlanModel)
            .filter(
                LearningPlanModel.plan_id
                == submitted.automation.proposed_plan_id
            )
            .one()
            .status,
            "ACTIVE",
        )
        self.assertEqual(
            self.db.query(LearningEventModel)
            .filter(LearningEventModel.event_type == "PLAN_APPROVED")
            .count(),
            2,
        )

    def test_no_active_plan_only_records_mastery_update(self):
        submitted = self._submit_wrong()
        self.assertFalse(submitted.automation.replan_required)
        self.assertEqual(submitted.automation.reason, "NO_ACTIVE_PLAN")
        self.assertEqual(self.db.query(LearningPlanModel).count(), 0)
        self.assertEqual(
            [
                event.event_type
                for event in self.db.query(LearningEventModel).all()
            ],
            ["MASTERY_UPDATED"],
        )

    def test_expired_plan_reports_blocker_without_losing_assessment(self):
        self._activate_plan()
        submitted = self._submit_wrong(today=date(2026, 9, 10))
        self.assertTrue(submitted.automation.replan_required)
        self.assertEqual(submitted.automation.reason, "REPLAN_BLOCKED")
        self.assertIsNone(submitted.automation.proposed_plan_id)
        self.assertEqual(self.db.query(LearningPlanModel).count(), 1)
        self.assertEqual(
            self.db.query(LearningEventModel)
            .filter(LearningEventModel.event_type == "MASTERY_UPDATED")
            .count(),
            1,
        )


class LearningEventApiTests(unittest.TestCase):
    def test_endpoint_uses_authenticated_user_scope(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        fake_db = SimpleNamespace()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: fake_db
        service = SimpleNamespace(
            list_for_user=Mock(return_value={"events": []})
        )
        with patch(
            "routers.automation.LearningEventService",
            return_value=service,
        ) as factory:
            response = TestClient(app).get(
                "/api/academic-assistant/events",
                params={
                    "course_id": "political_philosophy",
                    "course_version": "1.0.0",
                    "limit": 20,
                },
            )
        self.assertEqual(response.status_code, 200)
        factory.assert_called_once_with(fake_db)
        service.list_for_user.assert_called_once_with(
            user_id=7,
            course_id="political_philosophy",
            course_version="1.0.0",
            limit=20,
        )


if __name__ == "__main__":
    unittest.main()
