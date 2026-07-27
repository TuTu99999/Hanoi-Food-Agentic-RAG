import datetime
from datetime import timezone
from urllib.parse import urlsplit

import jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

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


# Hỗ trợ HttpOnly cookie cho browser và Bearer header cho Swagger/API clients.
class HTTPBearerWithCookie(HTTPBearer):
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


auth_scheme = HTTPBearerWithCookie(auto_error=False)


def hash_password(password: str) -> str:
    # bcrypt yêu cầu input dạng bytes
    pwd_bytes = password.encode('utf-8')
    # Tạo salt và hash
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(pwd_bytes, hashed_bytes)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    # Dùng timezone-aware UTC datetime để tránh warning
    expire = datetime.datetime.now(timezone.utc) + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def get_current_user(
    token: str = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> UserModel:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Thông tin xác thực tài khoản không hợp lệ hoặc đã hết hạn",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    user = db.query(UserModel).filter(UserModel.username == username).first()
    if user is None:
        raise credentials_exception
        
    return user
