# Giai đoạn 5 - Multi-Agent hỏi đáp học thuật

## 1. Mục tiêu

Giai đoạn 5 triển khai use case UC01 của đồ án: sinh viên hỏi kiến thức trong một môn lý luận chính trị, hệ thống tự chọn luồng xử lý, tra cứu đúng dữ liệu môn, tạo câu trả lời có dẫn nguồn và kiểm tra lại trước khi trả kết quả.

Đây là lát cắt multi-agent đầu tiên chạy được của hệ thống. Phạm vi gồm ba agent:

| Agent | Trách nhiệm | Không được làm |
| --- | --- | --- |
| Orchestrator Agent | Phân loại yêu cầu thành `knowledge`, `direct` hoặc `unsupported` và chọn nhánh tiếp theo | Tự trả lời kiến thức học thuật |
| Knowledge Agent | Gọi tool truy xuất, tạo câu trả lời chỉ từ evidence và gắn citation dạng `[n]` | Tự quyết định câu trả lời đã đủ tin cậy |
| Verification Agent | Kiểm tra phạm vi môn, locator, citation và mức độ bám evidence; trả `PASS`, `REVISE` hoặc `BLOCK` | Tự thay Knowledge Agent tạo nội dung mới |

Assessment Agent và Planning Agent chưa được gắn tên giả vào luồng này. Hai agent đó sẽ được xây khi triển khai UC02-UC04.

## 2. Luồng điều phối

```text
START
  |
  v
Orchestrator Agent
  |-- direct -------> câu chào/hướng dẫn ----------------> END
  |-- unsupported --> từ chối yêu cầu ngoài phạm vi -----> END
  |
  `-- knowledge
          |
          v
    Knowledge Agent -- search_course_knowledge
          |
          v
    Verification Agent
          |-- PASS --------------------------------------> END
          |-- BLOCK -------------------------------------> END
          `-- REVISE --> Knowledge Agent (tối đa 2 lần)
```

Workflow được cài bằng `StateGraph`. Đây là multi-agent thực, không phải một chuỗi prompt cố định, vì:

- Orchestrator quyết định nhánh từ trạng thái yêu cầu.
- Mỗi agent có prompt, input/output và trách nhiệm riêng.
- Knowledge Agent truyền draft và evidence cho Verification Agent.
- Verification Agent có quyền buộc sửa hoặc chặn đầu ra.
- Vòng lặp sửa bị giới hạn tối đa hai lần để tránh chạy vô hạn.
- Response có `agent_trace` để quan sát agent, tool, trạng thái và số lần sửa.

## 3. Tool học thuật dùng chung cho nhiều môn

Tool duy nhất trong giai đoạn này là:

```text
search_course_knowledge(
  query,
  course_id,
  course_version,
  top_k
)
```

`AcademicRetrieverRegistry` tự tìm artifact theo quy ước:

```text
data/courses/<course_id>/<course_version>/processed/
data/courses/<course_id>/<course_version>/indexed/
```

Retriever được tạo lười và cache theo cặp `(course_id, course_version)`. Alias Qdrant cũng được suy ra từ `course_id`. Vì vậy thêm môn lý luận chính trị mới không cần sửa tool, agent hay graph; chỉ cần nạp Course Package, chạy ingestion, indexing và bộ đánh giá của môn.

Tool kiểm tra lại mọi hit phải đúng `course_id` và `course_version`. Nếu có evidence từ môn khác, workflow báo lỗi thay vì đưa dữ liệu đó cho LLM.

Contract này đã sẵn sàng để bọc thành một MCP server mỏng ở giai đoạn sau. Giai đoạn 5 chưa gắn nhãn MCP cho một hàm nội bộ, vì như vậy không tạo thêm giá trị kỹ thuật hay khả năng tích hợp thực tế.

## 4. Grounding và cơ chế fail-closed

Knowledge Agent chỉ nhận các đoạn evidence do tool trả về. Prompt coi nội dung tài liệu là dữ liệu, không thực thi chỉ dẫn nằm trong tài liệu.

Verification Agent kiểm tra hai lớp:

1. Kiểm tra xác định bằng code: đúng môn/version, citation tồn tại, số citation hợp lệ và nguồn có locator trang, dòng hoặc đoạn.
2. Kiểm tra ngữ nghĩa bằng LLM: câu trả lời có được evidence hỗ trợ và có trả lời đúng câu hỏi không.

Nếu output có cấu trúc của verifier không hợp lệ, không đủ evidence hoặc đã sửa hai lần vẫn chưa đạt, hệ thống trả `BLOCK` và không phát citation. Chỉ kết quả `PASS` mới trả draft của Knowledge Agent cho người dùng.

## 5. Cấu hình và chạy API

Giữ nguyên provider hiện tại bằng `LLM_PROVIDER`. Cả `gemini` và `kimi` dùng chung adapter OpenAI-compatible của project.

Các biến mới:

```dotenv
ACADEMIC_AGENT_ENABLED=true
COURSE_DATA_ROOT=data/courses
ACADEMIC_AGENT_MAX_REVISIONS=2
ACADEMIC_AGENT_TOP_K=5
```

Trước khi bật runtime cần có:

- Course Package đã qua ingestion và sinh embedding.
- Qdrant có collection/alias đã upload ở Giai đoạn 4.
- API key và model của provider đang chọn.

Endpoint:

```http
POST /api/academic-assistant/ask
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "question": "Quy luật lượng - chất là gì?",
  "course_id": "political_philosophy",
  "course_version": "1.0.0",
  "top_k": 5
}
```

Response chính:

```json
{
  "course_id": "political_philosophy",
  "course_version": "1.0.0",
  "route": "knowledge",
  "answer": "... [1]",
  "citations": [],
  "verification_status": "PASS",
  "revision_count": 0,
  "agent_trace": []
}
```

`citations` và `agent_trace` được rút gọn trong ví dụ. API yêu cầu đăng nhập, dùng chung ngân sách LLM với chat hiện tại, có burst limit riêng và không trả lỗi nội bộ cho client. Runtime mặc định tắt để project cũ vẫn khởi động khi chưa có dữ liệu môn.

## 6. Đánh giá agent

Template nằm tại:

```text
course_packages/_template/evaluation/agent_cases.example.json
```

Mỗi môn tạo file case riêng và chạy:

```powershell
python -m scripts.evaluate_academic_agents `
  course_packages\political_philosophy\evaluation\agent_cases.json `
  --output data\evaluation\political_philosophy_agents.json
```

Report hiện có:

| Metric | Ý nghĩa |
| --- | --- |
| `routing_accuracy` | Orchestrator chọn đúng nhánh |
| `tool_selection_accuracy` | Nhánh cần kiến thức có gọi tool và nhánh khác không gọi nhầm |
| `verification_outcome_accuracy` | Kết quả kiểm tra đúng kỳ vọng |
| `constraint_satisfaction_rate` | Citation, phạm vi môn và giới hạn loop đều hợp lệ |
| `average_revision_count` | Số vòng tự sửa trung bình |
| `loop_violation_count` | Số case vượt giới hạn sửa |

Khi làm thực nghiệm thật, nên bổ sung tối thiểu ba nhóm case: câu hỏi có đủ evidence, câu hỏi thiếu evidence và yêu cầu ngoài phạm vi. Không dùng điểm unit test thay cho số liệu thực nghiệm với Kimi/Gemini và dữ liệu chính thức.

## 7. Kiểm thử kỹ thuật

Test Giai đoạn 5 bao phủ:

- Luồng grounded đi qua đủ ba agent.
- Nhánh trực tiếp và ngoài phạm vi không gọi nhầm retrieval/verifier.
- Thiếu citation hoặc sai ngữ nghĩa tạo vòng `REVISE`.
- Revision dùng lại evidence, không gọi retrieval lặp không cần thiết.
- Chặn sau tối đa hai lần sửa.
- Không có evidence thì không cho LLM bịa câu trả lời.
- Verifier trả JSON lỗi thì hệ thống fail-closed.
- Tool chặn dữ liệu lẫn môn.
- Registry dùng chung cho nhiều môn và cache đúng version.
- Adapter hoạt động với cấu hình Kimi/Gemini.
- API, authentication dependency, lifecycle, rate limit và budget.
- Các metric đánh giá agent.

Kết quả regression khi hoàn thành giai đoạn:

```text
Ran 203 tests
OK (skipped=1)
```

Test bị skip là integration migration PostgreSQL cần database riêng, không phải lỗi của workflow agent.

## 8. Giới hạn có chủ đích và bước tiếp theo

Giai đoạn 5 chưa có:

- Assessment Agent, BKT và hồ sơ mastery theo concept.
- Planning Agent và vòng tự động điều chỉnh kế hoạch học.
- MCP server chạy độc lập.
- Session memory dài hạn cho người học.
- Benchmark thật với dữ liệu môn và provider thật.
- Giao diện quản trị nạp môn hoặc giao diện chat học thuật riêng.

Bước tiếp theo hợp lý là triển khai Assessment Agent cùng BKT cho UC02. Sau khi contract tool đã ổn định, có thể bọc `search_course_knowledge` và các tool đánh giá thành một `academic-learning-mcp`; tất cả môn tiếp tục dùng chung một server, không tạo MCP riêng cho từng môn.
