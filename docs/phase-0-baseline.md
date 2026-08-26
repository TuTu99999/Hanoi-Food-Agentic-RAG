# Giai đoạn 0 - Baseline trước khi chuyển sang trợ lý học tập đa tác tử

## 1. Mục tiêu của giai đoạn này

Giai đoạn 0 chỉ làm ba việc đơn giản:

1. Giữ lại một mốc ổn định của project ẩm thực hiện tại.
2. Kiểm tra những phần nào có thể tái sử dụng.
3. Chỉ ra những phần đang gắn cứng với ẩm thực để xử lý ở các giai đoạn sau.

Giai đoạn này **chưa đổi dữ liệu**, **chưa tạo agent mới** và **chưa thay workflow hiện tại**.

## 2. Mốc baseline

| Hạng mục | Giá trị |
| --- | --- |
| Ngày kiểm tra | 2026-08-25 |
| Nhánh nguồn | `feature/be` |
| Commit baseline | `754216b40f858dc3abf6f8d740b30bae82dc6854` |
| Nhánh phát triển mới | `feature/political-learning-platform` |
| Python | `3.10.11` |
| Dữ liệu gốc | 792 địa điểm |
| Dữ liệu sau xử lý | 820 chunks |
| Knowledge version | `food-dbba6314ac89` |

Baseline được giữ bằng commit ở trên. Khi chuyển đổi hệ thống, không sửa hoặc xóa dữ liệu cũ trước khi chức năng mới có test thay thế.

## 3. Kết quả kiểm tra

| Kiểm tra | Kết quả |
| --- | --- |
| Backend unit/integration tests | 155 tests run, 1 skipped, 0 failed |
| Retrieval cases | 80 cases hợp lệ |
| Lexical retrieval | Accuracy 100%, Recall@5 100%, MRR 1.000 |
| Query router | Accuracy 96% trên 175 cases |
| Frontend tests | 15 passed |
| Frontend production build | Thành công |

Ghi chú:

- Test PostgreSQL migration được skip theo chủ đích vì cần biến `RUN_P0_POSTGRES_MIGRATION_TEST=1` và một PostgreSQL riêng.
- Môi trường chưa cài `pytest`, vì vậy baseline backend được chạy bằng `python -m unittest discover -s tests -v`.
- Một số log `ERROR` xuất hiện trong lúc test là tình huống lỗi giả lập; toàn bộ test liên quan vẫn pass.
- Trên máy Windows này nên dùng `npm.cmd` thay cho `npm` vì PowerShell đang chặn `npm.ps1`.

## 4. Những phần nên giữ lại

Các phần dưới đây đủ tốt để làm nền cho đồ án mới:

### Hạ tầng backend

- FastAPI và cấu trúc router/service.
- Đăng ký, đăng nhập, JWT và phân quyền phiên chat.
- PostgreSQL, SQLAlchemy và Alembic migration.
- Chat history, streaming và idempotency.
- Rate limit, timeout, retry và circuit breaker.
- Health check, logging, metrics và LangSmith tracing.

### Hạ tầng RAG

- Sentence Transformer embedding.
- Qdrant client và cơ chế collection alias/version.
- BM25, vector retrieval và Reciprocal Rank Fusion.
- Kiểm tra đồng nhất `knowledge_version`.
- Retrieval evaluation và các nguyên tắc chống hallucination.

### Hạ tầng Agentic AI

- LangGraph và cách quản lý state.
- Các bước analyze, plan, retrieve, grade và rewrite.
- Vòng retry có giới hạn.
- Cơ chế chỉ sinh câu trả lời khi có đủ evidence.

### Frontend

- React/Vite, routing và authentication context.
- Giao diện chat, lịch sử chat và streaming.
- Render Markdown an toàn.
- Quản lý session theo từng user.

## 5. Những phần cần tổng quát hóa

Những phần này có thể tái sử dụng ý tưởng nhưng phải bỏ hard-code ẩm thực:

| Khu vực | Vấn đề hiện tại | Hướng xử lý sau này |
| --- | --- | --- |
| `core/config.py` | Có `FOOD_CATALOG_PATH`, collection và tên project Hà Nội Food | Chuyển sang Course Registry và cấu hình theo `course_id` |
| `rag/agentic_graph.py` | State chứa quận, giá, giờ mở cửa và food signal | Tạo learning state: môn, mục tiêu, mastery và concept yếu |
| `rag/query_router.py` | Intent phục vụ tìm món/quán | Đổi thành intent học tập: hỏi kiến thức, kiểm tra, lập kế hoạch |
| `rag/Rag.py` | Prompt và output dành cho quán ăn | Tách prompt dùng chung và course prompt profile |
| `embedding/process_data.py` | Schema dữ liệu là địa điểm ăn uống | Tạo Course Package ingestion pipeline |
| `embedding/lexical_index.py` | Index theo tên quán, món, quận và giá | Index theo chương, concept, objective và thuật ngữ |
| `embedding/retrieval_engine.py` | Chỉ chấp nhận domain `food` | Lọc theo `course_id` và `course_version` |
| `embedding/upload_to_qdrant.py` | Collection cố định `hanoi_food_*` | Tạo collection/alias theo từng môn và phiên bản |
| `database/models.py` | Có Food, Restaurant, Travel và Favorite | Giữ User/Chat; bổ sung Course, Concept, Mastery, Quiz và StudyPlan |
| `schemas/chat.py` | Request có `district` và `nearby` | Thay bằng `course_id`, `goal` và learning context |
| Frontend Chat | Có tìm gần tôi, bản đồ và nội dung ẩm thực | Giữ chat; thay bằng chọn môn, citation và tiến độ học |
| Evaluation | Dataset chỉ chứa câu hỏi ẩm thực | Tạo eval dataset riêng theo từng môn |

## 6. Những phần không mang sang hệ thống học tập

Các thành phần sau là tính năng riêng của project cũ, không thuộc đề tài mới:

- `scripts/import_osm_hanoi_food.py`
- `scripts/crawl_foody_hanoi.py`
- `rag/map_links.py`
- `embedding/geo.py`
- Nearby Food Finder và bộ lọc bán kính.
- Bộ lọc quận, giá, giờ mở cửa, cuisine và menu.
- Dữ liệu OSM/Foody và Google Maps link.
- Dashboard/metric có tên `hanoi_food_*` sẽ được đổi tên sau.

Không xóa ngay các file này. Chỉ ngừng sử dụng sau khi luồng học tập mới có test thay thế.

## 7. Quy tắc để không làm project rối

1. Mỗi giai đoạn chỉ thay một nhóm chức năng.
2. Không đổi tên hàng loạt toàn project ngay từ đầu.
3. Giữ backend chạy được sau mỗi thay đổi.
4. Code dùng chung không được chứa tên `Triết học Mác - Lênin`.
5. Mọi dữ liệu môn học sau này phải đi qua `course_id` và `course_version`.
6. Agent không đọc database trực tiếp; agent gọi tool nghiệp vụ.
7. Hoàn thiện một môn chính trước, sau đó dùng môn thứ hai để kiểm tra khả năng mở rộng.

## 8. Lệnh kiểm tra baseline

Chạy từ thư mục gốc:

```powershell
python -m unittest discover -s tests -v
python -m scripts.build_retrieval_cases --check
python -m embedding.evaluate_retrieval --mode lexical --top-k 5 --min-accuracy 0.90
python -m rag.evaluate_query_router --min-accuracy 0.90
```

Kiểm tra frontend:

```powershell
Set-Location frontend
npm.cmd test
npm.cmd run build
Set-Location ..
```

## 9. Điều kiện kết thúc Giai đoạn 0

- [x] Repository ban đầu sạch.
- [x] Ghi lại branch và commit baseline.
- [x] Tạo branch riêng cho đồ án mới.
- [x] Backend tests chạy thành công.
- [x] Retrieval và router baseline đạt ngưỡng.
- [x] Frontend tests và production build thành công.
- [x] Phân loại phần giữ lại, phần cần tổng quát hóa và phần không sử dụng.
- [x] Chưa thay đổi logic chạy của hệ thống.

Giai đoạn tiếp theo nên là **Giai đoạn 1: chốt phạm vi đồ án, use case và tiêu chí đánh giá**, chưa bắt đầu viết multi-agent ngay.
