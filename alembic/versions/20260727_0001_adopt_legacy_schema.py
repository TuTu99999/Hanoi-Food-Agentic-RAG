"""Adopt the schema previously created by SQLAlchemy create_all.

This baseline is safe for both an existing project database and a clean
database. Existing tables are validated and adopted; on a clean database the
legacy schema is created so the following P0 migration can transform it.

Revision ID: 20260727_0001
Revises:
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APPLICATION_TABLES = {
    "users",
    "chat_sessions",
    "messages",
    "foods",
    "restaurants",
    "travel_places",
    "hotels",
    "favorites",
}


def _validate_existing_schema(inspector: sa.Inspector) -> None:
    existing = set(inspector.get_table_names())
    present = existing & APPLICATION_TABLES
    if not present:
        return

    missing = APPLICATION_TABLES - existing
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise RuntimeError(
            "Database chứa schema ứng dụng chưa đầy đủ. "
            f"Thiếu các bảng: {missing_names}. Hãy phục hồi backup trước khi migrate."
        )

    message_columns = {
        column["name"] for column in inspector.get_columns("messages")
    }
    legacy_shape = {"question", "answer"} <= message_columns
    p0_shape = {"role", "content", "turn_id", "position", "status"} <= message_columns
    if not legacy_shape and not p0_shape:
        raise RuntimeError(
            "Bảng messages không khớp schema legacy hoặc P0 đã biết; "
            "migration dừng để tránh làm mất dữ liệu."
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _validate_existing_schema(inspector)

    if set(inspector.get_table_names()) & APPLICATION_TABLES:
        return

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "foods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_range", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_foods_id", "foods", ["id"], unique=False)
    op.create_index("ix_foods_name", "foods", ["name"], unique=False)

    op.create_table(
        "restaurants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("district", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("price_range", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_restaurants_id", "restaurants", ["id"], unique=False)
    op.create_index("ix_restaurants_name", "restaurants", ["name"], unique=False)
    op.create_index(
        "ix_restaurants_district",
        "restaurants",
        ["district"],
        unique=False,
    )

    op.create_table(
        "travel_places",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("district", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("best_time_to_visit", sa.String(), nullable=True),
        sa.Column("ticket_price", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_travel_places_id", "travel_places", ["id"], unique=False)
    op.create_index(
        "ix_travel_places_name",
        "travel_places",
        ["name"],
        unique=False,
    )
    op.create_index(
        "ix_travel_places_district",
        "travel_places",
        ["district"],
        unique=False,
    )

    op.create_table(
        "hotels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("district", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hotels_id", "hotels", ["id"], unique=False)
    op.create_index("ix_hotels_name", "hotels", ["name"], unique=False)
    op.create_index("ix_hotels_district", "hotels", ["district"], unique=False)

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_sessions_id",
        "chat_sessions",
        ["id"],
        unique=False,
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("district_filter", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_id", "messages", ["id"], unique=False)

    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("travel_place_id", sa.Integer(), nullable=True),
        sa.Column("hotel_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"]),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["travel_place_id"], ["travel_places.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_favorites_id", "favorites", ["id"], unique=False)


def downgrade() -> None:
    raise RuntimeError(
        "Baseline có thể đã adopt database tồn tại nên không tự động drop bảng. "
        "Khôi phục bằng backup nếu cần quay lại trước baseline."
    )
