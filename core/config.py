import os
from urllib.parse import urlsplit

from dotenv import load_dotenv


load_dotenv()

DEVELOPMENT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_cors_origins_env = os.getenv("CORS_ORIGINS")


class ConfigurationError(RuntimeError):
    pass


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ConfigurationError(
        f"[Lỗi Cấu Hình] {name} phải là true hoặc false."
    )


def _get_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(
            f"[Lỗi Cấu Hình] {name} phải là số nguyên."
        ) from exc


def _get_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(
            f"[Lỗi Cấu Hình] {name} phải là số."
        ) from exc


def normalize_origin(value: str) -> str:
    """Return one canonical HTTP origin without a trailing slash."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(
            f"[Lỗi Cấu Hình] Origin không hợp lệ: {value}"
        ) from exc

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            f"[Lỗi Cấu Hình] Origin không hợp lệ: {value}"
        )

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"

    default_port = 80 if scheme == "http" else 443
    port_suffix = f":{port}" if port and port != default_port else ""
    return f"{scheme}://{host}{port_suffix}"


def _get_cors_origins() -> tuple[str, ...]:
    values = (
        _cors_origins_env.split(",")
        if _cors_origins_env is not None
        else DEVELOPMENT_CORS_ORIGINS
    )
    origins = [
        normalize_origin(value)
        for value in values
        if value.strip()
    ]
    return tuple(dict.fromkeys(origins))


def _validate_http_url(name: str, value: str) -> None:
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise ConfigurationError(
            f"[Lỗi Cấu Hình] {name} không phải URL hợp lệ."
        ) from exc

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            f"[Lỗi Cấu Hình] {name} phải là HTTP(S) URL hợp lệ."
        )


def _get_qdrant_connection() -> tuple[str, int, str]:
    host = os.getenv("QDRANT_HOST", "localhost").strip()
    configured_url = os.getenv("QDRANT_URL", "").strip().rstrip("/")
    if configured_url:
        return host, 6333, configured_url

    port = _get_int_env("QDRANT_PORT", 6333)
    return host, port, f"http://{host}:{port}"


_qdrant_host, _qdrant_port, _qdrant_url = _get_qdrant_connection()


class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "development").strip().lower()
    CORS_ORIGINS: tuple[str, ...] = _get_cors_origins()

    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256").strip().upper()
    ACCESS_TOKEN_EXPIRE_MINUTES: int = _get_int_env(
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        60,
    )

    AUTH_COOKIE_NAME: str = os.getenv(
        "AUTH_COOKIE_NAME",
        "access_token",
    ).strip()
    AUTH_COOKIE_MAX_AGE_SECONDS: int = _get_int_env(
        "AUTH_COOKIE_MAX_AGE_SECONDS",
        ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    AUTH_COOKIE_SECURE: bool = _get_bool_env(
        "AUTH_COOKIE_SECURE",
        False,
    )
    AUTH_COOKIE_SAMESITE: str = os.getenv(
        "AUTH_COOKIE_SAMESITE",
        "lax",
    ).strip().lower()
    AUTH_COOKIE_PATH: str = os.getenv("AUTH_COOKIE_PATH", "/").strip()
    AUTH_COOKIE_DOMAIN: str | None = (
        os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
    )

    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "").strip()
    LLM_BASE_URL: str = os.getenv(
        "LLM_BASE_URL",
        "https://models.inference.ai.azure.com",
    ).strip().rstrip("/")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    LLM_TIMEOUT_SECONDS: int = _get_int_env("LLM_TIMEOUT_SECONDS", 30)
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ).strip()
    EMBEDDING_LOCAL_FILES_ONLY: bool = _get_bool_env(
        "EMBEDDING_LOCAL_FILES_ONLY",
        True,
    )

    QDRANT_HOST: str = _qdrant_host
    QDRANT_PORT: int = _qdrant_port
    QDRANT_URL: str = _qdrant_url
    QDRANT_API_KEY: str | None = (
        os.getenv("QDRANT_API_KEY", "").strip() or None
    )
    QDRANT_COLLECTION: str = os.getenv(
        "QDRANT_COLLECTION",
        "hanoi_knowledge_current",
    ).strip()
    QDRANT_TIMEOUT_SECONDS: float = _get_float_env(
        "QDRANT_TIMEOUT_SECONDS",
        5.0,
    )
    RAG_MIN_SCORE: float = _get_float_env("RAG_MIN_SCORE", 0.5)

    EXTERNAL_RETRY_ATTEMPTS: int = _get_int_env(
        "EXTERNAL_RETRY_ATTEMPTS",
        3,
    )
    EXTERNAL_RETRY_BASE_SECONDS: float = _get_float_env(
        "EXTERNAL_RETRY_BASE_SECONDS",
        0.25,
    )
    EXTERNAL_RETRY_MAX_SECONDS: float = _get_float_env(
        "EXTERNAL_RETRY_MAX_SECONDS",
        2.0,
    )
    CIRCUIT_BREAKER_FAILURES: int = _get_int_env(
        "CIRCUIT_BREAKER_FAILURES",
        5,
    )
    CIRCUIT_BREAKER_RESET_SECONDS: float = _get_float_env(
        "CIRCUIT_BREAKER_RESET_SECONDS",
        30.0,
    )
    HEALTHCHECK_TIMEOUT_SECONDS: float = _get_float_env(
        "HEALTHCHECK_TIMEOUT_SECONDS",
        3.0,
    )
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    CHAT_RATE_LIMIT_REQUESTS: int = _get_int_env(
        "CHAT_RATE_LIMIT_REQUESTS",
        20,
    )
    CHAT_RATE_LIMIT_WINDOW_SECONDS: int = _get_int_env(
        "CHAT_RATE_LIMIT_WINDOW_SECONDS",
        60,
    )
    DB_SCHEMA_CHECK: bool = _get_bool_env("DB_SCHEMA_CHECK", True)


def _validate_settings(config: Settings) -> None:
    if config.APP_ENV not in {"development", "test", "production"}:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] APP_ENV phải là development, test hoặc production."
        )

    if not config.DATABASE_URL:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] Chưa khai báo DATABASE_URL trong .env!"
        )
    if not config.JWT_SECRET_KEY:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] Chưa khai báo JWT_SECRET_KEY trong .env!"
        )
    if config.JWT_ALGORITHM not in {"HS256", "HS384", "HS512"}:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] JWT_ALGORITHM không được hỗ trợ."
        )
    if config.ACCESS_TOKEN_EXPIRE_MINUTES <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] ACCESS_TOKEN_EXPIRE_MINUTES phải lớn hơn 0."
        )

    if not config.AUTH_COOKIE_NAME:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] AUTH_COOKIE_NAME không được để trống."
        )
    if config.AUTH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] AUTH_COOKIE_SAMESITE phải là lax, strict hoặc none."
        )
    if (
        config.AUTH_COOKIE_SAMESITE == "none"
        and not config.AUTH_COOKIE_SECURE
    ):
        raise ConfigurationError(
            "[Lỗi Cấu Hình] Cookie SameSite=none bắt buộc "
            "AUTH_COOKIE_SECURE=true."
        )
    if config.AUTH_COOKIE_MAX_AGE_SECONDS <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] AUTH_COOKIE_MAX_AGE_SECONDS phải lớn hơn 0."
        )
    if not config.AUTH_COOKIE_PATH.startswith("/"):
        raise ConfigurationError(
            "[Lỗi Cấu Hình] AUTH_COOKIE_PATH phải bắt đầu bằng /."
        )

    if not config.CORS_ORIGINS:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] CORS_ORIGINS không được để trống."
        )

    if not config.LLM_MODEL:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] LLM_MODEL không được để trống."
        )
    if not config.EMBEDDING_MODEL:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] EMBEDDING_MODEL không được để trống."
        )
    if config.LLM_TIMEOUT_SECONDS <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] LLM_TIMEOUT_SECONDS phải lớn hơn 0."
        )
    _validate_http_url("LLM_BASE_URL", config.LLM_BASE_URL)

    if config.QDRANT_PORT <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] QDRANT_PORT phải lớn hơn 0."
        )
    if not config.QDRANT_COLLECTION:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] QDRANT_COLLECTION không được để trống."
        )
    _validate_http_url("QDRANT_URL", config.QDRANT_URL)
    if not 0 <= config.RAG_MIN_SCORE <= 1:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] RAG_MIN_SCORE phải nằm trong khoảng 0 đến 1."
        )
    if config.QDRANT_TIMEOUT_SECONDS <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] QDRANT_TIMEOUT_SECONDS phải lớn hơn 0."
        )

    if not 1 <= config.EXTERNAL_RETRY_ATTEMPTS <= 5:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] EXTERNAL_RETRY_ATTEMPTS phải từ 1 đến 5."
        )
    if config.EXTERNAL_RETRY_BASE_SECONDS < 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] EXTERNAL_RETRY_BASE_SECONDS không được âm."
        )
    if (
        config.EXTERNAL_RETRY_MAX_SECONDS
        < config.EXTERNAL_RETRY_BASE_SECONDS
    ):
        raise ConfigurationError(
            "[Lỗi Cấu Hình] EXTERNAL_RETRY_MAX_SECONDS phải lớn hơn "
            "hoặc bằng EXTERNAL_RETRY_BASE_SECONDS."
        )
    if config.CIRCUIT_BREAKER_FAILURES <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] CIRCUIT_BREAKER_FAILURES phải lớn hơn 0."
        )
    if config.CIRCUIT_BREAKER_RESET_SECONDS <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] CIRCUIT_BREAKER_RESET_SECONDS phải lớn hơn 0."
        )
    if config.HEALTHCHECK_TIMEOUT_SECONDS <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] HEALTHCHECK_TIMEOUT_SECONDS phải lớn hơn 0."
        )
    if config.LOG_LEVEL not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] LOG_LEVEL không hợp lệ."
        )

    if config.CHAT_RATE_LIMIT_REQUESTS <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] CHAT_RATE_LIMIT_REQUESTS phải lớn hơn 0."
        )
    if config.CHAT_RATE_LIMIT_WINDOW_SECONDS <= 0:
        raise ConfigurationError(
            "[Lỗi Cấu Hình] CHAT_RATE_LIMIT_WINDOW_SECONDS phải lớn hơn 0."
        )

    if config.APP_ENV == "production":
        if _cors_origins_env is None:
            raise ConfigurationError(
                "[Lỗi Cấu Hình] Production phải khai báo CORS_ORIGINS."
            )
        if not config.AUTH_COOKIE_SECURE:
            raise ConfigurationError(
                "[Lỗi Cấu Hình] Production bắt buộc AUTH_COOKIE_SECURE=true."
            )
        if len(config.JWT_SECRET_KEY.encode("utf-8")) < 32:
            raise ConfigurationError(
                "[Lỗi Cấu Hình] JWT_SECRET_KEY production phải có ít nhất 32 byte."
            )
        if config.JWT_SECRET_KEY.startswith("replace-with"):
            raise ConfigurationError(
                "[Lỗi Cấu Hình] JWT_SECRET_KEY production vẫn là placeholder."
            )
        if (
            not config.GITHUB_TOKEN
            or config.GITHUB_TOKEN.startswith("replace-with")
        ):
            raise ConfigurationError(
                "[Lỗi Cấu Hình] Production cần GITHUB_TOKEN hợp lệ."
            )
        if any(
            not origin.startswith("https://")
            for origin in config.CORS_ORIGINS
        ):
            raise ConfigurationError(
                "[Lỗi Cấu Hình] CORS_ORIGINS production phải dùng HTTPS."
            )


settings = Settings()
_validate_settings(settings)
