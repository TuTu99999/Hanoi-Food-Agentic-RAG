import json
import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# ==========================================
# BUỚC 1: KẾT NỐI QDRANT
# ==========================================
print("Đang kết nối tới Qdrant Vector DB (localhost:6333)...")
client = QdrantClient(host="localhost", port=6333)

def upload_vector_data(vector_file_path, collection_name):
    """
    Hàm thực hiện trọn vẹn Giai đoạn 5:
    1. Tạo Collection (nếu chưa có) với cấu hình 384 chiều, khoảng cách Cosine.
    2. Đọc file JSON chứa vector đã sinh từ Giai đoạn 4.
    3. Đóng gói và Upload đồng thời cả Embedding và Payload (bao gồm Metadata) lên Qdrant.
    """
    if not os.path.exists(vector_file_path):
        print(f"[Cảnh báo] Không tìm thấy file dữ liệu vector tại: {vector_file_path}")
        return

    # Đọc dữ liệu từ Giai đoạn 4
    with open(vector_file_path, 'r', encoding='utf-8') as f:
        chunks = json.load(f)

    if not chunks:
        print("[Lỗi] File JSON trống, không có dữ liệu để nạp.")
        return

    # ==========================================
    # BƯỚC 2: TẠO COLLECTION
    # ==========================================
    if not client.collection_exists(collection_name=collection_name):
        print(f"-> [Khởi tạo] Tạo mới Collection: '{collection_name}'")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
    else:
        print(f"-> [Thông báo] Collection '{collection_name}' đã tồn tại sẵn trên hệ thống.")

    # ==========================================
    # BƯỚC 3 & 4: UPLOAD EMBEDDING & PAYLOAD
    # ==========================================
    points = []
    for idx, chunk in enumerate(chunks):
        point_id = idx + 1  # Định danh ID kiểu số nguyên tăng dần cho mỗi point
        
        point = PointStruct(
            id=point_id,
            vector=chunk["vector"],  # <--- BƯỚC 3: UPLOAD EMBEDDING
            payload={                # <--- BƯỚC 4: UPLOAD PAYLOAD
                "chunk_id": chunk["chunk_id"],
                "vector_text": chunk["vector_text"],
                "metadata": chunk["metadata"]  # Lưu giữ toàn vẹn cấu trúc để phục vụ Metadata Filtering về sau
            }
        )
        points.append(point)

    print(f"-> Đang tiến hành nạp {len(points)} points dữ liệu lên Qdrant...")
    
    # Thực hiện upsert đồng bộ dữ liệu
    client.upsert(collection_name=collection_name, wait=True, points=points)
    print(f"[Thành công] Đã hoàn thành Giai đoạn 5! Toàn bộ dữ liệu đã nằm an toàn trong '{collection_name}'.")


if __name__ == "__main__":
    print("--- KHỞI CHẠY GIAI ĐOẠN 5: XÂY DỰNG VECTOR DATABASE (QDRANT) ---")
    
    # Cấu hình đường dẫn file dữ liệu và tên collection thực tế của bạn
    DATA_PATH = "data/final/food_vector.json"
    COLLECTION_NAME = "hanoi_food_collection"
    
    # Thực thi nạp dữ liệu
    upload_vector_data(DATA_PATH, COLLECTION_NAME)