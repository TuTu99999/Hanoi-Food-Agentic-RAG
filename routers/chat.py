import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from core.config import settings
from core.observability import bind_session_id
from core.security import get_current_user
from database.connection import get_db
from database.models import UserModel
from embedding.text_utils import normalize_text
from schemas.chat import ChatRequest, ChatResponse, NearbySearch
from services.chat_service import (
    ChatBudgetExceededError,
    ChatIdempotencyConflictError,
    ChatRateLimitExceededError,
    ChatSessionBusyError,
    ChatSessionNotFoundError,
    prepare_chat_turn_task,
    update_assistant_message_task,
)
from services.chat_stream_service import (
    LLM_TIMEOUT_MESSAGE,
    generate_chat_stream,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["RAG Chat"])

RAG_COLLECTION_NAME = settings.QDRANT_COLLECTION
RAG_ERROR_MESSAGE = "Xin lỗi, hệ thống chưa thể hoàn tất câu trả lời."
HANOI_DISTRICTS = [
    "Hoàn Kiếm",
    "Ba Đình",
    "Tây Hồ",
    "Cầu Giấy",
    "Hai Bà Trưng",
    "Đống Đa",
    "Thanh Xuân",
    "Hoàng Mai",
    "Long Biên",
    "Nam Từ Liêm",
    "Bắc Từ Liêm",
    "Hà Đông",
    "Sơn Tây",
    "Thanh Trì",
    "Gia Lâm",
    "Đông Anh",
    "Sóc Sơn",
    "Thạch Thất",
    "Quốc Oai",
    "Chương Mỹ",
    "Đan Phượng",
    "Hoài Đức",
    "Mê Linh",
    "Mỹ Đức",
    "Phú Xuyên",
    "Phúc Thọ",
    "Thanh Oai",
    "Thường Tín",
    "Ứng Hòa",
    "Ba Vì",
]
NORMALIZED_HANOI_DISTRICTS = {
    normalize_text(district): district for district in HANOI_DISTRICTS
}


def resolve_effective_district(
    user_question: str,
    ui_district: Optional[str],
) -> Optional[str]:
    normalized_question = f" {normalize_text(user_question)} "
    for normalized_district, district in NORMALIZED_HANOI_DISTRICTS.items():
        if f" {normalized_district} " in normalized_question:
            return district

    if ui_district and ui_district != "Tất cả":
        return NORMALIZED_HANOI_DISTRICTS.get(normalize_text(ui_district))

    return None


def get_rag_pipeline(request: Request):
    rag_pipeline = getattr(request.app.state, "rag_pipeline", None)
    if rag_pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lõi RAG chưa sẵn sàng.",
        )
    return rag_pipeline


def _raise_reservation_error(exc: Exception) -> None:
    if isinstance(exc, ChatSessionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phiên hội thoại phù hợp.",
        ) from exc
    if isinstance(exc, ChatRateLimitExceededError):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bạn gửi câu hỏi quá nhanh. Vui lòng thử lại sau.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    if isinstance(exc, ChatBudgetExceededError):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bạn đã đạt giới hạn sử dụng AI. Vui lòng thử lại sau.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    if isinstance(exc, ChatSessionBusyError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phiên hội thoại đang xử lý một câu hỏi khác.",
            headers={"Retry-After": "2"},
        ) from exc
    if isinstance(exc, ChatIdempotencyConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mã yêu cầu đã được sử dụng.",
        ) from exc
    raise exc


def _run_rag(
    rag_pipeline,
    question: str,
    district: str | None,
    history: list[dict[str, str]],
    nearby: NearbySearch | None = None,
) -> str:
    answer = rag_pipeline.run(
        user_question=question,
        collection_name=RAG_COLLECTION_NAME,
        district=district,
        history=history,
        **_nearby_kwargs(nearby),
    )
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("RAG trả về nội dung rỗng.")
    return answer


def _nearby_kwargs(nearby: NearbySearch | None) -> dict[str, float]:
    if nearby is None:
        return {}
    return {
        "user_latitude": nearby.latitude,
        "user_longitude": nearby.longitude,
        "radius_km": nearby.radius_km,
    }


@router.post("", response_model=ChatResponse)
def chat_with_rag(
    payload: ChatRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    rag_pipeline=Depends(get_rag_pipeline),
):
    effective_district = resolve_effective_district(
        payload.question,
        payload.district,
    )
    user_id = current_user.id
    db.close()

    try:
        prepared_turn = prepare_chat_turn_task(
            user_id=user_id,
            session_id=payload.session_id,
            client_request_id=payload.client_request_id,
            question=payload.question,
            district=effective_district,
        )
    except (
        ChatBudgetExceededError,
        ChatIdempotencyConflictError,
        ChatRateLimitExceededError,
        ChatSessionBusyError,
        ChatSessionNotFoundError,
    ) as exc:
        _raise_reservation_error(exc)

    session_id = prepared_turn.session_id
    bind_session_id(session_id)
    user_payload = prepared_turn.user_message
    assistant_payload = prepared_turn.assistant_message
    assistant_message_id = assistant_payload["id"]
    turn_id = assistant_payload["turn_id"]

    if not prepared_turn.created:
        if assistant_payload["status"] == "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Yêu cầu này đang được xử lý.",
                headers={"Retry-After": "2"},
            )
        if assistant_payload["status"] == "error":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=RAG_ERROR_MESSAGE,
            )
        return {
            "session_id": session_id,
            "user_message": user_payload,
            "assistant_message": assistant_payload,
        }

    try:
        answer = _run_rag(
            rag_pipeline,
            payload.question,
            effective_district,
            prepared_turn.history,
            payload.nearby,
        )
        assistant_payload = update_assistant_message_task(
            user_id=user_id,
            session_id=session_id,
            assistant_message_id=assistant_message_id,
            turn_id=turn_id,
            content=answer,
            status="completed",
        )
    except Exception as exc:
        logger.exception("RAG xử lý thất bại cho session %s", session_id)
        try:
            update_assistant_message_task(
                user_id=user_id,
                session_id=session_id,
                assistant_message_id=assistant_message_id,
                turn_id=turn_id,
                content=RAG_ERROR_MESSAGE,
                status="error",
            )
        except Exception:
            logger.exception(
                "Không thể cập nhật assistant message lỗi cho session %s",
                session_id,
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=RAG_ERROR_MESSAGE,
        ) from exc

    logger.info(
        "RAG request completed.",
        extra={"session_id": str(session_id)},
    )
    return {
        "session_id": session_id,
        "user_message": user_payload,
        "assistant_message": assistant_payload,
    }


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    rag_pipeline=Depends(get_rag_pipeline),
):
    effective_district = resolve_effective_district(
        payload.question,
        payload.district,
    )
    user_id = current_user.id
    db.close()

    try:
        prepared_turn = await asyncio.to_thread(
            prepare_chat_turn_task,
            user_id=user_id,
            session_id=payload.session_id,
            client_request_id=payload.client_request_id,
            question=payload.question,
            district=effective_district,
        )
    except (
        ChatBudgetExceededError,
        ChatIdempotencyConflictError,
        ChatRateLimitExceededError,
        ChatSessionBusyError,
        ChatSessionNotFoundError,
    ) as exc:
        _raise_reservation_error(exc)

    session_id = prepared_turn.session_id
    bind_session_id(session_id)

    if (
        not prepared_turn.created
        and prepared_turn.assistant_message["status"] == "pending"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Yêu cầu này đang được xử lý.",
            headers={"Retry-After": "2"},
        )

    return StreamingResponse(
        generate_chat_stream(
            rag_pipeline=rag_pipeline,
            user_id=user_id,
            session_id=session_id,
            question=payload.question,
            effective_district=effective_district,
            history=prepared_turn.history,
            nearby=payload.nearby,
            prepared_turn=prepared_turn,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "private, no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )