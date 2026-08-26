# Giai đoạn 4 - Indexing và Hybrid Retrieval đa môn

## 1. Mục tiêu

Giai đoạn 4 biến các chunk có citation từ Giai đoạn 3 thành knowledge index có thể truy xuất. Mỗi môn và mỗi phiên bản kiến thức được cô lập, nhưng đều sử dụng chung một pipeline nên thêm môn lý luận chính trị mới không cần sửa code.

Phạm vi đã hoàn thành:

- Sinh embedding từ `vector_text` của chunk.
- Lưu vector artifact và manifest có hash kiểm chứng.
- Tạo Qdrant collection vật lý bất biến theo môn và knowledge version.
- Tạo alias hiện hành riêng cho từng môn.
- Tạo payload index cho các trường lọc quan trọng.
- Hybrid retrieval gồm vector search, BM25 và Reciprocal Rank Fusion (RRF).
- Bắt buộc lọc theo môn, phiên bản và knowledge version.
- Trả lại citation theo cùng schema của Giai đoạn 3.
- Bộ đánh giá Recall@k, Hit Rate@k, MRR, citation completeness và cross-course leakage.

## 2. Kiến trúc

```text
processed/chunks.json
        │
        ├── validate schema + chunks_sha256
        ▼
SentenceTransformer
        │
        ▼
indexed/vectors.json + embedding_manifest.json
        │
        ├── validate vector dimension + artifact hash
        ▼
Qdrant physical collection
        │
        └── course_<course_id>_current (alias)

Query + course_id
        ├── Dense retrieval trên Qdrant, có filter bắt buộc
        ├── BM25 retrieval trên đúng processed artifact
        └── RRF -> grounded chunks + citation
```

Pipeline food cũ không bị sửa thành schema học thuật. Module mới nằm trong `academic_retrieval/`, tránh làm hỏng chức năng cũ trong lúc hệ thống học tập chưa được nối vào chat.

## 3. Cấu trúc output

Sau Giai đoạn 3:

```text
data/courses/<course_id>/<version>/processed/
├── chunks.json
└── ingestion_manifest.json
```

Sau bước sinh embedding:

```text
data/courses/<course_id>/<version>/indexed/
├── vectors.json
└── embedding_manifest.json
```

`embedding_manifest.json` lưu:

- `course_id`
- `course_version`
- `knowledge_version`
- embedding model
- số chiều vector
- số point
- hash của `chunks.json`
- hash của `vectors.json`

Nếu nội dung artifact bị sửa ngoài pipeline, bước tiếp theo sẽ từ chối sử dụng.

## 4. Quy tắc đặt tên Qdrant

Ví dụ với môn `political_philosophy`:

```text
Physical collection:
course_political_philosophy_1_0_0_<knowledge_hash>

Active alias:
course_political_philosophy_current
```

Collection vật lý không bị ghi đè. Khi phiên bản mới đã upload và kiểm tra thành công, alias mới được chuyển sang collection đó. Collection cũ vẫn còn để rollback hoặc kiểm tra lịch sử.

Hai môn khác nhau luôn có alias khác nhau, ví dụ:

```text
course_political_philosophy_current
course_hochiminh_thought_current
```

## 5. Cách chạy

### 5.1. Kiểm tra processed artifact

Lệnh này không tải model và không ghi file:

```powershell
python -m scripts.build_course_embeddings data\courses\political_philosophy\1.0.0\processed --dry-run
```

### 5.2. Sinh embedding

Nếu model đã có trong cache:

```powershell
python -m scripts.build_course_embeddings data\courses\political_philosophy\1.0.0\processed
```

Lần đầu cần cho phép tải model:

```powershell
python -m scripts.build_course_embeddings data\courses\political_philosophy\1.0.0\processed --allow-download
```

Mặc định sử dụng model trong `EMBEDDING_MODEL`. `--force` chỉ dùng trong lúc phát triển; với dữ liệu thật nên tăng version thay vì ghi đè.

### 5.3. Kiểm tra vector artifact trước khi upload

```powershell
python -m scripts.upload_course_index data\courses\political_philosophy\1.0.0\indexed --dry-run
```

Dry-run hiển thị collection và alias sẽ được sử dụng nhưng không kết nối Qdrant.

### 5.4. Upload và kích hoạt alias

```powershell
python -m scripts.upload_course_index data\courses\political_philosophy\1.0.0\indexed
```

Muốn upload để review nhưng chưa chuyển alias:

```powershell
python -m scripts.upload_course_index data\courses\political_philosophy\1.0.0\indexed --no-alias-switch
```

### 5.5. Tìm kiếm thử

```powershell
python -m scripts.search_course_knowledge `
  data\courses\political_philosophy\1.0.0\processed `
  data\courses\political_philosophy\1.0.0\indexed `
  political_philosophy `
  "Quy luật lượng và chất là gì?"
```

Có thể thử riêng từng nhánh bằng `--mode dense`, `--mode keyword` hoặc `--mode hybrid`.

## 6. Cơ chế chống lẫn môn

Dense retrieval luôn gửi ba điều kiện vào Qdrant:

```text
course_id = môn đang học
course_version = phiên bản đang dùng
knowledge_version = đúng bản build đã kiểm chứng
```

BM25 index chỉ được khởi tạo từ một môn và một knowledge version. Sau khi Qdrant trả kết quả, service kiểm tra lại payload. Nếu Qdrant trả chunk của môn khác hoặc version khác, hệ thống báo lỗi thay vì đưa evidence đó cho LLM.

`search()` cũng yêu cầu truyền `course_id`. Nếu agent gọi tool với sai môn so với index đang mở, truy vấn bị từ chối trước khi gọi embedding hoặc Qdrant.

## 7. Citation và grounding

Mỗi retrieval hit trả lại:

```text
chunk_id
course_id
course_version
knowledge_version
document_id
section_id
content
citation
retrieval_sources: dense / keyword
```

Citation vẫn chứa tên tài liệu, đường dẫn nguồn, loại nguồn và vị trí trang/dòng/đoạn. Retrieval không tự sinh citation bằng LLM.

## 8. Đánh giá retrieval

Template evaluation nằm tại:

```text
course_packages/_template/evaluation/retrieval_cases.example.json
```

Sau khi thay `expected_chunk_ids` bằng ID thật từ `chunks.json`, chạy:

```powershell
python -m scripts.evaluate_course_retrieval `
  data\courses\political_philosophy\1.0.0\processed `
  data\courses\political_philosophy\1.0.0\indexed `
  course_packages\political_philosophy\evaluation\retrieval_cases.json `
  --mode hybrid `
  --output data\evaluation\political_philosophy_retrieval.json
```

Các metric hiện có:

| Metric | Ý nghĩa |
| --- | --- |
| `hit_rate_at_k` | Tỷ lệ câu hỏi có ít nhất một chunk đúng trong top-k |
| `recall_at_k` | Tỷ lệ các chunk kỳ vọng được tìm thấy |
| `mean_reciprocal_rank` | Chunk đúng đầu tiên đứng cao đến đâu |
| `citation_completeness` | Kết quả có đủ tài liệu nguồn và vị trí citation |
| `cross_course_leakage_count` | Số hit trả về sai môn |
| `empty_result_count` | Số câu hỏi không tìm được evidence |

Chưa công bố điểm Recall@5 thật vì chưa có bộ câu hỏi và tài liệu chính thức của môn. Khi làm thực nghiệm, môn chính cần tối thiểu 100 retrieval cases; môn minh chứng cần tối thiểu 30 cases theo phạm vi Giai đoạn 1.

## 9. Kiểm thử kỹ thuật

Test riêng của Giai đoạn 4 bao phủ:

- Sinh vector bằng fake encoder, không tải model thật.
- Phát hiện `chunks.json` bị sửa sai hash.
- Phát hiện vector sai schema, sai dimension hoặc sai version.
- Point ID ổn định theo `chunk_id`.
- Collection bất biến, không upload đè.
- Alias riêng cho từng môn.
- Payload index và citation được upload.
- Hybrid retrieval hợp nhất dense + keyword.
- Keyword-only không gọi model hoặc Qdrant.
- Chặn sai `course_id` trước truy vấn.
- Chặn payload rò từ môn khác.
- Upload, alias, filter và dense search chạy end-to-end trên Qdrant local in-memory.
- Tính Recall@k, MRR, citation completeness và leakage.

Kết quả toàn bộ test suite tại thời điểm hoàn thành:

```text
Ran 186 tests
OK (skipped=1)
```

Test được skip là integration migration PostgreSQL cần database riêng, không phải lỗi indexing hoặc retrieval.

## 10. Giới hạn có chủ đích

Giai đoạn 4 chưa làm:

- Concept graph expansion hoặc GraphRAG.
- Kết nối academic retriever vào endpoint chat cũ.
- Knowledge Agent và Orchestrator Agent.
- API upload/index trên giao diện quản trị.
- Đồng bộ trạng thái `PROCESSING`, `VALIDATED`, `ACTIVE` với database trong CLI.
- Chạy benchmark semantic thật khi chưa có dữ liệu môn học thật.

Các giới hạn này giữ Giai đoạn 4 tập trung vào retrieval đáng tin cậy. Giai đoạn tiếp theo nên đóng gói retrieval thành academic tool, xây Knowledge Agent và nối Orchestrator để bắt đầu luồng agentic AI đúng đề tài.
