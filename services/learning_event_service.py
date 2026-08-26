from uuid import uuid4

from sqlalchemy.orm import Session

from database.models import LearningEventModel
from schemas.automation import (
    LearningEventListResponse,
    LearningEventResponse,
    LearningEventType,
)


def append_learning_event(
    db: Session,
    *,
    user_id: int,
    course_id: str,
    course_version: str,
    event_type: LearningEventType,
    aggregate_type: str,
    aggregate_id: str | None,
    correlation_id: str | None,
    payload: dict,
) -> LearningEventModel:
    if correlation_id is not None:
        existing = (
            db.query(LearningEventModel)
            .filter(
                LearningEventModel.event_type == event_type,
                LearningEventModel.correlation_id == correlation_id,
            )
            .first()
        )
        if existing is not None:
            return existing

    event = LearningEventModel(
        event_id=str(uuid4()),
        user_id=user_id,
        course_id=course_id,
        course_version=course_version,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        payload_json=payload,
    )
    db.add(event)
    return event


def _event_response(event: LearningEventModel) -> LearningEventResponse:
    return LearningEventResponse(
        event_id=event.event_id,
        course_id=event.course_id,
        course_version=event.course_version,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        correlation_id=event.correlation_id,
        payload=event.payload_json,
        created_at=event.created_at,
    )


class LearningEventService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(
        self,
        *,
        user_id: int,
        course_id: str | None = None,
        course_version: str | None = None,
        limit: int = 50,
    ) -> LearningEventListResponse:
        query = self.db.query(LearningEventModel).filter(
            LearningEventModel.user_id == user_id
        )
        if course_id is not None:
            query = query.filter(LearningEventModel.course_id == course_id)
        if course_version is not None:
            query = query.filter(
                LearningEventModel.course_version == course_version
            )
        events = (
            query.order_by(
                LearningEventModel.created_at.desc(),
                LearningEventModel.id.desc(),
            )
            .limit(limit)
            .all()
        )
        return LearningEventListResponse(
            events=[_event_response(event) for event in events]
        )


__all__ = [
    "LearningEventService",
    "append_learning_event",
]
