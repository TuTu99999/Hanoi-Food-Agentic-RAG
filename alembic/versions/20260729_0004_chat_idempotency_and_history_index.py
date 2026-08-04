"""Add chat idempotency and history pagination support.

Revision ID: 20260729_0004
Revises: 20260729_0003
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0004"
down_revision: Union[str, None] = "20260729_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "client_request_id",
            sa.String(length=36),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_messages_client_request_id",
        "messages",
        ["client_request_id"],
    )
    op.create_index(
        "ix_chat_sessions_user_id_id",
        "chat_sessions",
        ["user_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_sessions_user_id_id",
        table_name="chat_sessions",
    )
    op.drop_constraint(
        "uq_messages_client_request_id",
        "messages",
        type_="unique",
    )
    op.drop_column("messages", "client_request_id")
