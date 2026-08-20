import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Optional

from core.config import settings
from core.metrics import chat_stream_finished
from services.chat_service import update_assistant_message_task

logger = logging.getLogger(__name__)

RAG_ERROR_MESSAGE = "Xin lỗi, hệ thống chưa thể hoàn tất câu trả lời."
RAG_ERROR_CODE = "RAG_FAILED"
LLM_TIMEOUT_CODE = "LLM_TIMEOUT"
LLM_TIMEOUT_MESSAGE = (
    "Xin lỗi, hệ thống AI phản hồi quá chậm. Vui lòng thử lại."
)


def _sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _nearby_kwargs(nearby: Any) -> dict[str, float]:
    if nearby is None:
        return {}
    return {
        "user_latitude": nearby.latitude,
        "user_longitude": nearby.longitude,
        "radius_km": nearby.radius_km,
    }


async def _persist_assistant(
    user_id: Any,
    session_id: str,
    assistant_message_id: str,
    turn_id: str,
    content: str,
    message_status: str,
) -> dict:
    return await asyncio.to_thread(
        lambda: update_assistant_message_task(
            user_id=user_id,
            session_id=session_id,
            assistant_message_id=assistant_message_id,
            turn_id=turn_id,
            content=content,
            status=message_status,
        )
    )


async def generate_chat_stream(
    rag_pipeline: Any,
    user_id: Any,
    session_id: str,
    question: str,
    effective_district: Optional[str],
    history: list[dict[str, str]],
    nearby: Any,
    prepared_turn: Any,
) -> AsyncGenerator[str, None]:
    assistant_finalized = False
    stream_outcome_recorded = False

    user_payload = prepared_turn.user_message
    pending_assistant_payload = prepared_turn.assistant_message
    assistant_payload = pending_assistant_payload
    assistant_message_id = pending_assistant_payload["id"]
    turn_id = pending_assistant_payload["turn_id"]

    answer_parts = []
    rag_stream = None

    def record_stream_outcome(outcome: str) -> None:
        nonlocal stream_outcome_recorded
        if stream_outcome_recorded:
            return
        chat_stream_finished(outcome)
        stream_outcome_recorded = True

    async def finalize_error(message: str) -> None:
        nonlocal assistant_finalized, assistant_payload
        if assistant_finalized:
            return

        partial_answer = "".join(answer_parts).strip()
        try:
            assistant_payload = await _persist_assistant(
                user_id=user_id,
                session_id=session_id,
                assistant_message_id=assistant_message_id,
                turn_id=turn_id,
                content=partial_answer or message,
                message_status="error",
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

        if not prepared_turn.created:
            assistant_finalized = True
            if pending_assistant_payload["status"] == "completed":
                record_stream_outcome("replayed")
                yield _sse_event(
                    "done",
                    {
                        "session_id": session_id,
                        "assistant_message": pending_assistant_payload,
                    },
                )
            else:
                record_stream_outcome("replayed_error")
                yield _sse_event(
                    "error",
                    {
                        "session_id": session_id,
                        "code": RAG_ERROR_CODE,
                        "message": RAG_ERROR_MESSAGE,
                        "assistant_message": pending_assistant_payload,
                    },
                )
            return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.LLM_TIMEOUT_SECONDS
        rag_stream = rag_pipeline.stream(
            user_question=question,
            collection_name=settings.QDRANT_COLLECTION,
            district=effective_district,
            history=history,
            **_nearby_kwargs(nearby),
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

        assistant_payload = await _persist_assistant(
            user_id=user_id,
            session_id=session_id,
            assistant_message_id=assistant_message_id,
            turn_id=turn_id,
            content=answer,
            message_status="completed",
        )
        assistant_finalized = True
        record_stream_outcome("completed")
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
        record_stream_outcome("cancelled")
        if not assistant_finalized:
            try:
                await asyncio.shield(finalize_error(RAG_ERROR_MESSAGE))
            except Exception:
                logger.exception(
                    "Không thể đánh dấu lượt stream bị hủy cho session %s",
                    session_id,
                )
        raise
    except asyncio.TimeoutError:
        record_stream_outcome("timeout")
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
        record_stream_outcome("error")
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
                await asyncio.shield(finalize_error(RAG_ERROR_MESSAGE))
            except Exception:
                logger.exception(
                    "Không thể finalize RAG stream cho session %s",
                    session_id,
                )
        if not stream_outcome_recorded:
            record_stream_outcome("cancelled")