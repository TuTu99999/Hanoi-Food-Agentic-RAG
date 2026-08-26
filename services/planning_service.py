import datetime
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from academic_agents.planning import PlanningAgentError
from database.models import (
    LearnerConceptMasteryModel,
    LearningPlanModel,
    UserModel,
)
from schemas.agents import AgentTraceEvent
from schemas.planning import (
    LearningPlanApprovalResponse,
    LearningPlanCreateRequest,
    LearningPlanDraft,
    LearningPlanResponse,
)
from services.learning_event_service import append_learning_event


class PlanningNotFoundError(LookupError):
    pass


class PlanningConflictError(RuntimeError):
    pass


class PlanningConstraintError(ValueError):
    pass


class PlanningRuntimeError(RuntimeError):
    pass


def _plan_response(plan: LearningPlanModel) -> LearningPlanResponse:
    return LearningPlanResponse(
        plan_id=plan.plan_id,
        course_id=plan.course_id,
        course_version=plan.course_version,
        title=plan.title,
        status=plan.status,
        revision=plan.revision,
        proposal_kind=plan.proposal_kind,
        parent_plan_id=plan.parent_plan_id,
        trigger_event_id=plan.trigger_event_id,
        draft=LearningPlanDraft.model_validate(plan.plan_json),
        verification_status="PASS",
        verification_critique=plan.verification_critique,
        agent_trace=[
            AgentTraceEvent.model_validate(event)
            for event in plan.agent_trace_json
        ],
        created_at=plan.created_at,
        approved_at=plan.approved_at,
    )


class AcademicPlanningService:
    def __init__(self, db: Session, runtime) -> None:
        if (
            getattr(runtime, "planning_workflow", None) is None
            or getattr(runtime, "learning_map_registry", None) is None
            or getattr(runtime, "question_bank_registry", None) is None
        ):
            raise PlanningRuntimeError("Planning runtime chưa được cấu hình.")
        self.db = db
        self.workflow = runtime.planning_workflow
        self.learning_maps = runtime.learning_map_registry
        self.question_banks = runtime.question_bank_registry

    def create(
        self,
        request: LearningPlanCreateRequest,
        *,
        user_id: int,
        today: datetime.date | None = None,
    ) -> LearningPlanResponse:
        plan = self._build_proposal(
            request,
            user_id=user_id,
            today=today,
            proposal_kind="INITIAL",
        )
        try:
            self.db.commit()
            self.db.refresh(plan)
        except Exception:
            self.db.rollback()
            raise
        return _plan_response(plan)

    def _build_proposal(
        self,
        request: LearningPlanCreateRequest,
        *,
        user_id: int,
        today: datetime.date | None = None,
        proposal_kind: str,
        parent_plan_id: str | None = None,
        trigger_event_id: str | None = None,
    ) -> LearningPlanModel:
        current_date = today or datetime.date.today()
        available_days = (request.target_date - current_date).days
        if available_days <= 0:
            raise PlanningConstraintError("Ngày mục tiêu phải sau ngày hiện tại.")
        study_days = request.study_days or available_days
        if study_days > available_days:
            raise PlanningConstraintError(
                "Số ngày học vượt quá số ngày còn lại trước ngày mục tiêu."
            )
        start_date = request.target_date - datetime.timedelta(days=study_days)

        learning_map = self.learning_maps.get(
            request.course_id,
            request.course_version,
        )
        question_bank = self.question_banks.get(
            request.course_id,
            request.course_version,
        )
        mastery_rows = (
            self.db.query(LearnerConceptMasteryModel)
            .filter(
                LearnerConceptMasteryModel.user_id == user_id,
                LearnerConceptMasteryModel.course_id == request.course_id,
                LearnerConceptMasteryModel.course_version
                == request.course_version,
            )
            .all()
        )
        mastery_by_concept = {
            row.concept_id: row.mastery_probability
            for row in mastery_rows
        }
        result = self.workflow.create_plan(
            learning_map,
            mastery_by_concept=mastery_by_concept,
            mastery_threshold=question_bank.bkt.mastery_threshold,
            initial_mastery=question_bank.bkt.p_initial,
            start_date=start_date,
            target_date=request.target_date,
            study_days=study_days,
            minutes_per_day=request.minutes_per_day,
            focus_concept_ids=request.focus_concept_ids,
        )
        if result.verification_status != "PASS":
            raise PlanningConstraintError(result.critique)

        (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .with_for_update()
            .first()
        )
        max_revision = (
            self.db.query(func.max(LearningPlanModel.revision))
            .filter(
                LearningPlanModel.user_id == user_id,
                LearningPlanModel.course_id == request.course_id,
                LearningPlanModel.course_version == request.course_version,
            )
            .scalar()
            or 0
        )
        plan = LearningPlanModel(
            plan_id=str(uuid4()),
            user_id=user_id,
            course_id=request.course_id,
            course_version=request.course_version,
            title=request.title or f"Lộ trình {learning_map.course_id}",
            status="PROPOSED",
            revision=max_revision + 1,
            proposal_kind=proposal_kind,
            parent_plan_id=parent_plan_id,
            trigger_event_id=trigger_event_id,
            request_json=request.model_dump(mode="json"),
            plan_json=result.draft.model_dump(mode="json"),
            verification_critique=result.critique,
            agent_trace_json=[
                event.model_dump(mode="json")
                for event in result.agent_trace
            ],
        )
        self.db.add(plan)
        append_learning_event(
            self.db,
            user_id=user_id,
            course_id=request.course_id,
            course_version=request.course_version,
            event_type="PLAN_PROPOSED",
            aggregate_type="plan",
            aggregate_id=plan.plan_id,
            correlation_id=plan.plan_id,
            payload={
                "proposal_kind": proposal_kind,
                "parent_plan_id": parent_plan_id,
                "trigger_event_id": trigger_event_id,
                "revision": plan.revision,
                "verification_status": "PASS",
            },
        )
        return plan

    def propose_replan(
        self,
        active_plan: LearningPlanModel,
        *,
        user_id: int,
        trigger_event_id: str,
        today: datetime.date | None = None,
    ) -> tuple[LearningPlanModel, bool]:
        pending = (
            self.db.query(LearningPlanModel)
            .filter(
                LearningPlanModel.user_id == user_id,
                LearningPlanModel.course_id == active_plan.course_id,
                LearningPlanModel.course_version == active_plan.course_version,
                LearningPlanModel.status == "PROPOSED",
                LearningPlanModel.proposal_kind == "REPLAN",
                LearningPlanModel.parent_plan_id == active_plan.plan_id,
            )
            .order_by(LearningPlanModel.revision.desc())
            .first()
        )
        if pending is not None:
            return pending, True

        original = LearningPlanCreateRequest.model_validate(
            active_plan.request_json
        )
        current_date = today or datetime.date.today()
        remaining_days = (original.target_date - current_date).days
        if remaining_days <= 0:
            raise PlanningConstraintError(
                "Ke hoach da het han, can nguoi hoc chon ngay muc tieu moi."
            )
        request = original.model_copy(
            update={
                "study_days": remaining_days,
                "focus_concept_ids": [],
                "title": f"{active_plan.title} - de xuat dieu chinh",
            }
        )
        plan = self._build_proposal(
            request,
            user_id=user_id,
            today=current_date,
            proposal_kind="REPLAN",
            parent_plan_id=active_plan.plan_id,
            trigger_event_id=trigger_event_id,
        )
        return plan, False

    def approve(
        self,
        plan_id: str,
        *,
        user_id: int,
    ) -> LearningPlanApprovalResponse:
        (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .with_for_update()
            .first()
        )
        plan = (
            self.db.query(LearningPlanModel)
            .filter(
                LearningPlanModel.plan_id == plan_id,
                LearningPlanModel.user_id == user_id,
            )
            .with_for_update()
            .first()
        )
        if plan is None:
            raise PlanningNotFoundError("Không tìm thấy kế hoạch học.")
        if plan.status != "PROPOSED":
            raise PlanningConflictError("Chỉ kế hoạch PROPOSED mới được duyệt.")

        previous_plans = (
            self.db.query(LearningPlanModel)
            .filter(
                LearningPlanModel.user_id == user_id,
                LearningPlanModel.course_id == plan.course_id,
                LearningPlanModel.course_version == plan.course_version,
                LearningPlanModel.status == "ACTIVE",
            )
            .with_for_update()
            .all()
        )
        for previous in previous_plans:
            previous.status = "REPLACED"
        approved_at = datetime.datetime.utcnow()
        plan.status = "ACTIVE"
        plan.approved_at = approved_at
        append_learning_event(
            self.db,
            user_id=user_id,
            course_id=plan.course_id,
            course_version=plan.course_version,
            event_type="PLAN_APPROVED",
            aggregate_type="plan",
            aggregate_id=plan.plan_id,
            correlation_id=plan.plan_id,
            payload={
                "proposal_kind": plan.proposal_kind,
                "revision": plan.revision,
                "replaced_plan_ids": [
                    previous.plan_id for previous in previous_plans
                ],
            },
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return LearningPlanApprovalResponse(
            plan_id=plan.plan_id,
            status="ACTIVE",
            approved_at=approved_at,
        )

    def get_current(
        self,
        *,
        user_id: int,
        course_id: str,
        course_version: str,
    ) -> LearningPlanResponse:
        plan = (
            self.db.query(LearningPlanModel)
            .filter(
                LearningPlanModel.user_id == user_id,
                LearningPlanModel.course_id == course_id,
                LearningPlanModel.course_version == course_version,
                LearningPlanModel.status == "ACTIVE",
            )
            .order_by(LearningPlanModel.revision.desc())
            .first()
        )
        if plan is None:
            raise PlanningNotFoundError("Chưa có kế hoạch ACTIVE cho môn này.")
        return _plan_response(plan)


__all__ = [
    "AcademicPlanningService",
    "PlanningAgentError",
    "PlanningConflictError",
    "PlanningConstraintError",
    "PlanningNotFoundError",
    "PlanningRuntimeError",
]
