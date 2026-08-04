import datetime
import hashlib
import hmac
import math
from dataclasses import dataclass

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from core.config import settings
from database.connection import SessionLocal
from database.models import RateLimitBucketModel


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


def _hash_identifier(scope: str, identifier: str) -> str:
    message = f"{scope}:{identifier}".encode("utf-8")
    secret = settings.JWT_SECRET_KEY.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _utc_datetime(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def consume_rate_limit(
    db: Session,
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
    commit: bool = True,
) -> RateLimitResult:
    """Atomically consume one database-backed fixed-window rate-limit slot."""
    if not scope or len(scope) > 64:
        raise ValueError("Rate-limit scope must contain 1 to 64 characters.")
    if not identifier:
        raise ValueError("Rate-limit identifier must not be empty.")
    if limit <= 0 or window_seconds <= 0:
        raise ValueError("Rate-limit values must be greater than zero.")

    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(seconds=window_seconds)
    identifier_hash = _hash_identifier(scope, identifier)
    dialect_name = db.get_bind().dialect.name

    if dialect_name == "postgresql":
        insert_statement = postgresql_insert(RateLimitBucketModel)
    elif dialect_name == "sqlite":
        insert_statement = sqlite_insert(RateLimitBucketModel)
    else:
        raise RuntimeError(
            "The rate limiter supports PostgreSQL and SQLite databases."
        )

    bucket_expired = RateLimitBucketModel.expires_at <= now
    statement = (
        insert_statement
        .values(
            scope=scope,
            identifier_hash=identifier_hash,
            request_count=1,
            expires_at=expires_at,
        )
        .on_conflict_do_update(
            index_elements=["scope", "identifier_hash"],
            set_={
                "request_count": case(
                    (bucket_expired, 1),
                    else_=RateLimitBucketModel.request_count + 1,
                ),
                "expires_at": case(
                    (bucket_expired, expires_at),
                    else_=RateLimitBucketModel.expires_at,
                ),
            },
        )
        .returning(
            RateLimitBucketModel.request_count,
            RateLimitBucketModel.expires_at,
        )
    )

    request_count, bucket_expires_at = db.execute(statement).one()
    if commit:
        db.commit()
    else:
        db.flush()

    retry_after = max(
        1,
        math.ceil((_utc_datetime(bucket_expires_at) - now).total_seconds()),
    )
    return RateLimitResult(
        allowed=request_count <= limit,
        retry_after_seconds=retry_after,
    )


def cleanup_expired_rate_limits_task() -> int:
    """Delete expired buckets once during application startup."""
    db = SessionLocal()
    try:
        deleted_count = (
            db.query(RateLimitBucketModel)
            .filter(
                RateLimitBucketModel.expires_at
                <= datetime.datetime.now(datetime.timezone.utc)
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted_count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
