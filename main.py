import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from core.config import settings
from core.observability import (
    RequestContextMiddleware,
    configure_logging,
)
from core.security import NoStoreMiddleware, validate_csrf_request
from academic_agents.runtime import AcademicAgentRuntime
from database.connection import engine
from database.schema import (
    EXPECTED_DATABASE_REVISION,
    verify_database_revision as verify_schema_revision,
)
from rag.Rag import RAGPipeline
from routers import (
    academic_assistant,
    assessments,
    automation,
    auth,
    chat,
    courses,
    health,
    history,
    planning,
)
from services.rate_limit_service import cleanup_expired_rate_limits_task


configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

def verify_database_revision() -> None:
    verify_schema_revision(
        engine,
        schema_check=settings.DB_SCHEMA_CHECK,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    rag_pipeline = None
    academic_agent_runtime = None
    _app.state.rag_pipeline = None
    _app.state.academic_agent_runtime = None

    try:
        await asyncio.to_thread(verify_database_revision)
        deleted_buckets = await asyncio.to_thread(
            cleanup_expired_rate_limits_task
        )
        if deleted_buckets:
            logger.info(
                "Expired rate-limit buckets removed.",
                extra={"deleted_count": deleted_buckets},
            )
        rag_pipeline = RAGPipeline()
        await asyncio.to_thread(rag_pipeline.warmup)
        _app.state.rag_pipeline = rag_pipeline
        if settings.ACADEMIC_AGENT_ENABLED:
            academic_agent_runtime = AcademicAgentRuntime.from_settings(
                settings
            )
            _app.state.academic_agent_runtime = academic_agent_runtime
        logger.info("Application dependencies are ready.")
        yield
    finally:
        _app.state.rag_pipeline = None
        _app.state.academic_agent_runtime = None
        try:
            try:
                if academic_agent_runtime is not None:
                    await academic_agent_runtime.aclose()
            finally:
                if rag_pipeline is not None:
                    await rag_pipeline.aclose()
        finally:
            await asyncio.to_thread(engine.dispose)
        logger.info("Application dependencies were closed.")


app = FastAPI(
    title="Agentic AI Learning Assistant API",
    version="3.4.0",
    lifespan=lifespan,
    dependencies=[Depends(validate_csrf_request)],
)

# ==========================================
# 1. MIDDLEWARE
# ==========================================
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(settings.TRUSTED_HOSTS),
)
app.add_middleware(
    NoStoreMiddleware,
    path_prefixes=(
        "/api/auth",
        "/api/academic-assistant",
        "/api/chat",
        "/api/courses",
        "/api/history",
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID", "X-Process-Time"],
)
app.add_middleware(RequestContextMiddleware)

# ==========================================
# 2. REGISTER ROUTERS
# ==========================================
app.include_router(auth.router, prefix="/api")
app.include_router(academic_assistant.router, prefix="/api")
app.include_router(assessments.router, prefix="/api")
app.include_router(planning.router, prefix="/api")
app.include_router(automation.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(courses.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(health.router)


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/")
def root():
    return {"message": "Agentic AI Learning Assistant API"}
