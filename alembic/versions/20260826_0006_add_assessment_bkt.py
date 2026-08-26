"""Add adaptive assessment attempts and BKT mastery.

Revision ID: 20260826_0006
Revises: 20260825_0005
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_0006"
down_revision: Union[str, None] = "20260825_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learner_concept_masteries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("course_version", sa.String(length=32), nullable=False),
        sa.Column("concept_id", sa.String(length=100), nullable=False),
        sa.Column("concept_name", sa.String(length=300), nullable=False),
        sa.Column("mastery_probability", sa.Float(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correct_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_question_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "attempt_count >= 0 AND correct_count >= 0 "
            "AND correct_count <= attempt_count",
            name="ck_learner_mastery_counts",
        ),
        sa.CheckConstraint(
            "mastery_probability >= 0 AND mastery_probability <= 1",
            name="ck_learner_mastery_probability",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "course_id",
            "course_version",
            "concept_id",
            name="uq_learner_concept_mastery_scope",
        ),
    )
    op.create_index(
        "ix_learner_concept_masteries_id",
        "learner_concept_masteries",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_learner_concept_masteries_user_id",
        "learner_concept_masteries",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_learner_mastery_user_course_version",
        "learner_concept_masteries",
        ["user_id", "course_id", "course_version"],
        unique=False,
    )

    op.create_table(
        "assessment_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("course_version", sa.String(length=32), nullable=False),
        sa.Column("question_id", sa.String(length=100), nullable=False),
        sa.Column("concept_id", sa.String(length=100), nullable=False),
        sa.Column("concept_name", sa.String(length=300), nullable=False),
        sa.Column("question_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("selected_option_id", sa.String(length=10), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("mastery_before", sa.Float(), nullable=False),
        sa.Column("mastery_after", sa.Float(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "mastery_after IS NULL OR (mastery_after >= 0 AND mastery_after <= 1)",
            name="ck_assessment_attempt_mastery_after",
        ),
        sa.CheckConstraint(
            "mastery_before >= 0 AND mastery_before <= 1",
            name="ck_assessment_attempt_mastery_before",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMPLETED')",
            name="ck_assessment_attempt_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assessment_attempts_attempt_id",
        "assessment_attempts",
        ["attempt_id"],
        unique=True,
    )
    op.create_index(
        "ix_assessment_attempts_id",
        "assessment_attempts",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_attempts_user_id",
        "assessment_attempts",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_attempt_user_course_version",
        "assessment_attempts",
        ["user_id", "course_id", "course_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assessment_attempt_user_course_version", table_name="assessment_attempts")
    op.drop_index("ix_assessment_attempts_user_id", table_name="assessment_attempts")
    op.drop_index("ix_assessment_attempts_id", table_name="assessment_attempts")
    op.drop_index("ix_assessment_attempts_attempt_id", table_name="assessment_attempts")
    op.drop_table("assessment_attempts")

    op.drop_index(
        "ix_learner_mastery_user_course_version",
        table_name="learner_concept_masteries",
    )
    op.drop_index(
        "ix_learner_concept_masteries_user_id",
        table_name="learner_concept_masteries",
    )
    op.drop_index(
        "ix_learner_concept_masteries_id",
        table_name="learner_concept_masteries",
    )
    op.drop_table("learner_concept_masteries")
