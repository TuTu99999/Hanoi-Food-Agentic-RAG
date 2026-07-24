from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json
from typing import Optional

from database.connection import get_db
from database.models import UserModel, ChatSessionModel
from schemas.chat import ChatRequest, ChatResponse
from core.security import get_current_user
from services.chat_service import save_message_task

# ✅ 1. Prefix /chat (kết hợp main.py /api -> /api/chat)
router = APIRouter(prefix="/chat", tags=["RAG Chat"])

# Danh sách 30 quận/huyện Hà Nội để đối soát từ khóa trong tin nhắn
HANOI_DISTRICTS = [
    "Hoàn Kiếm", "Ba Đình", "Tây Hồ", "Cầu Giấy", "Hai Bà Trưng", "Đống Đa", 
    "Thanh Xuân", "Hoàng Mai", "Long Biên", "Nam Từ Liêm", "Bắc Từ Liêm", "Hà Đông",
    "Sơn Tây", "Thanh Trì", "Gia Lâm", "Đông Anh", "Sóc Sơn", "Thạch Thất", 
    "Quốc Oai", "Chương Mỹ", "Đan Phượng", "Hoài Đức", "Mê Linh", "Mỹ Đức", 
    "Phú Xuyên", "Phúc Thọ", "Thanh Oai", "Thường Tín", "Ứng Hòa"
]

def resolve_effective_district(user_question: str, ui_district: Optional[str]) -> Optional[str]:
    """
    Xử lý độ ưu tiên lọc khu vực:
    1. Nếu tin nhắn chứa tên quận/huyện -> ƯU TIÊN LẤY TÊN QUẬN TRONG TIN NHẮN.
    2. Nếu tin nhắn không chứa tên quận/huyện -> Lấy quận ở UI (nếu khác None / 'Tất cả').
    """
    question_lower = user_question.lower()
    
    # 1. Quét tìm tên quận trong câu hỏi
    for district in HANOI_DISTRICTS:
        if district.lower() in question_lower:
            return district  # Override thành công
            
    # 2. Nếu câu hỏi chung chung -> Dùng quận từ UI Dropdown
    if ui_district and ui_district != "Tất cả":
        return ui_district
        
    return None

# Import RAG Pipeline
try:
    from rag.Rag import RAGPipeline
    rag_chain = RAGPipeline()
except Exception as e:
    print(f"[Cảnh báo] Chưa kết nối được rag/Rag.py. Chi tiết: {str(e)}")
    rag_chain = None


# API trả về JSON bình thường (POST /api/chat)
@router.post("", response_model=ChatResponse)
def chat_with_rag(
    payload: ChatRequest, 
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not rag_chain:
        raise HTTPException(status_code=503, detail="Lõi RAG chưa sẵn sàng.")

    session_id = payload.session_id
    if not session_id:
        new_session = ChatSessionModel(user_id=current_user.id)
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        session_id = new_session.id
    else:
        session_exists = db.query(ChatSessionModel).filter(
            ChatSessionModel.id == session_id, 
            ChatSessionModel.user_id == current_user.id
        ).first()
        if not session_exists:
            raise HTTPException(status_code=404, detail="Không tìm thấy phiên hội thoại phù hợp.")

    # 🟢 Xử lý chốt quận thực tế trước khi đẩy vào RAG
    effective_district = resolve_effective_district(payload.question, payload.district)

    answer = rag_chain.run(
        user_question=payload.question, 
        collection_name="hanoi_food_collection", 
        district=effective_district  # 👈 Dùng effective_district đã giải quyết xung đột
    )
    
    background_tasks.add_task(save_message_task, session_id, payload.question, answer, effective_district)
    
    return {"session_id": session_id, "question": payload.question, "answer": answer}


# ✅ 2. API STREAMING (POST /api/chat/stream)
@router.post("/stream")
async def chat_stream(payload: ChatRequest):
    if not rag_chain:
        raise HTTPException(status_code=503, detail="Lõi RAG chưa sẵn sàng.")

    # 🟢 Xử lý chốt quận thực tế ở API Stream
    effective_district = resolve_effective_district(payload.question, payload.district)

    async def event_generator():
        answer = rag_chain.run(
            user_question=payload.question, 
            collection_name="hanoi_food_collection", 
            district=effective_district
        )
        yield answer

    return StreamingResponse(event_generator(), media_type="text/plain")