import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.security import get_current_user
from database.connection import get_db
from database.models import UserModel
from schemas.automation import LearningEventListResponse
from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from services.learning_event_service import LearningEventService


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/academic-assistant/events",
    tags=["Learning Automation"],
)


@router.get("", response_model=LearningEventListResponse)
def list_learning_events(
    course_id: str | None = Query(
        default=None,
        min_length=3,
        max_length=64,
        pattern=COURSE_ID_PATTERN.pattern,
    ),
    course_version: str | None = Query(
        default=None,
        min_length=5,
        max_length=32,
        pattern=VERSION_PATTERN.pattern,
    ),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return LearningEventService(db).list_for_user(
            user_id=current_user.id,
            course_id=course_id,
            course_version=course_version,
            limit=limit,
        )
    except Exception as exc:
        logger.exception(
            "Learning event query failed.",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=500,
            detail="Khong the doc lich su tu dong hoa hoc tap.",
        ) from exc
