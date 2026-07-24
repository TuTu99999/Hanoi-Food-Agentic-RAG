import datetime
from datetime import timezone
import jwt
import bcrypt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from core.config import settings
from database.connection import get_db
from database.models import UserModel

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Custom lại lớp OAuth2 để vừa hỗ trợ Swagger UI vừa hỗ trợ lấy Token từ Cookie
class OAuth2PasswordBearerWithCookie(OAuth2PasswordBearer):
    async def __call__(self, request: Request) -> str | None:
        # 1. Ưu tiên lấy Token từ HttpOnly Cookie
        token = request.cookies.get("access_token")
        
        # 2. Nếu trong Cookie có chứa chữ "Bearer ", cắt bớt ra
        if token and token.startswith("Bearer "):
            token = token.split(" ")[1]
            return token
            
        # 3. Nếu Cookie không có, fallback về kiểm tra Header Authorization (Để dùng được cho Swagger UI /docs)
        header_auth = request.headers.get("Authorization")
        if header_auth and header_auth.startswith("Bearer "):
            return header_auth.split(" ")[1]
            
        return token

oauth2_scheme = OAuth2PasswordBearerWithCookie(tokenUrl="/api/auth/login", auto_error=False)

import bcrypt

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

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserModel:
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