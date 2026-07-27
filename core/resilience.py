import asyncio
import random
import threading
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    """Small thread-safe circuit breaker for one external service."""

    def __init__(
        self,
        failure_threshold: int,
        reset_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._failure_count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._clock() - self._opened_at >= self.reset_seconds:
                return "half_open"
            return "open"

    def before_call(self) -> None:
        if self.state == "open":
            raise CircuitOpenError(
                "External service circuit is temporarily open."
            )

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._opened_at = self._clock()


def is_retryable_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)

    if status_code is None:
        error_module = type(error).__module__
        return (
            isinstance(error, (ConnectionError, OSError, TimeoutError))
            or error_module.startswith(
                ("grpc", "httpcore", "httpx", "openai", "qdrant_client")
            )
        )
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _retry_delay(
    attempt: int,
    base_seconds: float,
    max_seconds: float,
) -> float:
    exponential_delay = min(
        max_seconds,
        base_seconds * (2 ** (attempt - 1)),
    )
    return exponential_delay * random.uniform(0.5, 1.5)


def call_with_retry(
    operation: Callable[[], T],
    *,
    attempts: int,
    base_seconds: float,
    max_seconds: float,
    circuit_breaker: CircuitBreaker,
) -> T:
    circuit_breaker.before_call()

    for attempt in range(1, attempts + 1):
        try:
            result = operation()
        except Exception as error:
            retryable = is_retryable_error(error)
            if not retryable:
                raise
            if attempt == attempts:
                circuit_breaker.record_failure()
                raise
            time.sleep(_retry_delay(attempt, base_seconds, max_seconds))
        else:
            circuit_breaker.record_success()
            return result

    raise RuntimeError("Retry loop ended unexpectedly.")


async def call_with_retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_seconds: float,
    max_seconds: float,
    circuit_breaker: CircuitBreaker,
) -> T:
    circuit_breaker.before_call()

    for attempt in range(1, attempts + 1):
        try:
            result = await operation()
        except Exception as error:
            retryable = is_retryable_error(error)
            if not retryable:
                raise
            if attempt == attempts:
                circuit_breaker.record_failure()
                raise
            await asyncio.sleep(
                _retry_delay(attempt, base_seconds, max_seconds)
            )
        else:
            circuit_breaker.record_success()
            return result

    raise RuntimeError("Retry loop ended unexpectedly.")
