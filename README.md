# Trợ lý học tập Agentic AI đa tác tử

Đồ án phát triển trợ lý học tập đa tác tử cho các môn lý luận chính trị bằng
FastAPI, PostgreSQL, Qdrant, LangGraph và Gemini/Kimi qua OpenAI-compatible API.
Luồng ẩm thực Hà Nội cũ vẫn được giữ làm baseline trong thời gian chuyển đổi;
phần học thuật mới nằm trong `academic_agents/`, `academic_retrieval/`,
`assessment/`, `planning/`, `automation/`, `academic_mcp/` và các tài liệu
`docs/phase-*`.

Mỗi địa điểm được đề xuất có nút mở Google Maps. Link ưu tiên địa chỉ đường/số
nhà vì tọa độ cộng đồng OSM có thể sai lệch, và chỉ dùng tọa độ làm fallback khi
thiếu địa chỉ cụ thể. Link không cần API key và để Google Maps dùng vị trí hiện
tại của thiết bị làm điểm xuất phát.

Nearby Food Finder chỉ xin quyền vị trí sau khi người dùng bấm `Gần tôi`. Tọa độ
được gửi trong đúng request chat đang chạy để lọc bán kính bằng Qdrant GEO và
Haversine, không được lưu vào history, database, log hoặc LangSmith trace. FE chỉ
giữ vị trí trong state của trang Chat; reload hoặc rời trang sẽ xóa. Khoảng cách
hiển thị là ước tính theo tọa độ OSM. Production phải dùng HTTPS để browser cho
phép Geolocation API.

## Dịch vụ cần có

- Python 3.10.11 (được pin trong `.python-version`)
- PostgreSQL
- Qdrant tại `localhost:6333` (có thể chạy bằng Docker)
- Node.js/npm
- Docker Compose nếu chạy toàn bộ stack và dashboard monitoring

## Cấu hình

Sao chép `.env.example` thành `.env`, sau đó điền URL database, JWT secret và
Gemini API key. Không commit `.env`. Vite có cấu hình development riêng tại
`frontend/.env.example`.

Backend đọc alias từ `QDRANT_COLLECTION` và mặc định dùng
`hanoi_food_current`. Alias Food-only này phải được chuyển sang collection
version mới sau khi uploader kiểm tra dữ liệu thành công. Ưu tiên cấu hình kết nối bằng
`QDRANT_URL`; nếu FastAPI chạy trong Docker Compose, dùng URL service
`http://qdrant:6333`.

`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_REASONING_EFFORT`,
`LLM_MAX_OUTPUT_TOKENS` và `EMBEDDING_MODEL` cũng được đọc từ environment.
Khi `LLM_API_KEY` trống, backend dùng `GEMINI_API_KEY`. RAG mặc định dùng
`reasoning_effort=minimal` để ưu tiên câu trả lời grounded, nhanh và không để
reasoning ẩn chiếm hết giới hạn output.
Nếu đổi embedding model, phải tạo lại toàn bộ vectors trong collection version
mới rồi chạy evaluation trước khi đổi alias.

LangSmith tracing là tùy chọn và mặc định tắt. Để trace LangGraph, hybrid
retrieval và LLM streaming, khai báo trong `.env` hoặc deployment secrets:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=replace-with-your-langsmith-key
LANGSMITH_PROJECT=hanoi-food-agentic-rag
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_WORKSPACE_ID=replace-when-required
```

Không commit API key. Nếu bật tracing nhưng chưa có key, backend tự tắt
LangSmith và vẫn khởi động bình thường. Trace không gắn raw user ID, session ID,
cookie hoặc JWT. LangSmith vẫn nhận câu hỏi, context retrieval và câu trả lời để
debug RAG; không bật tracing cho dữ liệu nhạy cảm nếu chưa có bước redaction.

Timeout, retry có exponential backoff + jitter và circuit breaker dùng các biến
`QDRANT_TIMEOUT_SECONDS`, `EXTERNAL_RETRY_*` và `CIRCUIT_BREAKER_*`. Giá trị
mặc định trong `.env.example` phù hợp để bắt đầu, không cần chỉnh khi chạy local.

Production bắt buộc khai báo `APP_ENV=production`, `CORS_ORIGINS` HTTPS,
`TRUSTED_HOSTS`, `LLM_API_KEY` hợp lệ, JWT secret tối thiểu 32 byte và
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
chưa ở revision `20260826_0008`; nhờ đó code mới không vô tình chạy trên bảng
`messages` cũ.

Migration P0 chuyển mỗi bản ghi lịch sử cũ `{question, answer}` thành hai
message có thứ tự ổn định:

```text
user(question) -> assistant(answer)
```

Migration cũng thêm `turn_id`, `position`, `status`, `next_position`, các
constraint chống trùng và `ON DELETE CASCADE` từ session xuống message.
Hai migration tiếp theo thêm `token_version`, rate-limit bucket, UUID
`client_request_id` và index phục vụ cursor pagination.

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
GET /metrics       -> Prometheus metrics trong mạng nội bộ
```

`ready` không gửi prompt tới LLM để tránh tốn token; nó kiểm tra client đã cấu
hình và circuit breaker chưa mở. PostgreSQL và Qdrant được kiểm tra kết nối thật.

Mỗi response có `X-Request-ID`. Backend log JSON gồm request ID, session ID,
route, status và latency; lỗi nội bộ chỉ nằm trong log, không trả exception ra frontend.

Prometheus thu thập `/metrics` mỗi 15 giây và Grafana được provision sẵn
dashboard `Hanoi Food RAG - Operations`. Metrics chỉ dùng label có tập giá trị
nhỏ như route, status và stream outcome; không lưu user ID, session ID hoặc nội
dung câu hỏi.

## Xây dựng knowledge base

Pipeline hiện chỉ index Food. Catalog gồm 792 địa điểm thật từ OpenStreetMap có
quận Hà Nội được xác định trực tiếp từ metadata nguồn. Kết quả hiện tại là 820
chunk, giới hạn 120 token và overlap 15 token.

Metadata giá và giờ mở cửa được chuẩn hóa song song với giá trị raw:

- `price_min`, `price_max`, `price_currency`, `price_status`
- `opening_intervals`, `closes_next_day`, `opening_schedule_scope`
- `sub_category_normalized`, `tags_normalized`
- tọa độ, cuisine, liên hệ và provenance/giấy phép OSM
- ảnh Wikimedia Commons nếu nguồn có metadata ảnh hợp lệ

Làm mới dữ liệu OSM vào file review trước:

```powershell
python scripts/import_osm_hanoi_food.py
```

File review và summary nằm trong `data/imports/` và không được commit. Sau khi
kiểm tra summary/sample, chủ động promote bằng
`--output data/raw/food_raw.json`. Importer không bịa giá, menu hoặc ảnh; trường
thiếu giữ `N/A`, `[]` hoặc `null`. Dữ liệu địa điểm mang giấy phép ODbL 1.0 và
attribution
[`OpenStreetMap contributors`](https://www.openstreetmap.org/copyright).

Chạy từ thư mục gốc:

```powershell
python -m embedding.process_data --local-files-only
python -m embedding.generate_embeddings --local-files-only
python -m embedding.upload_to_qdrant --dry-run
python -m embedding.upload_to_qdrant
```

Pipeline tạo `data/processed/food_manifest.json` và manifest cạnh file vector.
Mỗi chunk mang cùng một `knowledge_version`; runtime từ chối hợp nhất BM25 và
Qdrant nếu hai nhánh trả về version khác nhau. Record OSM giữ
`verification_status=unverified` cho tới khi được kiểm chứng thủ công.

Uploader tạo collection vật lý `hanoi_food_osm_v2`, thêm GEO payload/index, kiểm
tra point count và payload mẫu, sau đó mới chuyển alias `hanoi_food_current`.
Collection cũ không bị xóa
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
  --output data/final/hanoi_food_osm_v1.json

python -m embedding.upload_to_qdrant `
  --input data/final/hanoi_food_osm_v1.json `
  --collection hanoi_food_osm_v2 `
  --alias hanoi_food_current `
  --expected-points 820 `
  --expected-parents 792
```

Hai count trên là chốt an toàn của dữ liệu hiện tại. Collection `v2` dùng lại
vector 384 chiều của file `v1` vì thay đổi này chỉ bổ sung geo payload/index,
không đổi model hoặc nội dung embedding. Nếu đã review và chủ động đổi dữ liệu
hoặc chunking, dùng tên version kế tiếp và thay count bằng số pipeline vừa in ra.

Retrieval benchmark offline có 80 case trên 75 địa điểm: entity lookup, giờ mở
cửa, truy vấn không dấu và no-answer. Trước khi chạy, có thể xác nhận file JSON
vẫn khớp catalog:

```powershell
python -m scripts.build_retrieval_cases --check
```

Đánh giá exact/BM25 hoàn toàn offline (cũng được gate trong CI):

```powershell
python -m embedding.evaluate_retrieval `
  --mode lexical `
  --top-k 5 `
  --min-accuracy 0.90
```

Report tách accuracy theo nhóm, kiểm tra hard constraint giá/quận/giờ và thống kê
độ đa dạng entity được trả về. Điểm lexical là regression gate deterministic,
không thay thế đánh giá semantic/hybrid trên Qdrant hoặc hidden test set.

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
python -m rag.evaluate_query_router --min-accuracy 0.90
```

Dataset hiện có 490 mẫu train và 175 mẫu calibration, cân bằng trên 7 intent.
Threshold mặc định `0.35` cho intent accuracy `96%`, high-confidence coverage
`92%` và high-confidence accuracy `97,52%`. Đây là số calibration, không phải
kết quả trên một hidden test set.
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

## MCP server học thuật

Giai đoạn 9 cung cấp một stdio MCP server dùng chung cho mọi môn chính trị với
8 structured tools. Cấu hình một `users.id` local đã tồn tại:

```dotenv
ACADEMIC_MCP_USER_ID=1
```

Chạy server hoặc kiểm tra contract:

```powershell
python academic_mcp_server.py
python -m scripts.evaluate_academic_mcp_contract
```

MCP tool schema không nhận `user_id`; identity được khóa vào process để agent
không thể tự chọn user khác. Xem thiết kế, tool catalog và cấu hình MCP host tại
`docs/phase-9-academic-mcp.md`.

## Docker

Qdrant trong Compose dùng external volume `qdrant_storage`. Máy mới chỉ cần tạo
volume một lần:

```powershell
docker volume create qdrant_storage
```

Máy hiện tại đã có volume này với alias
`hanoi_food_current -> hanoi_food_osm_v2`; không upload lại collection mặc định.
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

Nếu chạy backend trực tiếp bằng Uvicorn để có hot reload, hãy mở Docker Desktop
rồi chạy hai terminal:

```powershell
# Terminal 1
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2
docker compose -f compose.monitoring.yml up -d
```

File monitoring riêng chỉ chạy Prometheus và Grafana. Prometheus dùng
`host.docker.internal:8000` để đọc metrics từ Uvicorn trên máy, không tạo thêm
backend container nên không bị trùng cổng `8000`.

Mở frontend tại `http://localhost:3000`, API tại `http://localhost:8000`,
Prometheus tại `http://localhost:9090` và Grafana tại
`http://localhost:3001`. Đăng nhập Grafana local bằng `admin/admin`, sau đó mở
folder `Hanoi Food RAG`; đổi `GRAFANA_ADMIN_PASSWORD` nếu máy được chia sẻ.
Service one-shot `migrate` chạy `alembic upgrade head` trước backend. Lần chạy Docker đầu
tiên, service `model-cache` tải embedding model vào volume `huggingface_cache`.
Backend chỉ khởi động sau khi model đã sẵn sàng và luôn dùng local cache, nên
request đầu tiên không phải tải model.

Compose không tự tạo vector knowledge base. Khi Qdrant mới hoàn toàn, chạy
pipeline build/upload vào collection version mới rồi mới dùng chat:

```powershell
python -m embedding.process_data --local-files-only
python -m embedding.generate_embeddings --local-files-only
python -m embedding.upload_to_qdrant --collection hanoi_food_osm_v2
```

Dừng container nhưng giữ database:

```powershell
docker compose down
```

External volume `qdrant_storage` không bị xóa bởi `docker compose down -v`.
Lệnh đó vẫn xóa PostgreSQL, model cache, lịch sử Prometheus và cấu hình nội bộ
Grafana do Compose quản lý, vì vậy chỉ dùng khi chủ động reset các dữ liệu này.

`compose.prod.yml` dùng image đã publish, không public PostgreSQL/Qdrant/backend
ra host. Caddy là edge proxy duy nhất mở cổng `80/443`, tự cấp HTTPS cho
`PUBLIC_DOMAIN` và thêm HSTS. Production phải truyền secret qua environment hoặc
secret manager, không ghi chúng vào image hay commit vào Git. Qdrant production
bắt buộc có `QDRANT_API_KEY` và external volume phải được tạo trước.

Trước khi chạy production, trỏ DNS về server rồi khai báo ít nhất
`PUBLIC_DOMAIN`, `ACME_EMAIL`, `DATABASE_URL`,
`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `LLM_API_KEY`, `QDRANT_API_KEY`,
`BACKEND_IMAGE`, `FRONTEND_IMAGE` và `GRAFANA_ADMIN_PASSWORD`. Endpoint
`/metrics` không được Caddy public ra Internet; hệ thống monitoring phải scrape
từ mạng nội bộ.
`TRUST_PROXY_HEADERS=true` chỉ an toàn với topology này vì backend không mở port
ra host và Caddy là ingress duy nhất; không public backend trực tiếp.
Prometheus và Grafana production chỉ bind `127.0.0.1`; xem dashboard từ xa qua
SSH tunnel thay vì public cổng `3001` trực tiếp.

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
- FE gửi UUID `client_request_id`; retry cùng UUID trả lại đúng turn và không gọi
  LLM hoặc trừ quota lần hai.
- SSE dùng các event `session`, `token`, `done`, `error`.
- `GET /api/history?limit=&cursor=` và
  `GET /api/history/{session_id}?limit=&cursor=` dùng cursor pagination.
- Login/register, chat burst và quota AI request theo user/toàn hệ thống dùng
  bucket PostgreSQL để hoạt động đồng nhất giữa nhiều worker. Đây là cost guard
  bảo thủ, không phải phép đếm token chính xác từ provider; bucket hết hạn được
  dọn khi backend khởi động.
- Logout tăng `token_version`, vì vậy JWT đã lấy trước đó không dùng lại được.
- Auth/chat/history trả `Cache-Control: private, no-cache, no-store`.
- Prometheus tách outcome stream `completed/error/timeout/cancelled/replayed`
  dù HTTP SSE đã bắt đầu với status `200`.

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
