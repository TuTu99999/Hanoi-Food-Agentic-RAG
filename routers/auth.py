from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import UserModel
from schemas.auth import UserLogin, UserRegister, UserResponse
from core.config import settings
from core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/me", response_model=UserResponse)
def get_authenticated_user(
    current_user: UserModel = Depends(get_current_user),
):
    return current_user


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user_in: UserRegister, db: Session = Depends(get_db)):
    # 1. Check user đã tồn tại chưa
    existing_user = db.query(UserModel).filter(UserModel.username == user_in.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Tên đăng nhập đã tồn tại!")

    # 2. Tạo user mới với password đã hash
    new_user = UserModel(
        username=user_in.username,
        hashed_password=hash_password(user_in.password)
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tên đăng nhập đã tồn tại!",
        ) from exc
    db.refresh(new_user)

    # 3. Trả về thông báo (TUYỆT ĐỐI KHÔNG set_cookie ở đây)
    return {"message": "Đăng ký tài khoản thành công!", "username": new_user.username}

@router.post("/login")
def login(user_in: UserLogin, response: Response, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.username == user_in.username).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản hoặc mật khẩu không chính xác!",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Tạo JWT Token
    access_token = create_access_token(data={"sub": user.username})
    
    # ✅ Ghi Token trực tiếp vào HttpOnly Cookie
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.AUTH_COOKIE_MAX_AGE_SECONDS,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        secure=settings.AUTH_COOKIE_SECURE,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )
    
    return {"message": "Đăng nhập thành công", "username": user.username}

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return {"message": "Đã đăng xuất"}
