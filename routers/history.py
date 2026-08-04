from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List

from database.connection import get_db
from database.models import UserModel, ChatSessionModel, MessageModel
from schemas.chat import SessionResponse, MessageResponse
from core.security import get_current_user

router = APIRouter(prefix="/history", tags=["Chat History"])

@router.get("", response_model=List[SessionResponse])
def get_chat_sessions(
    limit: int = Query(default=20, ge=1, le=50),
    cursor: int | None = Query(default=None, gt=0),
    current_user: UserModel = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    query = db.query(ChatSessionModel).filter(
        ChatSessionModel.user_id == current_user.id
    )
    if cursor is not None:
        query = query.filter(ChatSessionModel.id < cursor)
    return query.order_by(ChatSessionModel.id.desc()).limit(limit).all()

@router.get("/{session_id}", response_model=List[MessageResponse])
def get_session_messages(
    session_id: int,
    limit: int = Query(default=100, ge=1, le=100),
    cursor: int | None = Query(default=None, ge=0),
    current_user: UserModel = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    session = db.query(ChatSessionModel).filter(
        ChatSessionModel.id == session_id, 
        ChatSessionModel.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Phiên hội thoại không tồn tại.")
        
    query = db.query(MessageModel).filter(
        MessageModel.session_id == session_id
    )
    if cursor is not None:
        query = query.filter(MessageModel.position < cursor)
    messages = (
        query.order_by(
            MessageModel.position.desc(),
            MessageModel.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return list(reversed(messages))

@router.delete("/{session_id}", status_code=status.HTTP_200_OK)
def delete_chat_session(
    session_id: int,
    current_user: UserModel = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    session = db.query(ChatSessionModel).filter(
        ChatSessionModel.id == session_id, 
        ChatSessionModel.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên hội thoại cần xóa.")

    db.delete(session)
    db.commit()
    return {"message": f"Đã xóa phiên hội thoại {session_id} thành công!"}
