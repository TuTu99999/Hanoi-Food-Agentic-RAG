"""Harden authentication and add persistent rate-limit buckets.

Revision ID: 20260729_0003
Revises: 20260727_0002
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0003"
down_revision: Union[str, None] = "20260727_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )

    op.create_table(
        "rate_limit_buckets",
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "request_count > 0",
            name="ck_rate_limit_buckets_request_count_positive",
        ),
        sa.PrimaryKeyConstraint("scope", "identifier_hash"),
    )
    op.create_index(
        "ix_rate_limit_buckets_expires_at",
        "rate_limit_buckets",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rate_limit_buckets_expires_at",
        table_name="rate_limit_buckets",
    )
    op.drop_table("rate_limit_buckets")
    op.drop_column("users", "token_version")
