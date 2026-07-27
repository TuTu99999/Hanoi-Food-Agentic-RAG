import datetime
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.config import settings
from database.connection import SessionLocal
from database.models import ChatSessionModel, MessageModel, UserModel


NEW_SESSION_TITLE = "Cuộc trò chuyện mới"
CHAT_HISTORY_MAX_TURNS = 3
CHAT_HISTORY_MAX_CHARACTERS = 6000


class ChatSessionNotFoundError(Exception):
    pass


class AssistantMessageNotFoundError(Exception):
    pass


class ChatRateLimitExceededError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__("Chat rate limit exceeded.")


def message_to_payload(message: MessageModel) -> dict:
    return {
        "id": message.id,
        "turn_id": message.turn_id,
        "position": message.position,
        "role": message.role,
        "content": message.content,
        "status": message.status,
        "district_filter": message.district_filter,
        "created_at": message.created_at.isoformat(),
    }


def _build_session_title(question: str) -> str:
    title = question.strip()
    if len(title) > 30:
        return f"{title[:30]}..."
    return title


def reserve_chat_turn(
    db: Session,
    *,
    user_id: int,
    session_id: int | None,
    question: str,
    district: str | None,
) -> tuple[ChatSessionModel, MessageModel, MessageModel]:
    """Atomically reserve adjacent user/assistant positions for one chat turn."""
    try:
        locked_user = (
            db.query(UserModel)
            .filter(UserModel.id == user_id)
            .with_for_update()
            .first()
        )
        if locked_user is None:
            raise ChatSessionNotFoundError

        now = datetime.datetime.utcnow()
        window_start = now - datetime.timedelta(
            seconds=settings.CHAT_RATE_LIMIT_WINDOW_SECONDS
        )
        recent_request_count = (
            db.query(func.count(MessageModel.id))
            .join(
                ChatSessionModel,
                MessageModel.session_id == ChatSessionModel.id,
            )
            .filter(
                ChatSessionModel.user_id == user_id,
                MessageModel.role == "user",
                MessageModel.created_at >= window_start,
            )
            .scalar()
            or 0
        )
        if recent_request_count >= settings.CHAT_RATE_LIMIT_REQUESTS:
            raise ChatRateLimitExceededError(
                settings.CHAT_RATE_LIMIT_WINDOW_SECONDS
            )

        if session_id is None:
            session = ChatSessionModel(
                user_id=user_id,
                next_position=0,
            )
            db.add(session)
            db.flush()
        else:
            session = (
                db.query(ChatSessionModel)
                .filter(
                    ChatSessionModel.id == session_id,
                    ChatSessionModel.user_id == user_id,
                )
                .with_for_update()
                .first()
            )
            if session is None:
                raise ChatSessionNotFoundError

        base_position = session.next_position or 0
        session.next_position = base_position + 2

        if session.title == NEW_SESSION_TITLE:
            title = _build_session_title(question)
            if title:
                session.title = title

        turn_id = str(uuid4())
        user_message = MessageModel(
            session_id=session.id,
            turn_id=turn_id,
            position=base_position,
            role="user",
            content=question,
            status="completed",
            district_filter=district,
        )
        assistant_message = MessageModel(
            session_id=session.id,
            turn_id=turn_id,
            position=base_position + 1,
            role="assistant",
            content="",
            status="pending",
            district_filter=district,
        )
        db.add_all([user_message, assistant_message])
        db.commit()
        db.refresh(session)
        db.refresh(user_message)
        db.refresh(assistant_message)
        return session, user_message, assistant_message
    except Exception:
        db.rollback()
        raise


def get_recent_conversation(
    db: Session,
    *,
    user_id: int,
    session_id: int,
    before_position: int,
    max_turns: int = CHAT_HISTORY_MAX_TURNS,
    max_characters: int = CHAT_HISTORY_MAX_CHARACTERS,
) -> list[dict[str, str]]:
    """Return recent complete turns in chronological order."""
    if max_turns <= 0 or max_characters <= 0:
        return []

    complete_turn_rows = (
        db.query(MessageModel.turn_id)
        .join(
            ChatSessionModel,
            MessageModel.session_id == ChatSessionModel.id,
        )
        .filter(
            ChatSessionModel.user_id == user_id,
            MessageModel.session_id == session_id,
            MessageModel.position < before_position,
            MessageModel.status == "completed",
            MessageModel.role.in_(("user", "assistant")),
        )
        .group_by(MessageModel.turn_id)
        .having(func.count(MessageModel.id) == 2)
        .order_by(func.max(MessageModel.position).desc())
        .limit(max_turns)
        .all()
    )
    turn_ids = [row[0] for row in complete_turn_rows]
    if not turn_ids:
        return []

    messages = (
        db.query(MessageModel)
        .join(
            ChatSessionModel,
            MessageModel.session_id == ChatSessionModel.id,
        )
        .filter(
            ChatSessionModel.user_id == user_id,
            MessageModel.session_id == session_id,
            MessageModel.turn_id.in_(turn_ids),
            MessageModel.status == "completed",
        )
        .order_by(MessageModel.position.asc())
        .all()
    )
    messages_by_turn = {}
    for message in messages:
        messages_by_turn.setdefault(message.turn_id, []).append(message)

    selected_messages = []
    used_characters = 0
    for turn_id in turn_ids:
        turn_messages = messages_by_turn.get(turn_id, [])
        turn_contents = [
            message.content.strip()
            for message in turn_messages
        ]
        if len(turn_messages) != 2 or not all(turn_contents):
            continue
        turn_characters = sum(len(content) for content in turn_contents)
        if used_characters + turn_characters > max_characters:
            break

        selected_messages.extend(turn_messages)
        used_characters += turn_characters

    selected_messages.sort(key=lambda message: message.position)
    return [
        {
            "role": message.role,
            "content": message.content.strip(),
        }
        for message in selected_messages
        if message.content.strip()
    ]


def update_assistant_message(
    db: Session,
    *,
    user_id: int,
    session_id: int,
    assistant_message_id: int,
    turn_id: str,
    content: str,
    status: str,
) -> MessageModel:
    if status not in {"completed", "error"}:
        raise ValueError("Trạng thái assistant phải là completed hoặc error.")

    try:
        assistant_message = (
            db.query(MessageModel)
            .join(
                ChatSessionModel,
                MessageModel.session_id == ChatSessionModel.id,
            )
            .filter(
                ChatSessionModel.user_id == user_id,
                MessageModel.session_id == session_id,
                MessageModel.id == assistant_message_id,
                MessageModel.turn_id == turn_id,
                MessageModel.role == "assistant",
                MessageModel.status == "pending",
            )
            .with_for_update()
            .first()
        )
        if assistant_message is None:
            raise AssistantMessageNotFoundError

        assistant_message.content = content
        assistant_message.status = status
        db.commit()
        db.refresh(assistant_message)
        return assistant_message
    except Exception:
        db.rollback()
        raise


def update_assistant_message_task(
    *,
    user_id: int,
    session_id: int,
    assistant_message_id: int,
    turn_id: str,
    content: str,
    status: str,
) -> dict:
    """Update a reserved assistant row using a session independent of the request."""
    db = SessionLocal()
    try:
        assistant_message = update_assistant_message(
            db,
            user_id=user_id,
            session_id=session_id,
            assistant_message_id=assistant_message_id,
            turn_id=turn_id,
            content=content,
            status=status,
        )
        return message_to_payload(assistant_message)
    finally:
        db.close()
