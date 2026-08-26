import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from academic_agents.assessment import AssessmentAgentError
from assessment.question_bank import QuestionBankError
from core.security import get_current_user
from database.connection import get_db
from database.models import UserModel
from routers.academic_assistant import get_academic_agent_runtime
from schemas.assessment import (
    AssessmentStartRequest,
    AssessmentStartResponse,
    AssessmentSubmitRequest,
    AssessmentSubmitResponse,
    CourseMasteryResponse,
)
from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from services.academic_agent_service import (
    AcademicAgentLimitError,
    consume_academic_assessment_limit,
)
from services.assessment_service import (
    AcademicAssessmentService,
    AssessmentConflictError,
    AssessmentNotFoundError,
    AssessmentVerificationError,
)


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/academic-assistant/assessments",
    tags=["Academic Assessment"],
)


def _consume_limit(db: Session, user_id: int) -> None:
    try:
        consume_academic_assessment_limit(db, user_id=user_id)
    except AcademicAgentLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bạn đã đạt giới hạn thao tác đánh giá.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except Exception as exc:
        logger.exception("Academic assessment rate-limit check failed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hệ thống kiểm soát lượt dùng tạm thời chưa sẵn sàng.",
        ) from exc


def _handle_service_error(exc: Exception) -> None:
    if isinstance(exc, AssessmentNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if isinstance(exc, AssessmentConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, AssessmentAgentError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if isinstance(exc, QuestionBankError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ngân hàng câu hỏi của môn chưa sẵn sàng.",
        ) from exc
    if isinstance(exc, AssessmentVerificationError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Không thể xác minh câu hỏi hoặc kết quả chấm.",
        ) from exc
    logger.exception(
        "Academic assessment request failed.",
        extra={"error_type": type(exc).__name__},
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Hệ thống đánh giá chưa thể hoàn thành yêu cầu.",
    ) from exc


@router.post(
    "/start",
    response_model=AssessmentStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_assessment(
    payload: AssessmentStartRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime=Depends(get_academic_agent_runtime),
):
    _consume_limit(db, current_user.id)
    try:
        return AcademicAssessmentService(db, runtime).start(
            payload,
            user_id=current_user.id,
        )
    except Exception as exc:
        _handle_service_error(exc)


@router.post(
    "/{attempt_id}/submit",
    response_model=AssessmentSubmitResponse,
)
def submit_assessment(
    attempt_id: UUID,
    payload: AssessmentSubmitRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime=Depends(get_academic_agent_runtime),
):
    _consume_limit(db, current_user.id)
    try:
        return AcademicAssessmentService(db, runtime).submit(
            str(attempt_id),
            selected_option_id=payload.selected_option_id,
            user_id=current_user.id,
        )
    except Exception as exc:
        _handle_service_error(exc)


@router.get("/mastery", response_model=CourseMasteryResponse)
def get_course_mastery(
    course_id: str = Query(
        min_length=3,
        max_length=64,
        pattern=COURSE_ID_PATTERN.pattern,
    ),
    course_version: str = Query(
        min_length=5,
        max_length=32,
        pattern=VERSION_PATTERN.pattern,
    ),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime=Depends(get_academic_agent_runtime),
):
    try:
        return AcademicAssessmentService(db, runtime).get_mastery(
            user_id=current_user.id,
            course_id=course_id,
            course_version=course_version,
        )
    except Exception as exc:
        _handle_service_error(exc)
