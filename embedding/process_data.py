import json
import os
import re
import numpy as np
from sentence_transformers import SentenceTransformer

# 1. Khởi tạo mô hình Embedding siêu nhẹ, hiểu tiếng Việt (Đã cài sẵn trong máy bạn)
print("Đang tải mô hình Embedding đa ngôn ngữ siêu nhẹ...")
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

def clean_text(text):
    """Làm sạch khoảng trắng, dấu xuống dòng thừa."""
    if not text: 
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def semantic_chunking(text, threshold_percentile=60):
    """
    Tự động băm nhỏ văn bản theo ngữ nghĩa bằng cách đo khoảng cách vector giữa các câu liên tiếp.
    Không phụ thuộc vào LangChain.
    """
    # Tách văn bản thành danh sách các câu đơn lẻ
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [clean_text(s) for s in sentences if clean_text(s)]
    
    if len(sentences) <= 1:
        return sentences

    # Tính Vector Embedding cho từng câu một
    embeddings = model.encode(sentences, convert_to_numpy=True)
    
    # Tính toán khoảng cách Cosine (Cosine Distance) giữa các câu liên tiếp
    # Khoảng cách càng lớn nghĩa là ý nghĩa của 2 câu liên tiếp càng chuyển biến mạnh
    distances = []
    for i in range(len(embeddings) - 1):
        vec1 = embeddings[i]
        vec2 = embeddings[i+1]
        # Công thức tính Cosine Distance
        cosine_dist = 1 - (np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))
        distances.append(cosine_dist)

    # Xác định điểm cắt (breakpoint) dựa trên phân vị (percentile)
    if distances:
        breakpoint_threshold = np.percentile(distances, threshold_percentile)
    else:
        breakpoint_threshold = 0.5

    # Tiến hành gom cụm câu thành các chunk dựa trên điểm cắt
    chunks = []
    current_chunk = [sentences[0]]
    
    for i, distance in enumerate(distances):
        if distance > breakpoint_threshold:
            # Nếu sự thay đổi ý nghĩa vượt ngưỡng -> Đóng chunk cũ, tạo chunk mới
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentences[i + 1]]
        else:
            # Nếu ý nghĩa vẫn tương đồng -> Gom chung câu tiếp theo vào chunk hiện tại
            current_chunk.append(sentences[i + 1])
            
    if current_chunk:
        chunks.append(" ".join(current_chunk))
        
    return chunks

def process_file_semantic(raw_file_path, processed_file_path, data_type):
    """Hàm xử lý băm ngữ nghĩa cho Ẩm thực và Địa điểm du lịch."""
    if not os.path.exists(raw_file_path):
        print(f"[Cảnh báo] Không tìm thấy file: {raw_file_path}. Bỏ qua.")
        return

    with open(raw_file_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    processed_chunks = []

    for item in raw_data:
        item_id = item.get("id")
        title = clean_text(item.get("title"))
        district = clean_text(item.get("district")).title()
        category = clean_text(item.get("category"))
        sub_category = clean_text(item.get("sub_category"))
        address = clean_text(item.get("address", "Hà Nội"))
        price_range = clean_text(item.get("price_range", "N/A"))
        opening_hours = clean_text(item.get("opening_hours", "N/A"))

        # Lấy phần mô tả chi tiết để băm
        full_text = clean_text(item.get("description"))

        # --- TIẾN HÀNH BĂM THEO NGỮ NGHĨA NGUYÊN BẢN ---
        text_chunks = semantic_chunking(full_text, threshold_percentile=60)
        
        for idx, chunk_text in enumerate(text_chunks):
            # Ép ngữ cảnh cố định vào đầu chuỗi text của từng mảnh băm
            vector_text = f"{title} tại địa chỉ {address}, quận {district}. {chunk_text}"

            chunk_structure = {
                "chunk_id": f"{item_id}_chunk_{idx + 1}",
                "vector_text": vector_text,
                "metadata": {
                    "parent_id": item_id,
                    "city": "Hà Nội",
                    "title": title,
                    "category": category,
                    "sub_category": sub_category,
                    "district": district,
                    "price_range": price_range,
                    "opening_hours": opening_hours
                }
            }
            processed_chunks.append(chunk_structure)

    # Lưu kết quả xuống thư mục processed
    os.makedirs(os.path.dirname(processed_file_path), exist_ok=True)
    with open(processed_file_path, 'w', encoding='utf-8') as f:
        json.dump(processed_chunks, f, ensure_ascii=False, indent=2)

    print(f"-> Đã băm SEMANTIC [{data_type.upper()}]: Sinh ra {len(processed_chunks)} chunks ý nghĩa.")

if __name__ == "__main__":
    print("--- KHỞI CHẠY GIAI ĐOẠN : SEMANTIC CHUNKING ---")
    
    tasks = [
        {"raw": "data/raw/food_raw.json", "processed": "data/processed/food_chunks.json", "type": "food"},
        {"raw": "data/raw/travel_raw.json", "processed": "data/processed/travel_chunks.json", "type": "travel"}
    ]

    for task in tasks:
        process_file_semantic(task["raw"], task["processed"], task["type"])
        
    print("--- HOÀN THÀNH TIỀN XỬ LÝ NGỮ NGHĨA ---")