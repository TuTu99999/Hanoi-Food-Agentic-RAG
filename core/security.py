import datetime
import uuid
from datetime import timezone
from urllib.parse import urlsplit

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from starlette.datastructures import MutableHeaders

from core.config import ConfigurationError, normalize_origin, settings
from database.connection import get_db
from database.models import UserModel


SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_AUTH_WRITE_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
}


def _request_source_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin is not None:
        if origin.strip().lower() == "null":
            return None
        try:
            return normalize_origin(origin)
        except ConfigurationError:
            return None

    referer = request.headers.get("referer")
    if not referer:
        return None

    parsed_referer = urlsplit(referer)
    if not parsed_referer.scheme or not parsed_referer.netloc:
        return None

    try:
        return normalize_origin(
            f"{parsed_referer.scheme}://{parsed_referer.netloc}"
        )
    except ConfigurationError:
        return None


def validate_csrf_request(request: Request) -> None:
    """Reject forged browser writes while keeping Bearer-only clients usable."""
    if request.method.upper() in SAFE_HTTP_METHODS:
        return

    has_auth_cookie = bool(
        request.cookies.get(settings.AUTH_COOKIE_NAME)
    )
    has_browser_source = bool(
        request.headers.get("origin")
        or request.headers.get("referer")
    )
    requires_origin = (
        has_auth_cookie
        or has_browser_source
        or request.url.path in PUBLIC_AUTH_WRITE_PATHS
    )
    if not requires_origin:
        return

    source_origin = _request_source_origin(request)
    trusted_origins = set(settings.CORS_ORIGINS)

    # TestClient and local direct API calls do not have a configured browser
    # origin. Production only trusts the explicit CORS allowlist.
    if settings.APP_ENV != "production":
        try:
            base_url = urlsplit(str(request.base_url))
            trusted_origins.add(
                normalize_origin(f"{base_url.scheme}://{base_url.netloc}")
            )
        except ConfigurationError:
            pass

    if source_origin not in trusted_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nguồn gửi yêu cầu không hợp lệ.",
        )


class HTTPBearerWithCookie(HTTPBearer):
    """Read auth from an HttpOnly cookie or a Bearer header."""

    async def __call__(self, request: Request) -> str | None:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)
        if token:
            scheme, _, value = token.partition(" ")
            if scheme.lower() == "bearer" and value:
                return value.strip()
            return token

        credentials: HTTPAuthorizationCredentials | None = await super().__call__(
            request
        )
        if credentials is not None:
            return credentials.credentials
        return None


class NoStoreMiddleware:
    """Prevent browsers and proxies from caching sensitive API responses."""

    def __init__(self, app, path_prefixes: tuple[str, ...]):
        self.app = app
        self.path_prefixes = path_prefixes

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope.get("path", "").startswith(self.path_prefixes)
        ):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "private, no-cache, no-store"
                headers["Pragma"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_no_store)


auth_scheme = HTTPBearerWithCookie(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(user: UserModel) -> str:
    now = datetime.datetime.now(timezone.utc)
    expire = now + datetime.timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "ver": user.token_version,
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def _decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={
            "require": [
                "sub",
                "ver",
                "iat",
                "exp",
                "jti",
                "iss",
                "aud",
            ]
        },
    )


def _user_from_token(
    token: str | None,
    db: Session,
) -> UserModel | None:
    if not token:
        return None

    try:
        payload = _decode_access_token(token)
        user_id = int(payload["sub"])
        token_version = payload["ver"]
        if (
            isinstance(token_version, bool)
            or not isinstance(token_version, int)
            or not isinstance(payload["jti"], str)
        ):
            return None
    except (KeyError, TypeError, ValueError, jwt.PyJWTError):
        return None

    return (
        db.query(UserModel)
        .filter(
            UserModel.id == user_id,
            UserModel.token_version == token_version,
        )
        .first()
    )


def get_current_user(
    token: str | None = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> UserModel:
    user = _user_from_token(token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Thông tin xác thực tài khoản không hợp lệ "
                "hoặc đã hết hạn"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_current_user(
    token: str | None = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> UserModel | None:
    return _user_from_token(token, db)
