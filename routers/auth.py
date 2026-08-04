import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import settings
from core.security import (
    create_access_token,
    get_current_user,
    get_optional_current_user,
    hash_password,
    verify_password,
)
from database.connection import get_db
from database.models import UserModel
from schemas.auth import UserLogin, UserRegister, UserResponse
from services.rate_limit_service import consume_rate_limit


router = APIRouter(prefix="/auth", tags=["Authentication"])
DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-only")
AUTHENTICATION_ERROR = "Tài khoản hoặc mật khẩu không chính xác!"
REGISTRATION_ERROR = "Không thể đăng ký với thông tin đã cung cấp."


def _client_identifier(request: Request) -> str:
    candidate = request.client.host if request.client else ""
    if settings.TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        candidate = forwarded_for.split(",", maxsplit=1)[0].strip() or candidate

    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return "unknown"


def _enforce_rate_limit(
    db: Session,
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> None:
    result = consume_rate_limit(
        db,
        scope=scope,
        identifier=identifier,
        limit=limit,
        window_seconds=window_seconds,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Quá nhiều yêu cầu. Vui lòng thử lại sau.",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


@router.get("/me", response_model=UserResponse)
def get_authenticated_user(
    current_user: UserModel = Depends(get_current_user),
):
    return current_user


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    user_in: UserRegister,
    request: Request,
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(
        db,
        scope="auth.register.ip",
        identifier=_client_identifier(request),
        limit=settings.REGISTER_RATE_LIMIT_REQUESTS,
        window_seconds=settings.REGISTER_RATE_LIMIT_WINDOW_SECONDS,
    )

    password_hash = hash_password(user_in.password)
    existing_user = (
        db.query(UserModel)
        .filter(UserModel.username == user_in.username)
        .first()
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=REGISTRATION_ERROR,
        )

    new_user = UserModel(
        username=user_in.username,
        hashed_password=password_hash,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=REGISTRATION_ERROR,
        ) from exc
    db.refresh(new_user)

    return {
        "message": "Đăng ký tài khoản thành công!",
        "username": new_user.username,
    }


@router.post("/login")
def login(
    user_in: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(
        db,
        scope="auth.login.ip",
        identifier=_client_identifier(request),
        limit=settings.LOGIN_RATE_LIMIT_REQUESTS,
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )

    user = (
        db.query(UserModel)
        .filter(UserModel.username == user_in.username)
        .first()
    )
    if user is not None:
        _enforce_rate_limit(
            db,
            scope="auth.login.user",
            identifier=str(user.id),
            limit=settings.LOGIN_RATE_LIMIT_REQUESTS,
            window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )

    password_hash = user.hashed_password if user else DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(user_in.password, password_hash)
    if user is None or not password_is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTHENTICATION_ERROR,
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(user)
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=access_token,
        httponly=True,
        max_age=settings.AUTH_COOKIE_MAX_AGE_SECONDS,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        secure=settings.AUTH_COOKIE_SECURE,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )

    return {
        "message": "Đăng nhập thành công",
        "username": user.username,
    }


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    current_user: UserModel | None = Depends(get_optional_current_user),
):
    if current_user is not None:
        db.query(UserModel).filter(
            UserModel.id == current_user.id
        ).update(
            {UserModel.token_version: UserModel.token_version + 1},
            synchronize_session=False,
        )
        db.commit()

    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return {"message": "Đã đăng xuất"}
