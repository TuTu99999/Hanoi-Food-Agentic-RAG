import os
from pathlib import Path
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from core.config import settings


RUN_POSTGRES_MIGRATION_TEST = (
    os.getenv("RUN_P0_POSTGRES_MIGRATION_TEST", "").lower()
    in {"1", "true", "yes"}
)


@unittest.skipUnless(
    RUN_POSTGRES_MIGRATION_TEST,
    "Set RUN_P0_POSTGRES_MIGRATION_TEST=1 to run isolated PostgreSQL migration test.",
)
class P0PostgresMigrationTests(unittest.TestCase):
    def test_legacy_backfill_order_constraints_sequence_and_cascade(self):
        original_database_url = settings.DATABASE_URL
        admin_engine = sa.create_engine(original_database_url, pool_pre_ping=True)
        schema_name = f"p0_migration_test_{uuid4().hex}"
        quoted_schema = admin_engine.dialect.identifier_preparer.quote(schema_name)

        base_url = make_url(original_database_url)
        query = dict(base_url.query)
        query["options"] = f"-csearch_path={schema_name}"
        test_url = base_url.set(query=query)
        test_database_url = test_url.render_as_string(hide_password=False)
        test_engine = None

        repository_root = Path(__file__).resolve().parents[1]
        alembic_config = Config(str(repository_root / "alembic.ini"))

        try:
            with admin_engine.begin() as connection:
                connection.execute(sa.text(f"CREATE SCHEMA {quoted_schema}"))

            settings.DATABASE_URL = test_database_url
            command.upgrade(alembic_config, "20260727_0001")

            test_engine = sa.create_engine(test_database_url, pool_pre_ping=True)
            shared_timestamp = "2026-07-27 08:00:00"
            with test_engine.begin() as connection:
                user_id = connection.execute(
                    sa.text(
                        """
                        INSERT INTO users (username, hashed_password, created_at)
                        VALUES (:username, :password, :created_at)
                        RETURNING id
                        """
                    ),
                    {
                        "username": "legacy-user",
                        "password": "legacy-hash",
                        "created_at": shared_timestamp,
                    },
                ).scalar_one()
                first_session_id = connection.execute(
                    sa.text(
                        """
                        INSERT INTO chat_sessions (user_id, title, created_at)
                        VALUES (:user_id, :title, :created_at)
                        RETURNING id
                        """
                    ),
                    {
                        "user_id": user_id,
                        "title": "Phiên có dữ liệu cũ",
                        "created_at": shared_timestamp,
                    },
                ).scalar_one()
                second_session_id = connection.execute(
                    sa.text(
                        """
                        INSERT INTO chat_sessions (user_id, title, created_at)
                        VALUES (:user_id, NULL, NULL)
                        RETURNING id
                        """
                    ),
                    {"user_id": user_id},
                ).scalar_one()
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO messages (
                            session_id,
                            question,
                            answer,
                            district_filter,
                            created_at
                        )
                        VALUES
                            (:session_id, :q1, :a1, :district, :created_at),
                            (:session_id, :q2, :a2, NULL, :created_at),
                            (:second_session_id, :q3, :a3, NULL, NULL)
                        """
                    ),
                    {
                        "session_id": first_session_id,
                        "second_session_id": second_session_id,
                        "q1": "Phở **ngon** ở đâu?\nCho mình địa chỉ.",
                        "a1": "Ở phố cổ Hà Nội.",
                        "q2": "Giá bao nhiêu?",
                        "a2": "",
                        "q3": "Đi Hồ Gươm",
                        "a3": "Bạn có thể đi bộ quanh hồ.",
                        "district": "Hoàn Kiếm",
                        "created_at": shared_timestamp,
                    },
                )

            command.upgrade(alembic_config, "head")
            command.check(alembic_config)

            with test_engine.begin() as connection:
                rows = connection.execute(
                    sa.text(
                        """
                        SELECT
                            session_id,
                            turn_id,
                            position,
                            role,
                            content,
                            status,
                            district_filter
                        FROM messages
                        ORDER BY session_id, position, id
                        """
                    )
                ).mappings().all()
                self.assertEqual(len(rows), 6)

                first_session_rows = [
                    row for row in rows if row["session_id"] == first_session_id
                ]
                self.assertEqual(
                    [row["role"] for row in first_session_rows],
                    ["user", "assistant", "user", "assistant"],
                )
                self.assertEqual(
                    [row["position"] for row in first_session_rows],
                    [0, 1, 2, 3],
                )
                self.assertEqual(
                    first_session_rows[0]["content"],
                    "Phở **ngon** ở đâu?\nCho mình địa chỉ.",
                )
                self.assertEqual(
                    first_session_rows[1]["content"],
                    "Ở phố cổ Hà Nội.",
                )
                self.assertEqual(first_session_rows[3]["content"], "")
                self.assertEqual(
                    first_session_rows[0]["turn_id"],
                    first_session_rows[1]["turn_id"],
                )
                self.assertNotEqual(
                    first_session_rows[0]["turn_id"],
                    first_session_rows[2]["turn_id"],
                )
                self.assertTrue(
                    all(row["status"] == "completed" for row in rows)
                )

                next_positions = dict(
                    connection.execute(
                        sa.text(
                            "SELECT id, next_position FROM chat_sessions ORDER BY id"
                        )
                    ).all()
                )
                self.assertEqual(next_positions[first_session_id], 4)
                self.assertEqual(next_positions[second_session_id], 2)

                max_existing_id = connection.execute(
                    sa.text("SELECT MAX(id) FROM messages")
                ).scalar_one()
                inserted_id = connection.execute(
                    sa.text(
                        """
                        INSERT INTO messages (
                            session_id,
                            turn_id,
                            position,
                            role,
                            content,
                            status
                        )
                        VALUES (
                            :session_id,
                            :turn_id,
                            2,
                            'user',
                            'Tin nhắn mới',
                            'completed'
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "session_id": second_session_id,
                        "turn_id": str(uuid4()),
                    },
                ).scalar_one()
                self.assertGreater(inserted_id, max_existing_id)

                connection.execute(
                    sa.text("DELETE FROM chat_sessions WHERE id = :session_id"),
                    {"session_id": first_session_id},
                )
                remaining = connection.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM messages WHERE session_id = :session_id"
                    ),
                    {"session_id": first_session_id},
                ).scalar_one()
                self.assertEqual(remaining, 0)

            with self.assertRaises(sa.exc.IntegrityError):
                with test_engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            """
                            INSERT INTO messages (
                                session_id,
                                turn_id,
                                position,
                                role,
                                content,
                                status
                            )
                            VALUES (
                                :session_id,
                                :turn_id,
                                2,
                                'assistant',
                                'Trùng position',
                                'completed'
                            )
                            """
                        ),
                        {
                            "session_id": second_session_id,
                            "turn_id": str(uuid4()),
                        },
                    )
        finally:
            settings.DATABASE_URL = original_database_url
            if test_engine is not None:
                test_engine.dispose()
            with admin_engine.begin() as connection:
                connection.execute(
                    sa.text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE")
                )
            admin_engine.dispose()


if __name__ == "__main__":
    unittest.main()
