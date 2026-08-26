"""Add verified personalized learning plans.

Revision ID: 20260826_0007
Revises: 20260826_0006
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_0007"
down_revision: Union[str, None] = "20260826_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("course_version", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PROPOSED", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("verification_critique", sa.Text(), nullable=False),
        sa.Column("agent_trace_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_learning_plan_revision_positive",
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED', 'ACTIVE', 'REPLACED', 'COMPLETED')",
            name="ck_learning_plan_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_plans_id", "learning_plans", ["id"], unique=False)
    op.create_index(
        "ix_learning_plans_plan_id",
        "learning_plans",
        ["plan_id"],
        unique=True,
    )
    op.create_index(
        "ix_learning_plans_user_id",
        "learning_plans",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_learning_plan_user_course_status",
        "learning_plans",
        ["user_id", "course_id", "course_version", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learning_plan_user_course_status",
        table_name="learning_plans",
    )
    op.drop_index("ix_learning_plans_user_id", table_name="learning_plans")
    op.drop_index("ix_learning_plans_plan_id", table_name="learning_plans")
    op.drop_index("ix_learning_plans_id", table_name="learning_plans")
    op.drop_table("learning_plans")
