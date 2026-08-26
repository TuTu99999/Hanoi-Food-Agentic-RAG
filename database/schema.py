from sqlalchemy import inspect, text


EXPECTED_DATABASE_REVISION = "20260826_0008"


def verify_database_revision(engine, *, schema_check: bool = True) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        if not schema_check:
            return

        inspector = inspect(connection)
        if "alembic_version" not in inspector.get_table_names():
            raise RuntimeError(
                "Database chưa được quản lý bằng Alembic. "
                "Hãy backup database rồi chạy: alembic upgrade head"
            )

        revisions = {
            row[0]
            for row in connection.execute(
                text("SELECT version_num FROM alembic_version")
            )
        }
        if revisions != {EXPECTED_DATABASE_REVISION}:
            current = ", ".join(sorted(revisions)) or "chưa có revision"
            raise RuntimeError(
                "Database schema chưa đúng phiên bản. "
                f"Hiện tại: {current}; yêu cầu: {EXPECTED_DATABASE_REVISION}. "
                "Hãy chạy: alembic upgrade head"
            )


__all__ = ["EXPECTED_DATABASE_REVISION", "verify_database_revision"]
