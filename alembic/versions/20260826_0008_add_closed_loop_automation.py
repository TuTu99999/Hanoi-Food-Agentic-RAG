"""Add closed-loop learning events and plan revision metadata.

Revision ID: 20260826_0008
Revises: 20260826_0007
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_0008"
down_revision: Union[str, None] = "20260826_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "learning_plans",
        sa.Column(
            "proposal_kind",
            sa.String(length=20),
            server_default="INITIAL",
            nullable=False,
        ),
    )
    op.add_column(
        "learning_plans",
        sa.Column("parent_plan_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "learning_plans",
        sa.Column("trigger_event_id", sa.String(length=36), nullable=True),
    )
    op.create_check_constraint(
        "ck_learning_plan_proposal_kind",
        "learning_plans",
        "proposal_kind IN ('INITIAL', 'REPLAN')",
    )
    op.create_index(
        "ix_learning_plans_parent_plan_id",
        "learning_plans",
        ["parent_plan_id"],
        unique=False,
    )
    op.create_index(
        "ix_learning_plans_trigger_event_id",
        "learning_plans",
        ["trigger_event_id"],
        unique=False,
    )

    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("course_version", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("aggregate_type", sa.String(length=32), nullable=False),
        sa.Column("aggregate_id", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('MASTERY_UPDATED', 'REPLAN_REQUIRED', "
            "'PLAN_PROPOSED', 'PLAN_APPROVED')",
            name="ck_learning_event_type",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_type",
            "correlation_id",
            name="uq_learning_event_type_correlation",
        ),
    )
    op.create_index("ix_learning_events_id", "learning_events", ["id"])
    op.create_index(
        "ix_learning_events_event_id",
        "learning_events",
        ["event_id"],
        unique=True,
    )
    op.create_index(
        "ix_learning_events_user_id",
        "learning_events",
        ["user_id"],
    )
    op.create_index(
        "ix_learning_event_user_course_created",
        "learning_events",
        ["user_id", "course_id", "course_version", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learning_event_user_course_created",
        table_name="learning_events",
    )
    op.drop_index("ix_learning_events_user_id", table_name="learning_events")
    op.drop_index("ix_learning_events_event_id", table_name="learning_events")
    op.drop_index("ix_learning_events_id", table_name="learning_events")
    op.drop_table("learning_events")

    op.drop_index(
        "ix_learning_plans_trigger_event_id",
        table_name="learning_plans",
    )
    op.drop_index(
        "ix_learning_plans_parent_plan_id",
        table_name="learning_plans",
    )
    op.drop_constraint(
        "ck_learning_plan_proposal_kind",
        "learning_plans",
        type_="check",
    )
    op.drop_column("learning_plans", "trigger_event_id")
    op.drop_column("learning_plans", "parent_plan_id")
    op.drop_column("learning_plans", "proposal_kind")
