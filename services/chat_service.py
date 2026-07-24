from database.connection import SessionLocal
from database.models import MessageModel, ChatSessionModel

def save_message_task(session_id: int, question: str, answer: str, district: str):
    db = SessionLocal()
    try:
        new_msg = MessageModel(
            session_id=session_id,
            question=question,
            answer=answer,
            district_filter=district
        )
        db.add(new_msg)
        
        session = db.query(ChatSessionModel).filter(ChatSessionModel.id == session_id).first()
        if session and session.title == "Cuộc trò chuyện mới":
            session.title = question[:30] + "..." if len(question) > 30 else question
            
        db.commit()
    except Exception as e:
        print(f"[Lỗi Ghi Lịch Sử Ngầm]: {str(e)}")
    finally:
        db.close()