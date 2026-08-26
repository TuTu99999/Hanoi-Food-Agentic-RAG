import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from academic_agents.planning import PlanningAgentError
from assessment.question_bank import QuestionBankError
from core.security import get_current_user
from database.connection import get_db
from database.models import UserModel
from planning.learning_map import LearningMapError
from routers.academic_assistant import get_academic_agent_runtime
from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from schemas.planning import (
    LearningPlanApprovalResponse,
    LearningPlanCreateRequest,
    LearningPlanResponse,
)
from services.academic_agent_service import (
    AcademicAgentLimitError,
    consume_academic_planning_limit,
)
from services.planning_service import (
    AcademicPlanningService,
    PlanningConflictError,
    PlanningConstraintError,
    PlanningNotFoundError,
    PlanningRuntimeError,
)


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/academic-assistant/plans",
    tags=["Academic Planning"],
)


def _consume_limit(db: Session, user_id: int) -> None:
    try:
        consume_academic_planning_limit(db, user_id=user_id)
    except AcademicAgentLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bạn đã đạt giới hạn tạo kế hoạch.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except Exception as exc:
        logger.exception("Academic planning rate-limit check failed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hệ thống kiểm soát lượt dùng tạm thời chưa sẵn sàng.",
        ) from exc


def _handle_error(exc: Exception) -> None:
    if isinstance(exc, PlanningNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PlanningConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (PlanningConstraintError, PlanningAgentError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, (LearningMapError, QuestionBankError, PlanningRuntimeError)):
        raise HTTPException(
            status_code=503,
            detail="Dữ liệu lập kế hoạch của môn chưa sẵn sàng.",
        ) from exc
    logger.exception(
        "Academic planning request failed.",
        extra={"error_type": type(exc).__name__},
    )
    raise HTTPException(
        status_code=500,
        detail="Hệ thống chưa thể hoàn thành kế hoạch học.",
    ) from exc


@router.post("", response_model=LearningPlanResponse, status_code=201)
def create_learning_plan(
    payload: LearningPlanCreateRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime=Depends(get_academic_agent_runtime),
):
    _consume_limit(db, current_user.id)
    try:
        return AcademicPlanningService(db, runtime).create(
            payload,
            user_id=current_user.id,
        )
    except Exception as exc:
        _handle_error(exc)


@router.post(
    "/{plan_id}/approve",
    response_model=LearningPlanApprovalResponse,
)
def approve_learning_plan(
    plan_id: UUID,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime=Depends(get_academic_agent_runtime),
):
    _consume_limit(db, current_user.id)
    try:
        return AcademicPlanningService(db, runtime).approve(
            str(plan_id),
            user_id=current_user.id,
        )
    except Exception as exc:
        _handle_error(exc)


@router.get("/current", response_model=LearningPlanResponse)
def get_current_learning_plan(
    course_id: str = Query(pattern=COURSE_ID_PATTERN.pattern),
    course_version: str = Query(pattern=VERSION_PATTERN.pattern),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime=Depends(get_academic_agent_runtime),
):
    try:
        return AcademicPlanningService(db, runtime).get_current(
            user_id=current_user.id,
            course_id=course_id,
            course_version=course_version,
        )
    except Exception as exc:
        _handle_error(exc)
