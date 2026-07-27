import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from core.config import settings
from core.observability import (
    RequestContextMiddleware,
    configure_logging,
)
from core.security import validate_csrf_request
from database.connection import engine
from rag.Rag import RAGPipeline
from routers import auth, chat, health, history


configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

EXPECTED_DATABASE_REVISION = "20260727_0002"


def verify_database_revision() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        if not settings.DB_SCHEMA_CHECK:
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    rag_pipeline = None
    _app.state.rag_pipeline = None

    try:
        await asyncio.to_thread(verify_database_revision)
        rag_pipeline = RAGPipeline()
        await asyncio.to_thread(rag_pipeline.warmup)
        _app.state.rag_pipeline = rag_pipeline
        logger.info("Application dependencies are ready.")
        yield
    finally:
        _app.state.rag_pipeline = None
        try:
            if rag_pipeline is not None:
                await rag_pipeline.aclose()
        finally:
            await asyncio.to_thread(engine.dispose)
        logger.info("Application dependencies were closed.")


app = FastAPI(
    title="Hà Nội Travel & Food RAG API",
    version="2.0.0",
    lifespan=lifespan,
    dependencies=[Depends(validate_csrf_request)],
)

# ==========================================
# 1. MIDDLEWARE
# ==========================================
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
app.include_router(chat.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(health.router)

@app.get("/")
def root():
    return {"message": "Chào mừng đến với Hà Nội Travel & Food RAG API!"}
