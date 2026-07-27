from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class UserCredentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Tên đăng nhập không được để trống.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_bcrypt_input(cls, value: str) -> str:
        if not value:
            raise ValueError("Mật khẩu không được để trống.")
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Mật khẩu không được vượt quá 72 byte UTF-8.")
        return value


class UserLogin(UserCredentials):
    pass


class UserRegister(UserCredentials):
    @field_validator("password")
    @classmethod
    def validate_registration_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Mật khẩu phải có ít nhất 8 ký tự.")
        return value

class UserResponse(BaseModel):
    id: int
    username: str
    created_at: datetime
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
