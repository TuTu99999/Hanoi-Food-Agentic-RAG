from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ChatRequest(BaseModel):
    session_id: Optional[int] = None
    question: str
    district: Optional[str] = "Tất cả"

class ChatResponse(BaseModel):
    session_id: int
    question: str
    answer: str

class MessageResponse(BaseModel):
    id: int
    question: str
    answer: str
    district_filter: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True

class SessionResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    class Config:
        from_attributes = True