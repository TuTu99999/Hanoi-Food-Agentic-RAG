from prometheus_client import Counter, Gauge, Histogram


HTTP_REQUESTS_TOTAL = Counter(
    "hanoi_food_http_requests_total",
    "Total HTTP requests handled by the API.",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "hanoi_food_http_request_duration_seconds",
    "Complete HTTP request duration, including SSE streams.",
    ("method", "route"),
    buckets=(
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2.5,
        5,
        10,
        20,
        30,
        60,
    ),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "hanoi_food_http_requests_in_progress",
    "HTTP requests currently being processed.",
    ("method",),
)
CHAT_STREAMS_TOTAL = Counter(
    "hanoi_food_chat_streams_total",
    "Total chat streams by terminal outcome.",
    ("outcome",),
)
for _stream_outcome in (
    "completed",
    "error",
    "timeout",
    "cancelled",
    "replayed",
    "replayed_error",
):
    CHAT_STREAMS_TOTAL.labels(outcome=_stream_outcome)


def request_started(method: str) -> None:
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()


def request_finished(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()
    HTTP_REQUESTS_TOTAL.labels(
        method=method,
        route=route,
        status_code=str(status_code),
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(
        method=method,
        route=route,
    ).observe(duration_seconds)


def chat_stream_finished(outcome: str) -> None:
    CHAT_STREAMS_TOTAL.labels(outcome=outcome).inc()
