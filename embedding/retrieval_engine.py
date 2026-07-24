from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer

class RetrievalEngine:
    def __init__(self, qdrant_host="localhost", qdrant_port=6333):
        """
        Khởi tạo Bộ tìm kiếm dữ liệu (Retrieval Engine):
        1. Kết nối tới Qdrant Vector DB thông qua API port.
        2. Tải mô hình nhúng câu đa ngôn ngữ (Đồng bộ 384 chiều với khâu tiền xử lý).
        """
        print("Đang khởi tạo kết nối tới Qdrant Vector DB...")
        self.client = QdrantClient(host=qdrant_host, port=qdrant_port)
        
        print("Đang tải mô hình Embedding (MiniLM-L12)...")
        self.model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    def search(self, collection_name: str, query: str, top_k: int = 3, district_filter: str = None):
        """
        Pipeline Giai đoạn 6 (Retrieval):
        Question -> Chuyển đổi Embedding -> Qdrant Search (kèm Metadata Filter) -> Trả về Top-k Documents.
        """
        # Bước A: Chuyển đổi câu hỏi của người dùng (Question) thành dạng mã hóa Vector
        query_vector = self.model.encode(query).tolist()

        # Bước B: Xây dựng bộ lọc thuộc tính (Metadata Filtering) nếu có yêu cầu lọc theo quận
        search_filter = None
        if district_filter:
            search_filter = Filter(
                must=[
                    FieldCondition(
                        key="metadata.district",
                        match=MatchValue(value=district_filter)
                    )
                ]
            )

        # Bước C & D: Thực hiện tìm kiếm tương đồng (Similarity Search) để bóc tách Top-k kết quả tốt nhất
        raw_results = self.client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=search_filter,
            limit=top_k
        )

        # Trích xuất và định dạng lại dữ liệu sạch sẽ để chuẩn bị bàn giao cho LLM ở khâu sinh câu trả lời (Generation)
        retrieved_documents = []
        for hit in raw_results:
            retrieved_documents.append({
                "score": hit.score,
                "title": hit.payload["metadata"]["title"],
                "district": hit.payload["metadata"]["district"],
                "text": hit.payload["vector_text"]
            })

        return retrieved_documents