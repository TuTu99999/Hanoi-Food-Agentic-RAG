import asyncio
import json
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
from schemas.chat import ChatRequest, ChatResponse
from services.chat_service import (
    ChatRateLimitExceededError,
    ChatSessionNotFoundError,
    get_recent_conversation,
    message_to_payload,
    reserve_chat_turn,
    update_assistant_message,
    update_assistant_message_task,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["RAG Chat"])

RAG_COLLECTION_NAME = settings.QDRANT_COLLECTION
RAG_ERROR_MESSAGE = "Xin lỗi, hệ thống chưa thể hoàn tất câu trả lời."
RAG_ERROR_CODE = "RAG_FAILED"
LLM_TIMEOUT_CODE = "LLM_TIMEOUT"
LLM_TIMEOUT_MESSAGE = (
    "Xin lỗi, hệ thống AI phản hồi quá chậm. Vui lòng thử lại."
)

# Danh sách 30 quận/huyện Hà Nội để đối soát từ khóa trong tin nhắn
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
    normalize_text(district): district
    for district in HANOI_DISTRICTS
}


def resolve_effective_district(
    user_question: str,
    ui_district: Optional[str],
) -> Optional[str]:
    """
    Xử lý độ ưu tiên lọc khu vực:
    1. Nếu tin nhắn chứa tên quận/huyện -> ưu tiên tên trong tin nhắn.
    2. Nếu không -> lấy quận ở UI nếu khác None / "Tất cả".
    """
    normalized_question = f" {normalize_text(user_question)} "
    for normalized_district, district in NORMALIZED_HANOI_DISTRICTS.items():
        if f" {normalized_district} " in normalized_question:
            return district

    if ui_district and ui_district != "Tất cả":
        return NORMALIZED_HANOI_DISTRICTS.get(
            normalize_text(ui_district)
        )

    return None


def get_rag_pipeline(request: Request):
    rag_pipeline = getattr(request.app.state, "rag_pipeline", None)
    if rag_pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lõi RAG chưa sẵn sàng.",
        )
    return rag_pipeline


def _reserve_turn_or_404(
    db: Session,
    *,
    current_user: UserModel,
    payload: ChatRequest,
    district: str | None,
):
    try:
        return reserve_chat_turn(
            db,
            user_id=current_user.id,
            session_id=payload.session_id,
            question=payload.question,
            district=district,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phiên hội thoại phù hợp.",
        ) from exc
    except ChatRateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Bạn gửi câu hỏi quá nhanh. Vui lòng thử lại sau.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc


def _run_rag(
    rag_pipeline,
    question: str,
    district: str | None,
    history: list[dict[str, str]],
) -> str:
    answer = rag_pipeline.run(
        user_question=question,
        collection_name=RAG_COLLECTION_NAME,
        district=district,
        history=history,
    )
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("RAG trả về nội dung rỗng.")
    return answer


def _sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


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
    session, user_message, assistant_message = _reserve_turn_or_404(
        db,
        current_user=current_user,
        payload=payload,
        district=effective_district,
    )
    session_id = session.id
    bind_session_id(session_id)
    assistant_message_id = assistant_message.id
    turn_id = assistant_message.turn_id
    history = get_recent_conversation(
        db,
        user_id=current_user.id,
        session_id=session_id,
        before_position=user_message.position,
    )

    try:
        answer = _run_rag(
            rag_pipeline,
            payload.question,
            effective_district,
            history,
        )
        assistant_message = update_assistant_message(
            db,
            user_id=current_user.id,
            session_id=session_id,
            assistant_message_id=assistant_message_id,
            turn_id=turn_id,
            content=answer,
            status="completed",
        )
    except Exception as exc:
        logger.exception("RAG xử lý thất bại cho session %s", session_id)
        try:
            update_assistant_message(
                db,
                user_id=current_user.id,
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
        "user_message": message_to_payload(user_message),
        "assistant_message": message_to_payload(assistant_message),
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
    session, user_message, assistant_message = _reserve_turn_or_404(
        db,
        current_user=current_user,
        payload=payload,
        district=effective_district,
    )

    session_id = session.id
    bind_session_id(session_id)
    user_id = current_user.id
    assistant_message_id = assistant_message.id
    turn_id = assistant_message.turn_id
    user_payload = message_to_payload(user_message)
    pending_assistant_payload = message_to_payload(assistant_message)
    history = get_recent_conversation(
        db,
        user_id=user_id,
        session_id=session_id,
        before_position=user_message.position,
    )

    async def persist_assistant(content: str, message_status: str) -> dict:
        return await asyncio.to_thread(
            lambda: update_assistant_message_task(
                user_id=user_id,
                session_id=session_id,
                assistant_message_id=assistant_message_id,
                turn_id=turn_id,
                content=content,
                status=message_status,
            ),
        )

    async def event_generator():
        assistant_finalized = False
        assistant_payload = pending_assistant_payload
        answer_parts = []
        rag_stream = None

        async def finalize_error(message: str) -> None:
            nonlocal assistant_finalized, assistant_payload
            if assistant_finalized:
                return

            partial_answer = "".join(answer_parts).strip()
            try:
                assistant_payload = await persist_assistant(
                    partial_answer or message,
                    "error",
                )
                assistant_finalized = True
            except Exception:
                logger.exception(
                    "Không thể cập nhật assistant message lỗi cho session %s",
                    session_id,
                )

        try:
            yield _sse_event(
                "session",
                {
                    "session_id": session_id,
                    "user_message": user_payload,
                    "assistant_message": pending_assistant_payload,
                },
            )

            loop = asyncio.get_running_loop()
            deadline = loop.time() + settings.LLM_TIMEOUT_SECONDS
            rag_stream = rag_pipeline.stream(
                user_question=payload.question,
                collection_name=RAG_COLLECTION_NAME,
                district=effective_district,
                history=history,
            )

            while True:
                remaining_seconds = deadline - loop.time()
                if remaining_seconds <= 0:
                    raise asyncio.TimeoutError

                try:
                    delta = await asyncio.wait_for(
                        rag_stream.__anext__(),
                        timeout=remaining_seconds,
                    )
                except StopAsyncIteration:
                    break

                if not isinstance(delta, str):
                    raise RuntimeError("RAG stream trả về delta không hợp lệ.")
                if not delta:
                    continue

                answer_parts.append(delta)
                yield _sse_event(
                    "token",
                    {
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "content": delta,
                    },
                )

            answer = "".join(answer_parts).strip()
            if not answer:
                raise RuntimeError("RAG stream trả về nội dung rỗng.")

            assistant_payload = await persist_assistant(answer, "completed")
            assistant_finalized = True
            logger.info(
                "RAG stream completed.",
                extra={"session_id": str(session_id)},
            )

            yield _sse_event(
                "done",
                {
                    "session_id": session_id,
                    "assistant_message": assistant_payload,
                },
            )
        except asyncio.CancelledError:
            if not assistant_finalized:
                try:
                    await asyncio.shield(
                        finalize_error(RAG_ERROR_MESSAGE)
                    )
                except Exception:
                    logger.exception(
                        "Không thể đánh dấu lượt stream bị hủy cho session %s",
                        session_id,
                    )
            raise
        except asyncio.TimeoutError:
            logger.warning(
                "LLM quá thời gian chờ cho session %s.",
                session_id,
            )
            await finalize_error(LLM_TIMEOUT_MESSAGE)
            yield _sse_event(
                "error",
                {
                    "session_id": session_id,
                    "code": LLM_TIMEOUT_CODE,
                    "message": LLM_TIMEOUT_MESSAGE,
                    "assistant_message": assistant_payload,
                },
            )
        except Exception:
            logger.exception("RAG stream thất bại cho session %s", session_id)
            await finalize_error(RAG_ERROR_MESSAGE)

            yield _sse_event(
                "error",
                {
                    "session_id": session_id,
                    "code": RAG_ERROR_CODE,
                    "message": RAG_ERROR_MESSAGE,
                    "assistant_message": assistant_payload,
                },
            )
        finally:
            if rag_stream is not None:
                try:
                    await rag_stream.aclose()
                except Exception:
                    logger.exception(
                        "Không thể đóng RAG stream cho session %s",
                        session_id,
                    )
            if not assistant_finalized:
                try:
                    await asyncio.shield(
                        finalize_error(RAG_ERROR_MESSAGE)
                    )
                except Exception:
                    logger.exception(
                        "Không thể finalize RAG stream cho session %s",
                        session_id,
                    )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
