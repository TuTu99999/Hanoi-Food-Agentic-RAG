from sqlalchemy.orm import Session

from core.config import settings
from services.rate_limit_service import consume_rate_limit


class AcademicAgentLimitError(RuntimeError):
    def __init__(self, retry_after_seconds: int):
        super().__init__("Academic agent usage limit exceeded.")
        self.retry_after_seconds = retry_after_seconds


def consume_academic_assessment_limit(db: Session, *, user_id: int) -> None:
    """Rate-limit deterministic assessment actions without charging LLM budget."""

    try:
        result = consume_rate_limit(
            db,
            scope="academic_assessment.user",
            identifier=str(user_id),
            limit=settings.CHAT_RATE_LIMIT_REQUESTS,
            window_seconds=settings.CHAT_RATE_LIMIT_WINDOW_SECONDS,
        )
        if not result.allowed:
            raise AcademicAgentLimitError(result.retry_after_seconds)
    except AcademicAgentLimitError:
        raise
    except Exception:
        db.rollback()
        raise


def consume_academic_planning_limit(db: Session, *, user_id: int) -> None:
    """Rate-limit deterministic planning without charging LLM budget."""

    try:
        result = consume_rate_limit(
            db,
            scope="academic_planning.user",
            identifier=str(user_id),
            limit=settings.CHAT_RATE_LIMIT_REQUESTS,
            window_seconds=settings.CHAT_RATE_LIMIT_WINDOW_SECONDS,
        )
        if not result.allowed:
            raise AcademicAgentLimitError(result.retry_after_seconds)
    except AcademicAgentLimitError:
        raise
    except Exception:
        db.rollback()
        raise


def consume_academic_agent_budget(db: Session, *, user_id: int) -> None:
    """Consume one authenticated request and one shared LLM budget slot."""

    try:
        burst_limit = consume_rate_limit(
            db,
            scope="academic_agent.burst.user",
            identifier=str(user_id),
            limit=settings.CHAT_RATE_LIMIT_REQUESTS,
            window_seconds=settings.CHAT_RATE_LIMIT_WINDOW_SECONDS,
            commit=False,
        )
        if not burst_limit.allowed:
            db.commit()
            raise AcademicAgentLimitError(burst_limit.retry_after_seconds)

        user_budget = consume_rate_limit(
            db,
            scope="llm.budget.user",
            identifier=str(user_id),
            limit=settings.LLM_DAILY_USER_REQUESTS,
            window_seconds=settings.LLM_BUDGET_WINDOW_SECONDS,
            commit=False,
        )
        if not user_budget.allowed:
            db.commit()
            raise AcademicAgentLimitError(user_budget.retry_after_seconds)

        global_budget = consume_rate_limit(
            db,
            scope="llm.budget.global",
            identifier="global",
            limit=settings.LLM_DAILY_GLOBAL_REQUESTS,
            window_seconds=settings.LLM_BUDGET_WINDOW_SECONDS,
            commit=False,
        )
        db.commit()
        if not global_budget.allowed:
            raise AcademicAgentLimitError(global_budget.retry_after_seconds)
    except AcademicAgentLimitError:
        raise
    except Exception:
        db.rollback()
        raise
