import contextvars
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
request_id_context = contextvars.ContextVar(
    "request_id",
    default="-",
)
session_id_context = contextvars.ContextVar(
    "session_id",
    default="-",
)


def get_request_id() -> str:
    return request_id_context.get()


def bind_session_id(session_id: int | str) -> None:
    session_id_context.set(str(session_id))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(
                record,
                "request_id",
                request_id_context.get(),
            ),
            "session_id": getattr(
                record,
                "session_id",
                session_id_context.get(),
            ),
        }

        for field_name in (
            "method",
            "path",
            "route",
            "status_code",
            "duration_ms",
            "query_length",
            "result_count",
            "district",
            "result_index",
            "semantic_score",
            "ranking_score",
            "intent",
            "router_source",
            "router_confidence",
            "evidence_reason",
            "retry_count",
            "branch_counts",
            "exact_shortcut_used",
            "service",
        ):
            if hasattr(record, field_name):
                payload[field_name] = getattr(record, field_name)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    for logger_name in ("alembic", "httpcore", "httpx"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    if any(
        getattr(handler, "_rag_json_handler", False)
        for handler in root_logger.handlers
    ):
        root_logger.setLevel(level)
        return

    handler = logging.StreamHandler()
    handler._rag_json_handler = True
    handler.setFormatter(JsonFormatter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def _read_request_id(scope: dict) -> str:
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-request-id":
            candidate = value.decode("latin-1").strip()
            if REQUEST_ID_PATTERN.fullmatch(candidate):
                return candidate
            break
    return str(uuid.uuid4())


class RequestContextMiddleware:
    """Keep request context active until the complete SSE body is sent."""

    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger("http.request")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _read_request_id(scope)
        request_token = request_id_context.set(request_id)
        session_token = session_id_context.set("-")
        started_at = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message):
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Process-Time"] = (
                    f"{time.perf_counter() - started_at:.4f}s"
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            self.logger.exception("http.request.unhandled_error")
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Hệ thống đang gặp lỗi. Vui lòng thử lại sau.",
                    "request_id": request_id,
                },
            )
            await response(scope, receive, send_with_request_id)
        finally:
            duration_ms = round(
                (time.perf_counter() - started_at) * 1000,
                2,
            )
            route = scope.get("route")
            route_path = getattr(route, "path", scope.get("path", ""))
            self.logger.info(
                "http.request.completed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "route": route_path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            session_id_context.reset(session_token)
            request_id_context.reset(request_token)
