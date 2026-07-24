from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import UserModel
from schemas.auth import UserRegister, UserResponse
from core.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["Authentication"])

# routers/auth.py
@router.post("/register", status_code=201)
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
    db.commit()
    db.refresh(new_user)

    # 3. Trả về thông báo (TUYỆT ĐỐI KHÔNG set_cookie ở đây)
    return {"message": "Đăng ký tài khoản thành công!", "username": new_user.username}

@router.post("/login")
def login(user_in: UserRegister, response: Response, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.username == user_in.username).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Tài khoản hoặc mật khẩu không chính xác!")
    
    # Tạo JWT Token
    access_token = create_access_token(data={"sub": user.username})
    
    # ✅ Ghi Token trực tiếp vào HttpOnly Cookie
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,   # 👈 Khóa JS đọc Cookie (Chống XSS)
        max_age=1800,    # Thời gian sống Cookie (VD: 30 phút = 1800 giây)
        samesite="lax",  # Chống CSRF
        secure=False     # Đặt False nếu chạy localhost (HTTP), True khi deploy HTTPS
    )
    
    return {"message": "Đăng nhập thành công", "username": user.username}

@router.post("/logout")
def logout(response: Response):
    # ✅ Xóa Cookie khi Đăng xuất
    response.delete_cookie(key="access_token")
    return {"message": "Đã đăng xuất"}