"""Normalize chat messages and enforce P0 ownership/order invariants.

Each legacy question/answer exchange becomes two ordered rows sharing one
turn_id. The old row keeps the user message ID; the assistant receives a new
sequence ID. The migration is transactional on PostgreSQL.

Revision ID: 20260727_0002
Revises: 20260727_0001
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0002"
down_revision: Union[str, None] = "20260727_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _column_names(table_name: str) -> set[str]:
    return {
        column["name"] for column in _inspector().get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in _inspector().get_indexes(table_name)
        if index.get("name")
    }


def _unique_names(table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in _inspector().get_unique_constraints(table_name)
        if constraint.get("name")
    }


def _check_names(table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in _inspector().get_check_constraints(table_name)
        if constraint.get("name")
    }


def _replace_message_session_fk(ondelete: str | None) -> None:
    for foreign_key in _inspector().get_foreign_keys("messages"):
        if foreign_key.get("constrained_columns") == ["session_id"]:
            name = foreign_key.get("name")
            if not name:
                raise RuntimeError(
                    "Không xác định được tên FK messages.session_id để migrate an toàn."
                )
            op.drop_constraint(name, "messages", type_="foreignkey")

    op.create_foreign_key(
        "fk_messages_session_id_chat_sessions",
        "messages",
        "chat_sessions",
        ["session_id"],
        ["id"],
        ondelete=ondelete,
    )


def _ensure_index(name: str, table: str, columns: list[str]) -> None:
    if name not in _index_names(table):
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Migration P0 được thiết kế và kiểm chứng cho PostgreSQL."
        )

    session_columns = _column_names("chat_sessions")
    if "next_position" not in session_columns:
        op.add_column(
            "chat_sessions",
            sa.Column("next_position", sa.Integer(), nullable=True),
        )

    message_columns = _column_names("messages")
    new_columns = {
        "turn_id": sa.Column("turn_id", sa.String(length=36), nullable=True),
        "position": sa.Column("position", sa.Integer(), nullable=True),
        "role": sa.Column("role", sa.String(length=20), nullable=True),
        "content": sa.Column("content", sa.Text(), nullable=True),
        "status": sa.Column("status", sa.String(length=20), nullable=True),
    }
    for column_name, column in new_columns.items():
        if column_name not in message_columns:
            op.add_column("messages", column)

    op.execute(
        "UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
    )
    op.execute(
        """
        UPDATE chat_sessions
        SET title = 'Cuộc trò chuyện mới'
        WHERE title IS NULL OR btrim(title) = ''
        """
    )
    op.execute(
        """
        UPDATE chat_sessions
        SET created_at = CURRENT_TIMESTAMP
        WHERE created_at IS NULL
        """
    )
    op.execute(
        "UPDATE messages SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
    )

    message_columns = _column_names("messages")
    is_legacy = {"question", "answer"} <= message_columns
    if is_legacy:
        op.alter_column(
            "messages",
            "question",
            existing_type=sa.Text(),
            nullable=True,
        )
        op.alter_column(
            "messages",
            "answer",
            existing_type=sa.Text(),
            nullable=True,
        )

        op.execute(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY session_id
                        ORDER BY created_at ASC, id ASC
                    ) - 1 AS turn_number
                FROM messages
            )
            UPDATE messages AS message
            SET
                turn_id =
                    substr(md5('legacy-message-' || message.id::text), 1, 8)
                    || '-' || substr(md5('legacy-message-' || message.id::text), 9, 4)
                    || '-' || substr(md5('legacy-message-' || message.id::text), 13, 4)
                    || '-' || substr(md5('legacy-message-' || message.id::text), 17, 4)
                    || '-' || substr(md5('legacy-message-' || message.id::text), 21, 12),
                position = ranked.turn_number * 2,
                role = 'user',
                content = COALESCE(message.question, ''),
                status = 'completed'
            FROM ranked
            WHERE message.id = ranked.id
            """
        )

        op.execute(
            """
            INSERT INTO messages (
                session_id,
                turn_id,
                position,
                role,
                content,
                status,
                district_filter,
                created_at,
                question,
                answer
            )
            SELECT
                session_id,
                turn_id,
                position + 1,
                'assistant',
                COALESCE(answer, ''),
                'completed',
                district_filter,
                created_at,
                NULL,
                NULL
            FROM messages
            WHERE role = 'user'
            ORDER BY session_id, position
            """
        )
    else:
        missing_values = bind.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE turn_id IS NULL
                   OR position IS NULL
                   OR role IS NULL
                   OR content IS NULL
                   OR status IS NULL
                """
            )
        ).scalar_one()
        if missing_values:
            raise RuntimeError(
                "Schema messages đã ở dạng P0 nhưng có dữ liệu NULL; "
                "migration dừng để tránh đoán sai nội dung."
            )

    op.execute(
        """
        UPDATE chat_sessions AS session
        SET next_position = COALESCE(
            (
                SELECT MAX(message.position) + 1
                FROM messages AS message
                WHERE message.session_id = session.id
            ),
            0
        )
        """
    )

    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "chat_sessions",
        "title",
        existing_type=sa.String(),
        nullable=False,
        server_default="Cuộc trò chuyện mới",
    )
    op.alter_column(
        "chat_sessions",
        "next_position",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )
    op.alter_column(
        "chat_sessions",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "messages",
        "turn_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.alter_column(
        "messages",
        "position",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "messages",
        "role",
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.alter_column(
        "messages",
        "content",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "messages",
        "status",
        existing_type=sa.String(length=20),
        nullable=False,
        server_default="pending",
    )
    op.alter_column(
        "messages",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    if is_legacy:
        op.drop_column("messages", "answer")
        op.drop_column("messages", "question")

    _replace_message_session_fk("CASCADE")

    unique_names = _unique_names("messages")
    if "uq_messages_session_position" not in unique_names:
        op.create_unique_constraint(
            "uq_messages_session_position",
            "messages",
            ["session_id", "position"],
        )
    if "uq_messages_session_turn_role" not in unique_names:
        op.create_unique_constraint(
            "uq_messages_session_turn_role",
            "messages",
            ["session_id", "turn_id", "role"],
        )

    check_names = _check_names("messages")
    if "ck_messages_position_nonnegative" not in check_names:
        op.create_check_constraint(
            "ck_messages_position_nonnegative",
            "messages",
            "position >= 0",
        )
    if "ck_messages_role" not in check_names:
        op.create_check_constraint(
            "ck_messages_role",
            "messages",
            "role IN ('user', 'assistant')",
        )
    if "ck_messages_status" not in check_names:
        op.create_check_constraint(
            "ck_messages_status",
            "messages",
            "status IN ('pending', 'completed', 'error')",
        )

    if (
        "ck_chat_sessions_next_position_nonnegative"
        not in _check_names("chat_sessions")
    ):
        op.create_check_constraint(
            "ck_chat_sessions_next_position_nonnegative",
            "chat_sessions",
            "next_position >= 0",
        )

    _ensure_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    _ensure_index("ix_messages_session_id", "messages", ["session_id"])
    _ensure_index("ix_messages_turn_id", "messages", ["turn_id"])

    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('messages', 'id'),
            COALESCE((SELECT MAX(id) FROM messages), 1),
            EXISTS(SELECT 1 FROM messages)
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Downgrade P0 chỉ hỗ trợ PostgreSQL.")

    for name in (
        "ck_messages_position_nonnegative",
        "ck_messages_role",
        "ck_messages_status",
    ):
        if name in _check_names("messages"):
            op.drop_constraint(name, "messages", type_="check")

    if (
        "ck_chat_sessions_next_position_nonnegative"
        in _check_names("chat_sessions")
    ):
        op.drop_constraint(
            "ck_chat_sessions_next_position_nonnegative",
            "chat_sessions",
            type_="check",
        )

    for name in (
        "uq_messages_session_position",
        "uq_messages_session_turn_role",
    ):
        if name in _unique_names("messages"):
            op.drop_constraint(name, "messages", type_="unique")

    op.add_column(
        "messages",
        sa.Column("question", sa.Text(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("answer", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE messages AS user_message
        SET
            question = user_message.content,
            answer = COALESCE(
                (
                    SELECT assistant_message.content
                    FROM messages AS assistant_message
                    WHERE assistant_message.session_id = user_message.session_id
                      AND assistant_message.turn_id = user_message.turn_id
                      AND assistant_message.role = 'assistant'
                    ORDER BY assistant_message.position, assistant_message.id
                    LIMIT 1
                ),
                ''
            )
        WHERE user_message.role = 'user'
        """
    )
    op.execute("DELETE FROM messages WHERE role <> 'user'")
    op.alter_column(
        "messages",
        "question",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "messages",
        "answer",
        existing_type=sa.Text(),
        nullable=False,
    )

    _replace_message_session_fk(None)

    for index_name in ("ix_messages_turn_id", "ix_messages_session_id"):
        if index_name in _index_names("messages"):
            op.drop_index(index_name, table_name="messages")
    if "ix_chat_sessions_user_id" in _index_names("chat_sessions"):
        op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")

    for column_name in ("status", "content", "role", "position", "turn_id"):
        op.drop_column("messages", column_name)
    op.drop_column("chat_sessions", "next_position")
