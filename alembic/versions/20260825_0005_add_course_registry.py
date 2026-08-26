"""Add the multi-course registry foundation.

Revision ID: 20260825_0005
Revises: 20260729_0004
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_0005"
down_revision: Union[str, None] = "20260729_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_content_manager",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "domain",
            sa.String(length=64),
            server_default="political_theory",
            nullable=False,
        ),
        sa.Column(
            "language",
            sa.String(length=10),
            server_default="vi",
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_courses_id", "courses", ["id"], unique=False)
    op.create_index(
        "ix_courses_course_id",
        "courses",
        ["course_id"],
        unique=True,
    )
    op.create_index(
        "ix_courses_created_by_user_id",
        "courses",
        ["created_by_user_id"],
        unique=False,
    )

    op.create_table(
        "course_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_pk", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("vector_alias", sa.String(length=160), nullable=False),
        sa.Column("graph_namespace", sa.String(length=160), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PROCESSING', 'REVIEW_REQUIRED', "
            "'VALIDATED', 'ACTIVE', 'ARCHIVED')",
            name="ck_course_versions_status",
        ),
        sa.ForeignKeyConstraint(
            ["course_pk"],
            ["courses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_pk",
            "version",
            name="uq_course_versions_course_version",
        ),
    )
    op.create_index(
        "ix_course_versions_id",
        "course_versions",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_course_versions_course_pk",
        "course_versions",
        ["course_pk"],
        unique=False,
    )
    op.create_index(
        "ix_course_versions_course_pk_status",
        "course_versions",
        ["course_pk", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_versions_course_pk_status",
        table_name="course_versions",
    )
    op.drop_index(
        "ix_course_versions_course_pk",
        table_name="course_versions",
    )
    op.drop_index("ix_course_versions_id", table_name="course_versions")
    op.drop_table("course_versions")

    op.drop_index(
        "ix_courses_created_by_user_id",
        table_name="courses",
    )
    op.drop_index("ix_courses_course_id", table_name="courses")
    op.drop_index("ix_courses_id", table_name="courses")
    op.drop_table("courses")
    op.drop_column("users", "is_content_manager")
