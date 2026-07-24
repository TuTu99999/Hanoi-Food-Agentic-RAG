import json
import os
from sentence_transformers import SentenceTransformer

# 1. Tải mô hình embedding siêu nhẹ đa ngôn ngữ (Free, Offline sau lần tải đầu)
print("Đang tải mô hình sinh Embedding (384 chiều)...")
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

def generate_embeddings_for_file(processed_file_path, output_file_path, data_type):
    """Đọc dữ liệu đã băm, sinh vector embedding và lưu lại."""
    if not os.path.exists(processed_file_path):
        print(f"[Cảnh báo] Không tìm thấy file dữ liệu đã băm: {processed_file_path}")
        return

    print(f"\n[Bắt đầu] Sinh Embedding cho nhóm: {data_type.upper()}")
    with open(processed_file_path, 'r', encoding='utf-8') as f:
        chunks = json.load(f)

    if not chunks:
        print(f"-> File {processed_file_path} không có dữ liệu để sinh vector.")
        return

    # Gom toàn bộ chuỗi text cần chuyển thành vector vào một danh sách để xử lý hàng loạt (Batch)
    texts_to_encode = [chunk["vector_text"] for chunk in chunks]
    
    # Tiến hành chuyển text thành Vector (Mảng số thực)
    print(f"-> Đang tính toán Vector cho {len(texts_to_encode)} chunks...")
    embeddings = model.encode(texts_to_encode, batch_size=32, show_progress_bar=True)

    # Ép ngược các vector dạng numpy array về dạng danh sách số thực (list of floats) và nhét vào cấu trúc dữ liệu
    for idx, chunk in enumerate(chunks):
        # Chuyển đổi sang kiểu list để có thể lưu được vào file JSON
        chunk["vector"] = embeddings[idx].tolist()
        
        # In kiểm tra thử chiều dữ liệu của chunk đầu tiên
        if idx == 0:
            print(f"   [Kiểm tra] Kích thước vector của chunk đầu tiên: {len(chunk['vector'])} chiều")

    # Lưu kết quả cuối cùng bao gồm cả Text, Metadata và Vector xuống thư mục cuối
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
    with open(output_file_path, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"[Thành công] Đã lưu dữ liệu kèm Vector vào: {output_file_path}")

if __name__ == "__main__":
    print("--- KHỞI CHẠY GIAI ĐOẠN : SINH EMBEDDING ---")
    
    
    tasks = [
        {
            "processed": "data/processed/food_chunks.json", 
            "output": "data/final/food_vector.json", 
            "type": "food"
        },
        {
            "processed": "data/processed/travel_chunks.json", 
            "output": "data/final/travel_vector.json", 
            "type": "travel"
        }
    ]

    for task in tasks:
        generate_embeddings_for_file(task["processed"], task["output"], task["type"])
        