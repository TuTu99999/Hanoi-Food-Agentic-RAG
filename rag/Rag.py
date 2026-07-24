import os
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import types
from embedding.retrieval_engine import RetrievalEngine


load_dotenv()

class RAGPipeline:
    def __init__(self):
        """
        Khởi tạo RAG Pipeline:
        1. Kiểm tra API Key.
        2. Khởi tạo Gemini API Client.
        3. Để self.retriever = None (Lazy Loading).
        """
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[Lỗi] Không tìm thấy GEMINI_API_KEY trong file .env hoặc hệ thống!")
            sys.exit(1)
            
        
        self.retriever = None
        
        self.ai_client = genai.Client(api_key=api_key)
        self.llm_model = "gemini-3.5-flash" 

    def _get_retriever(self):
        """Hàm hỗ trợ Lazy Load RetrievalEngine"""
        if self.retriever is None:
            print("[Info] Đang khởi tạo Retrieval Engine & Nạp Model Embedding...")
            self.retriever = RetrievalEngine()
        return self.retriever

    def run(self, user_question: str, collection_name: str, district: str = None):
        """
        Quy trình xử lý RAG hoàn chỉnh
        """
        # BƯỚC 1: RETRIEVAL (Chỉ lúc này mới tải Model Embedding vào RAM)
        retriever = self._get_retriever()
        
        context_docs = retriever.search(
            collection_name=collection_name,
            query=user_question,
            top_k=3,
            district_filter=district
        )
        
        if not context_docs or context_docs[0]['score'] < 0.3:
            return "Dựa trên dữ liệu hiện tại, hệ thống không tìm thấy thông tin nào liên quan đến câu hỏi của bạn."

        # Trích xuất văn bản thô từ Qdrant payload
        context_segments = []
        for doc in context_docs:
            segment = f"--- THÔNG TIN THỰC THỂ: {doc['title']} ({doc.get('district', 'N/A')}) ---\n{doc['text']}"
            context_segments.append(segment)
            
        context_text = "\n\n".join(context_segments)

        # BƯỚC 2: PROMPT ENGINEERING & HALLUCINATION HANDLING
        system_instruction = (
            "Bạn là một trợ lý ảo chuyên gia am hiểu sâu sắc về Ẩm thực và Địa điểm Du lịch Hà Nội.\n"
            "Nhiệm vụ của bạn là trả lời câu hỏi của người dùng một cách tự nhiên, thân thiện và hữu ích.\n"
            "QUY TẮC CHỐNG ẢO TƯỞNG (HALLUCINATION HANDLING) TUYỆT ĐỐI:\n"
            "1. Chỉ được phép sử dụng thông tin nằm trong phần 'NGỮ CẢNH CUNG CẤP' dưới đây để trả lời.\n"
            "2. Không tự ý thêm bớt, suy đoán hoặc sử dụng kiến thức bên ngoài của bạn để bổ sung thông tin nếu ngữ cảnh không nhắc tới.\n"
            "3. Nếu thông tin trong ngữ cảnh không đủ để trả lời câu hỏi, hãy thẳng thắn phản hồi: "
            "'Dựa trên dữ liệu hiện tại, tôi không có đủ thông tin chi tiết về vấn đề này.' một cách lịch sự."
        )

        user_content = f"""Dưới đây là dữ liệu chính xác được trích xuất từ hệ thống. Hãy dựa vào đó để xử lý yêu cầu của người dùng.

[NGỮ CẢNH CUNG CẤP]:
{context_text}

[CÂU HỎI NGƯỜI DÙNG]:
{user_question}

[CÂU TRẢ LỜI CỦA BẠN]:"""

        # BƯỚC 3: GENERATION
        try:
            response = self.ai_client.models.generate_content(
                model=self.llm_model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3, 
                    max_output_tokens=800
                )
            )
            return response.text
        except Exception as e:
            return f"[Lỗi hệ thống LLM]: Không thể sinh câu trả lời. Chi tiết lỗi: {str(e)}"