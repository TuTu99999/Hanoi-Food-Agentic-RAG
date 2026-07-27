import asyncio
import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.config import settings
from database.connection import engine


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])


def check_postgresql() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def check_qdrant(rag_pipeline) -> None:
    rag_pipeline.check_retrieval_ready()


def check_llm(rag_pipeline) -> str:
    return rag_pipeline.llm_health_status()


async def _safe_check(
    service_name: str,
    operation,
    success_status: str,
) -> str:
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(operation),
            timeout=settings.HEALTHCHECK_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception(
            "Health check failed.",
            extra={"service": service_name},
        )
        return "unavailable"

    return result if isinstance(result, str) else success_status


@router.get("/live")
def live():
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request):
    rag_pipeline = getattr(request.app.state, "rag_pipeline", None)

    postgresql_task = _safe_check(
        "postgresql",
        check_postgresql,
        "ok",
    )
    if rag_pipeline is None:
        postgresql_status = await postgresql_task
        services = {
            "postgresql": postgresql_status,
            "qdrant": "unavailable",
            "llm": "unavailable",
        }
    else:
        postgresql_status, qdrant_status, llm_status = await asyncio.gather(
            postgresql_task,
            _safe_check(
                "qdrant",
                lambda: check_qdrant(rag_pipeline),
                "ok",
            ),
            _safe_check(
                "llm",
                lambda: check_llm(rag_pipeline),
                "configured",
            ),
        )
        services = {
            "postgresql": postgresql_status,
            "qdrant": qdrant_status,
            "llm": llm_status,
        }

    is_ready = services == {
        "postgresql": "ok",
        "qdrant": "ok",
        "llm": "configured",
    }
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "services": services,
    }
    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if is_ready
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=payload,
    )
