import datetime

from sqlalchemy.orm import Session

from academic_agents.planning import PlanningAgentError
from academic_agents.routing import OrchestratorAgent
from assessment.question_bank import QuestionBankError
from database.models import AssessmentAttemptModel, LearningPlanModel
from planning.learning_map import LearningMapError
from schemas.agents import AgentTraceEvent
from schemas.automation import AutomationOutcome
from services.learning_event_service import append_learning_event
from services.planning_service import (
    AcademicPlanningService,
    PlanningConstraintError,
    PlanningRuntimeError,
)


_REPLAN_BLOCKERS = (
    PlanningAgentError,
    PlanningConstraintError,
    PlanningRuntimeError,
    LearningMapError,
    QuestionBankError,
)


class ClosedLoopAutomationService:
    """Coordinate UC04 without auto-approving an AI-generated plan."""

    def __init__(self, db: Session, runtime) -> None:
        self.db = db
        self.runtime = runtime

    def handle_mastery_updated(
        self,
        *,
        attempt: AssessmentAttemptModel,
        user_id: int,
        is_correct: bool,
        mastery_before: float,
        mastery_after: float,
        today: datetime.date | None = None,
    ) -> AutomationOutcome:
        mastery_event = append_learning_event(
            self.db,
            user_id=user_id,
            course_id=attempt.course_id,
            course_version=attempt.course_version,
            event_type="MASTERY_UPDATED",
            aggregate_type="concept",
            aggregate_id=attempt.concept_id,
            correlation_id=attempt.attempt_id,
            payload={
                "attempt_id": attempt.attempt_id,
                "question_id": attempt.question_id,
                "is_correct": is_correct,
                "mastery_before": mastery_before,
                "mastery_after": mastery_after,
            },
        )
        active_plan = (
            self.db.query(LearningPlanModel)
            .filter(
                LearningPlanModel.user_id == user_id,
                LearningPlanModel.course_id == attempt.course_id,
                LearningPlanModel.course_version == attempt.course_version,
                LearningPlanModel.status == "ACTIVE",
            )
            .order_by(LearningPlanModel.revision.desc())
            .with_for_update()
            .first()
        )
        pending_replan = None
        if active_plan is not None:
            pending_replan = (
                self.db.query(LearningPlanModel)
                .filter(
                    LearningPlanModel.user_id == user_id,
                    LearningPlanModel.course_id == attempt.course_id,
                    LearningPlanModel.course_version == attempt.course_version,
                    LearningPlanModel.status == "PROPOSED",
                    LearningPlanModel.proposal_kind == "REPLAN",
                    LearningPlanModel.parent_plan_id == active_plan.plan_id,
                )
                .order_by(LearningPlanModel.revision.desc())
                .first()
            )

        orchestrator = getattr(self.runtime, "orchestrator_agent", None)
        if orchestrator is None:
            orchestrator = OrchestratorAgent(chat_model=None)
        decision = orchestrator.decide_replan(
            is_correct=is_correct,
            mastery_after=mastery_after,
            has_active_plan=active_plan is not None,
            has_pending_replan=pending_replan is not None,
        )
        trace = [
            AgentTraceEvent(
                sequence=1,
                agent="OrchestratorAgent",
                action="evaluate_replan_trigger",
                status=decision.reason,
                details={
                    "concept_id": attempt.concept_id,
                    "is_correct": is_correct,
                    "mastery_after": mastery_after,
                    "has_active_plan": active_plan is not None,
                    "has_pending_replan": pending_replan is not None,
                },
            )
        ]
        if not decision.replan_required:
            messages = {
                "NO_ACTIVE_PLAN": (
                    "Mastery da duoc cap nhat; chua co ke hoach ACTIVE de dieu chinh."
                ),
                "ANSWER_CORRECT": (
                    "Mastery da duoc cap nhat; cau tra loi dung khong kich hoat lap lai."
                ),
                "MASTERY_NOT_WEAK": (
                    "Mastery da duoc cap nhat; concept chua o muc weak."
                ),
            }
            return AutomationOutcome(
                mastery_event_id=mastery_event.event_id,
                replan_required=False,
                reason=decision.reason,
                message=messages[decision.reason],
                agent_trace=trace,
            )

        replan_event = append_learning_event(
            self.db,
            user_id=user_id,
            course_id=attempt.course_id,
            course_version=attempt.course_version,
            event_type="REPLAN_REQUIRED",
            aggregate_type="plan",
            aggregate_id=active_plan.plan_id,
            correlation_id=attempt.attempt_id,
            payload={
                "active_plan_id": active_plan.plan_id,
                "concept_id": attempt.concept_id,
                "mastery_after": mastery_after,
                "status": "PENDING",
            },
        )

        if pending_replan is not None:
            replan_event.payload_json = {
                **replan_event.payload_json,
                "status": "REUSED_EXISTING_PROPOSAL",
                "proposed_plan_id": pending_replan.plan_id,
            }
            trace.append(
                AgentTraceEvent(
                    sequence=2,
                    agent="System",
                    action="reuse_pending_replan",
                    status="completed",
                    details={"plan_id": pending_replan.plan_id},
                )
            )
            return AutomationOutcome(
                mastery_event_id=mastery_event.event_id,
                replan_required=True,
                reason="PENDING_REPLAN_EXISTS",
                proposed_plan_id=pending_replan.plan_id,
                reused_existing_proposal=True,
                message=(
                    "Da co mot de xuat dieu chinh dang cho duyet; he thong khong tao trung."
                ),
                agent_trace=trace,
            )

        try:
            plan, reused = AcademicPlanningService(
                self.db,
                self.runtime,
            ).propose_replan(
                active_plan,
                user_id=user_id,
                trigger_event_id=replan_event.event_id,
                today=today,
            )
        except _REPLAN_BLOCKERS as exc:
            replan_event.payload_json = {
                **replan_event.payload_json,
                "status": "BLOCKED",
                "blocker_type": type(exc).__name__,
            }
            trace.append(
                AgentTraceEvent(
                    sequence=2,
                    agent="System",
                    action="propose_replan",
                    status="BLOCKED",
                    details={"blocker_type": type(exc).__name__},
                )
            )
            return AutomationOutcome(
                mastery_event_id=mastery_event.event_id,
                replan_required=True,
                reason="REPLAN_BLOCKED",
                message=(
                    "Can dieu chinh ke hoach nhung rang buoc hien tai chua cho phep; "
                    "nguoi hoc can chon lai ngay hoac thoi luong."
                ),
                agent_trace=trace,
            )

        replan_event.payload_json = {
            **replan_event.payload_json,
            "status": "PROPOSED",
            "proposed_plan_id": plan.plan_id,
        }
        for event in plan.agent_trace_json:
            trace.append(
                AgentTraceEvent.model_validate(event).model_copy(
                    update={"sequence": len(trace) + 1}
                )
            )
        return AutomationOutcome(
            mastery_event_id=mastery_event.event_id,
            replan_required=True,
            reason="PENDING_REPLAN_EXISTS" if reused else "WEAKNESS_DETECTED",
            proposed_plan_id=plan.plan_id,
            reused_existing_proposal=reused,
            message=(
                "He thong da tao ke hoach dieu chinh da qua Verification; "
                "ke hoach dang cho nguoi hoc duyet."
            ),
            agent_trace=trace,
        )


__all__ = ["ClosedLoopAutomationService"]
