# RAG Food & Travel Hà Nội

Ứng dụng gồm FastAPI, React/Vite, PostgreSQL, Qdrant và một RAG pipeline dùng
GitHub Models.

## Dịch vụ cần có

- Python 3.10.11 (được pin trong `.python-version`)
- PostgreSQL
- Qdrant tại `localhost:6333` (có thể chạy bằng Docker)
- Node.js/npm

## Cấu hình

Sao chép `.env.example` thành `.env`, sau đó điền URL database, JWT secret và
GitHub token. Không commit `.env`. Vite có cấu hình development riêng tại
`frontend/.env.example`.

Backend mặc định truy vấn Qdrant qua alias `hanoi_knowledge_current` tại
`http://localhost:6333`. Ưu tiên cấu hình bằng `QDRANT_URL`; `QDRANT_HOST` và
`QDRANT_PORT` được giữ làm fallback. Nếu FastAPI chạy trong Docker Compose,
dùng URL service như `http://qdrant:6333`.

`LLM_BASE_URL`, `LLM_MODEL` và `EMBEDDING_MODEL` cũng được đọc từ environment.
Nếu đổi embedding model, phải tạo lại toàn bộ vectors trong collection version
mới rồi chạy evaluation trước khi đổi alias.

Timeout, retry có exponential backoff + jitter và circuit breaker dùng các biến
`QDRANT_TIMEOUT_SECONDS`, `EXTERNAL_RETRY_*` và `CIRCUIT_BREAKER_*`. Giá trị
mặc định trong `.env.example` phù hợp để bắt đầu, không cần chỉnh khi chạy local.

Production bắt buộc khai báo `APP_ENV=production`, `CORS_ORIGINS` HTTPS,
`GITHUB_TOKEN` hợp lệ, JWT secret tối thiểu 32 byte và
`AUTH_COOKIE_SECURE=true`. Backend sẽ từ chối khởi động nếu cấu hình không hợp
lệ.

Ở môi trường development, frontend và backend dùng cùng origin thông qua Vite
proxy `/api`. Hãy mở frontend bằng URL mà Vite in ra; không trộn URL
`localhost` và `127.0.0.1` cho các request API.

## Cài đặt

```powershell
python -m pip install -r requirements.txt
Set-Location frontend
npm install
Set-Location ..
```

## Migration database

Backend không còn tự chạy `Base.metadata.create_all()`. Trước khi khởi động
phiên bản P0, hãy backup PostgreSQL rồi chạy:

```powershell
alembic upgrade head
```

Khi `DB_SCHEMA_CHECK=true` (mặc định), backend sẽ từ chối khởi động nếu database
chưa ở revision `20260727_0002`; nhờ đó code mới không vô tình chạy trên bảng
`messages` cũ.

Migration P0 chuyển mỗi bản ghi lịch sử cũ `{question, answer}` thành hai
message có thứ tự ổn định:

```text
user(question) -> assistant(answer)
```

Migration cũng thêm `turn_id`, `position`, `status`, `next_position`, các
constraint chống trùng và `ON DELETE CASCADE` từ session xuống message.

Kiểm tra revision hiện tại:

```powershell
alembic current
alembic history
```

Không chạy downgrade baseline trên database có dữ liệu. Khi cần rollback, ưu
tiên khôi phục bản backup đã tạo trước migration.

## Chạy ứng dụng

Terminal backend:

```powershell
uvicorn main:app --reload
```

Terminal frontend:

```powershell
Set-Location frontend
npm run dev
```

Frontend chạy cổng `3000` và mặc định proxy `/api` sang FastAPI tại
`http://127.0.0.1:8000`. Có thể đổi bằng `VITE_API_PROXY_TARGET` trong
`frontend/.env`.

RAG và embedding model được warm-up trong FastAPI lifespan nên startup có thể
mất thêm vài giây, đổi lại câu hỏi đầu tiên không phải chờ tải model. Khi shutdown,
backend đóng OpenAI clients, Qdrant client và SQLAlchemy pool.

Runtime mặc định dùng `EMBEDDING_LOCAL_FILES_ONLY=true`, vì vậy model phải được
tải sẵn hoặc đóng gói trong image. Máy mới chưa có model có thể đặt tạm `false`
cho lần tải đầu, sau đó chuyển lại `true`.

Health check:

```text
GET /health/live   -> process FastAPI còn hoạt động
GET /health/ready  -> PostgreSQL, Qdrant và trạng thái LLM/RAG
```

`ready` không gửi prompt tới LLM để tránh tốn token; nó kiểm tra client đã cấu
hình và circuit breaker chưa mở. PostgreSQL và Qdrant được kiểm tra kết nối thật.

Mỗi response có `X-Request-ID`. Backend log JSON gồm request ID, session ID,
route, status và latency; lỗi nội bộ chỉ nằm trong log, không trả exception ra frontend.

## Xây dựng knowledge base

Pipeline P1 dùng chung một collection cho food và travel. Chunk được giới hạn
90 token, overlap 15 token và giữ đầy đủ metadata.

Chạy từ thư mục gốc:

```powershell
python -m embedding.process_data --local-files-only
python -m embedding.generate_embeddings
python -m embedding.upload_to_qdrant --dry-run
python -m embedding.upload_to_qdrant
```

Uploader tạo collection vật lý `hanoi_knowledge_v2`, kiểm tra point count và
payload mẫu, sau đó mới chuyển alias `hanoi_knowledge_current`. Collection cũ
không bị xóa nên có thể dùng để rollback.

Mỗi lần thay đổi dữ liệu hoặc chunking, dùng version collection mới thay vì
ghi đè version cũ:

```powershell
python -m embedding.generate_embeddings `
  --output data/final/hanoi_knowledge_v3.json

python -m embedding.upload_to_qdrant `
  --input data/final/hanoi_knowledge_v3.json `
  --collection hanoi_knowledge_v3
```

Đánh giá retrieval, recall@k, district filter và latency:

```powershell
python -m embedding.evaluate_retrieval `
  --thresholds 0.45 0.5 0.55 `
  --top-k 5 `
  --output data/evaluation/latest_retrieval_report.json
```

Đánh giá E2E correctness, faithfulness, district filter, latency, token và chi
phí ước tính:

```powershell
python eval_ragas.py `
  --input-price-per-million 0 `
  --output-price-per-million 0 `
  --output data/evaluation/latest_rag_report.json
```

Hai mức giá mặc định bằng `0` vì giá model thay đổi theo nhà cung cấp; điền giá
hiện tại để tính cost. Lệnh trên gọi thêm một LLM judge cho faithfulness. Muốn
chạy smoke test không tốn lượt judge:

```powershell
python eval_ragas.py --skip-faithfulness-judge
```

## Contract P0

- Browser auth dùng HttpOnly cookie; API client có thể dùng Bearer header.
- Request thay đổi dữ liệu dùng cookie phải có `Origin` hoặc `Referer` hợp lệ;
  Bearer-only API client không mang auth cookie thì không cần CSRF check.
- `GET /api/auth/me` kiểm tra phiên đăng nhập.
- `POST /api/chat/stream` yêu cầu đăng nhập, kiểm tra ownership và lưu lịch sử.
- SSE dùng các event `session`, `token`, `done`, `error`.
- `GET /api/history/{session_id}` trả message `{role, content, status, ...}`.
- Chat được giới hạn theo user bằng dữ liệu PostgreSQL để hoạt động đồng nhất
  giữa nhiều worker.

## Contract P1

- Food và travel nằm chung collection, phân biệt bằng metadata `domain`.
- Point ID là UUID ổn định sinh từ `chunk_id`.
- Payload giữ title, address, district, giá, giờ mở cửa, category và tags.
- District/category được chuẩn hóa để filter không phụ thuộc dấu hoặc viết hoa.
- Retrieval lọc từng document theo threshold, sau đó rerank nhẹ theo tên và
  địa chỉ, đồng thời gộp các chunk cùng địa điểm.
- Greeting được trả trực tiếp, không gọi Qdrant hoặc LLM.
- Backend forward trực tiếp từng delta từ LLM xuống SSE, không giả lập
  streaming bằng cách chia câu trả lời đã hoàn thành.
- Mỗi câu hỏi dùng tối đa 3 lượt hội thoại hoàn chỉnh gần nhất và 6.000 ký tự.
- Nếu stream bị ngắt, phần nội dung đã nhận được vẫn được lưu với trạng thái
  `error`; lượt lỗi không được đưa lại vào memory.
