from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from datetime import datetime
from uuid import UUID


class NearbySearch(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=3, ge=0.2, le=20)


class ChatRequest(BaseModel):
    session_id: Optional[int] = Field(default=None, gt=0)
    client_request_id: Optional[str] = Field(
        default=None,
        min_length=36,
        max_length=36,
    )
    question: str = Field(min_length=1, max_length=2000)
    district: Optional[str] = Field(default="Tất cả", max_length=100)
    nearby: Optional[NearbySearch] = None

    @field_validator("client_request_id")
    @classmethod
    def validate_client_request_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return str(UUID(value))

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Câu hỏi không được để trống.")
        return normalized

    @field_validator("district")
    @classmethod
    def normalize_district(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class MessageResponse(BaseModel):
    id: int
    turn_id: str
    position: int
    role: Literal["user", "assistant"]
    content: str
    status: Literal["pending", "completed", "error"]
    district_filter: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatResponse(BaseModel):
    session_id: int
    user_message: MessageResponse
    assistant_message: MessageResponse


class SessionResponse(BaseModel):
    id: int
    title: str
    created_at: datetime

    class Config:
        from_attributes = True
