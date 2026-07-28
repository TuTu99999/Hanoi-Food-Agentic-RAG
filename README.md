# Agentic Hybrid RAG Food Hà Nội

Ứng dụng gồm FastAPI, React/Vite, PostgreSQL, Qdrant, LangGraph và một
Agentic Hybrid RAG tập trung vào ẩm thực Hà Nội. LLM dùng GitHub Models qua
OpenAI-compatible API.

## Dịch vụ cần có

- Python 3.10.11 (được pin trong `.python-version`)
- PostgreSQL
- Qdrant tại `localhost:6333` (có thể chạy bằng Docker)
- Node.js/npm

## Cấu hình

Sao chép `.env.example` thành `.env`, sau đó điền URL database, JWT secret và
GitHub token. Không commit `.env`. Vite có cấu hình development riêng tại
`frontend/.env.example`.

Backend đọc alias từ `QDRANT_COLLECTION` và mặc định dùng
`hanoi_food_current`. Alias Food-only này phải được chuyển sang collection
version mới sau khi uploader kiểm tra dữ liệu thành công. Ưu tiên cấu hình kết nối bằng
`QDRANT_URL`; nếu FastAPI chạy trong Docker Compose, dùng URL service
`http://qdrant:6333`.

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

Frontend chỉ lưu `session_id` hiện tại theo user trong `sessionStorage`; nội dung
tin nhắn luôn được khôi phục từ backend. Logout, session không còn tồn tại hoặc
session không thuộc user hiện tại sẽ tự xóa trạng thái local.

RAG, embedding model, BM25 index, ML query router và LangGraph được warm-up
trong FastAPI lifespan nên startup có thể mất thêm vài giây, đổi lại câu hỏi
đầu tiên không phải tải model. Khi shutdown, backend đóng OpenAI clients,
Qdrant client và SQLAlchemy pool.

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

Pipeline hiện chỉ index Food. Trong 420 record nguồn có 418 record ẩm thực hợp
lệ; hai record sai category được giữ trong raw data để review nhưng không đưa
vào collection mới. Kết quả hiện tại là 624 chunk, giới hạn 90 token và overlap
15 token.

Metadata giá và giờ mở cửa được chuẩn hóa song song với giá trị raw:

- `price_min`, `price_max`, `price_currency`, `price_status`
- `opening_intervals`, `closes_next_day`, `opening_schedule_scope`
- `sub_category_normalized`, `tags_normalized`

Chạy từ thư mục gốc:

```powershell
python -m embedding.process_data --local-files-only
python -m embedding.generate_embeddings --local-files-only
python -m embedding.upload_to_qdrant --dry-run
python -m embedding.upload_to_qdrant
```

Uploader tạo collection vật lý `hanoi_food_v1`, kiểm tra point count và payload
mẫu, sau đó mới chuyển alias `hanoi_food_current`. Collection cũ không bị xóa
nên có thể rollback. Sau khi upload thành công, đặt:

```dotenv
QDRANT_COLLECTION=hanoi_food_current
```

rồi restart backend.

Mỗi lần thay đổi dữ liệu hoặc chunking, dùng version collection mới thay vì
ghi đè version cũ:

```powershell
python -m embedding.generate_embeddings `
  --local-files-only `
  --output data/final/hanoi_food_v2.json

python -m embedding.upload_to_qdrant `
  --input data/final/hanoi_food_v2.json `
  --collection hanoi_food_v2 `
  --alias hanoi_food_current `
  --expected-points 624 `
  --expected-parents 418
```

Hai count trên là chốt an toàn của dữ liệu hiện tại. Nếu đã review và chủ động đổi
dữ liệu/chunking, thay chúng bằng số chunk và số food record mà pipeline vừa in ra.

Đánh giá retrieval, recall@k, district filter và latency:

```powershell
python -m embedding.evaluate_retrieval `
  --mode semantic `
  --thresholds 0.45 0.5 0.55 `
  --top-k 5 `
  --output data/evaluation/latest_retrieval_report.json
```

Sau khi chọn threshold cho nhánh dense, chạy lại với `--mode hybrid` để kiểm tra
toàn bộ exact + BM25 + semantic. Evaluator sẽ không đề xuất threshold nếu một
retrieval branch đang lỗi, tránh coi kết quả fallback là một lần đo đầy đủ.

Đánh giá ML query router trên bộ calibration tách khỏi training:

```powershell
python -m rag.evaluate_query_router --min-accuracy 0.80
```

Threshold mặc định `0.35` được chọn từ bộ calibration hiện tại: intent accuracy
`88,57%`, high-confidence coverage `68,57%` và high-confidence accuracy
`95,83%`. Đây là số calibration, không phải kết quả trên một hidden test set.
Prediction dưới ngưỡng không bị loại; planner chuyển về hybrid.

Cài toàn bộ dependency runtime, test và evaluation:

```powershell
python -m pip install -r requirements.txt
```

Chạy Ragas thật với Context Precision, Context Recall, Faithfulness và Answer
Relevancy:

```powershell
python eval_ragas.py `
  --output reports/ragas.json
```

Chạy DeepEval với hard constraint deterministic, G-Eval và conversation eval
cho follow-up:

```powershell
python eval_deepeval.py `
  --output reports/deepeval.json
```

Hai lệnh live cần collection Qdrant đã có dữ liệu và token LLM. Không dùng điểm
LLM judge làm gate duy nhất vì kết quả có dao động; unit test, Recall@K, MRR,
router accuracy và hard constraint deterministic vẫn là các kiểm tra chất lượng
chính. Live evaluation hiện được chạy thủ công ở local để dùng Qdrant sẵn có.

## Docker

Qdrant trong Compose dùng external volume `qdrant_storage`. Máy mới chỉ cần tạo
volume một lần:

```powershell
docker volume create qdrant_storage
```

Máy hiện tại đã có volume này với alias
`hanoi_food_current -> hanoi_food_v1`; không upload lại collection mặc định.
Container Qdrant cũ phải được dừng trước khi Compose nhận quyền quản lý volume:

```powershell
docker stop strange_gates
docker compose up -d qdrant
```

Sau khi kiểm tra `http://localhost:6333/healthz`, chạy toàn bộ hệ thống:

```powershell
docker compose up --build -d
docker compose ps
```

Mở frontend tại `http://localhost:3000`, API tại `http://localhost:8000`.
Backend tự chạy `alembic upgrade head` trước khi khởi động. Lần chạy Docker đầu
tiên, service `model-cache` tải embedding model vào volume `huggingface_cache`.
Backend chỉ khởi động sau khi model đã sẵn sàng và luôn dùng local cache, nên
request đầu tiên không phải tải model.

Compose không tự tạo vector knowledge base. Khi Qdrant mới hoàn toàn, chạy
pipeline build/upload vào collection version mới rồi mới dùng chat:

```powershell
python -m embedding.process_data --local-files-only
python -m embedding.generate_embeddings --local-files-only
python -m embedding.upload_to_qdrant --collection hanoi_food_v2
```

Dừng container nhưng giữ database:

```powershell
docker compose down
```

External volume `qdrant_storage` không bị xóa bởi `docker compose down -v`.
Lệnh đó vẫn xóa PostgreSQL và model cache do Compose quản lý, vì vậy chỉ dùng
khi chủ động reset các dữ liệu này.

`compose.prod.yml` dùng image đã publish, không public PostgreSQL/Qdrant/backend
ra host. Production phải truyền secret qua environment hoặc secret manager,
không ghi chúng vào image hay commit vào Git. Qdrant production bắt buộc có
`QDRANT_API_KEY`, external volume phải được tạo trước và server phải có HTTPS
reverse proxy/load balancer ở phía trước frontend.

## GitHub Actions CI

- `CI`: unit test backend, migration thật trên PostgreSQL, ML router benchmark,
  unit test/build frontend và build thử hai Docker image.

CI tự chạy khi push vào `main`, nhánh `feature/**` hoặc tạo pull request vào
`main`. Các giá trị `ci-test-...` trong workflow chỉ là cấu hình giả cho test;
không cần tạo GitHub Secret và không được dùng trong production.

Ragas/DeepEval tiếp tục chạy bằng các lệnh local phía trên nên không cần
self-hosted runner. Publish image và deploy production được để dành cho giai đoạn
sau; hiện repository tập trung vào CI ổn định và kết quả kỹ thuật phục vụ
portfolio.

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

## Agentic Hybrid RAG v1

- Query router local dùng TF-IDF word/character và Logistic Regression. Dataset
  seed có 7 intent; prediction thiếu hoặc confidence thấp luôn fallback về
  hybrid search an toàn.
- LangGraph điều phối `analyze -> plan -> retrieve -> grade`. Chỉ evidence
  `low_relevance` được rewrite và retry, tối đa một lần.
- Exact-name, BM25 và semantic Qdrant là ba nhánh độc lập; kết quả được hợp nhất
  bằng Reciprocal Rank Fusion, không cộng trực tiếp các score khác thang đo.
- Exact-name chắc chắn có thể bỏ qua embedding để giảm latency.
- Hard filter không có dữ liệu, metadata bị thiếu, tên quán mơ hồ hoặc tool lỗi
  đều không tự nới filter và không retry vô ích.
- Runtime luôn ép `domain=food`. Các file travel cũ chỉ được giữ làm archive/rollback,
  không còn nằm trong pipeline build, retrieval hoặc evaluation đang hoạt động.
- Point ID là UUID ổn định sinh từ `chunk_id`.
- District được chuẩn hóa và allowlist để nhận cả `Hoàn Kiếm` lẫn
  `hoan kiem`.
- Greeting được trả trực tiếp, không gọi Qdrant hoặc LLM.
- Backend forward trực tiếp từng delta từ LLM xuống SSE, không giả lập
  streaming bằng cách chia câu trả lời đã hoàn thành.
- Mỗi câu hỏi dùng tối đa 3 lượt hội thoại hoàn chỉnh gần nhất và 6.000 ký tự.
- Nếu stream bị ngắt, phần nội dung đã nhận được vẫn được lưu với trạng thái
  `error`; lượt lỗi không được đưa lại vào memory.
- Graph v1 không dùng checkpointer vì không có bước pause/resume; PostgreSQL
  chat history vẫn là nguồn dữ liệu thật, tránh lưu state trùng lặp.
