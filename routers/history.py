from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database.connection import get_db
from database.models import UserModel, ChatSessionModel, MessageModel
from schemas.chat import SessionResponse, MessageResponse
from core.security import get_current_user

router = APIRouter(prefix="/history", tags=["Chat History"])

@router.get("", response_model=List[SessionResponse])
def get_chat_sessions(
    current_user: UserModel = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    return db.query(ChatSessionModel)\
             .filter(ChatSessionModel.user_id == current_user.id)\
             .order_by(ChatSessionModel.created_at.desc()).all()

@router.get("/{session_id}", response_model=List[MessageResponse])
def get_session_messages(
    session_id: int,
    current_user: UserModel = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    session = db.query(ChatSessionModel).filter(
        ChatSessionModel.id == session_id, 
        ChatSessionModel.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Phiên hội thoại không tồn tại.")
        
    return db.query(MessageModel)\
             .filter(MessageModel.session_id == session_id)\
             .order_by(MessageModel.created_at.asc()).all()

@router.delete("/{session_id}", status_code=status.HTTP_200_OK)
def delete_chat_session(
    session_id: int,
    current_user: UserModel = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    deleted = db.query(ChatSessionModel).filter(
        ChatSessionModel.id == session_id, 
        ChatSessionModel.user_id == current_user.id
    ).delete()
    db.commit()
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên hội thoại cần xóa.")
    return {"message": f"Đã xóa phiên hội thoại {session_id} thành công!"}