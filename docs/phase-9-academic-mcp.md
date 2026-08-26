# Giai đoạn 9 - Academic Learning MCP Server

## 1. Mục tiêu

Giai đoạn 9 bổ sung một MCP server dùng chung cho toàn bộ các môn lý luận chính trị. MCP là ranh giới chuẩn hóa để một MCP host/agent runtime khám phá và gọi các capability đã hoàn thiện; nó không thay thế Orchestrator, Knowledge, Assessment, Planning hoặc Verification Agent.

```text
MCP Host / Agent Runtime
          |
          | tools/list + tools/call
          v
 academic-learning-mcp
          |
          v
 User-bound Tool Adapter
          |
          +--> Orchestrator -> Knowledge -> Verification
          +--> Orchestrator -> Assessment -> Verification -> BKT
          +--> Orchestrator -> Planning -> Verification
          +--> Closed-loop event audit
```

Server dùng official MCP Python SDK `2.0.0`, dòng stable hỗ trợ protocol revision 2026-07-28. SDK yêu cầu Python 3.10 trở lên. Tham khảo [official Python SDK](https://github.com/modelcontextprotocol/python-sdk) và [PyPI release 2.0.0](https://pypi.org/project/mcp/2.0.0/).

## 2. Vì sao chỉ có một MCP server

Tên server:

```text
academic-learning-mcp
```

Không tạo MCP riêng cho Triết học, Tư tưởng Hồ Chí Minh hoặc Kinh tế chính trị. Mọi tool đều nhận `course_id` và `course_version`; dữ liệu khác nhau nằm trong Course Package, còn code agent và MCP adapter được tái sử dụng.

Thiết kế này giữ đề tài tập trung vào trợ lý AI đa tác tử và tự động hóa học tập, tránh biến đồ án thành bài toán quản trị nhiều microservice.

## 3. Tool catalog

| Tool | Agent/service phía sau | Side effect |
| --- | --- | --- |
| `ask_course_knowledge` | Orchestrator + Knowledge + Verification | Chỉ đọc tri thức, có citation |
| `start_assessment` | Assessment + Verification | Tạo attempt `PENDING` |
| `submit_assessment` | Assessment + BKT + closed loop | Cập nhật mastery và có thể đề xuất replan |
| `get_course_mastery` | Assessment service | Chỉ đọc mastery |
| `create_learning_plan` | Orchestrator + Planning + Verification | Tạo plan `PROPOSED` |
| `approve_learning_plan` | Planning service | Kích hoạt plan sau xác nhận người học |
| `get_current_learning_plan` | Planning service | Chỉ đọc plan `ACTIVE` |
| `list_learning_events` | Learning event service | Chỉ đọc audit trail |

Tất cả tool có JSON Schema đầu vào và structured output sinh từ type hints/Pydantic. Tool annotations đánh dấu rõ read-only, write, destructive và idempotent để MCP host chọn hành vi an toàn hơn.

## 4. Orchestrator và MCP không trùng vai trò

- MCP trả lời câu hỏi: “Capability nào tồn tại và gọi nó theo schema nào?”.
- Orchestrator trả lời câu hỏi: “Với trạng thái học tập hiện tại, bước tiếp theo nên là gì?”.
- Domain service thực hiện transaction và persistence.
- Verification Agent kiểm tra grounding hoặc constraint.

`ask_course_knowledge` vẫn chạy workflow đa tác tử nội bộ. `submit_assessment` vẫn kích hoạt UC04 và có thể gọi Planning Agent. MCP chỉ thay đổi cách capability được công bố cho host bên ngoài.

## 5. Identity và security boundary

Giai đoạn này chỉ chạy transport `stdio` dành cho local/trusted process. Identity được khóa lúc khởi động:

```dotenv
ACADEMIC_MCP_USER_ID=1
```

`user_id` không xuất hiện trong bất kỳ tool input schema nào. Model không thể tự truyền ID khác để đọc mastery, plan hoặc event của người dùng khác. Khi khởi động, server kiểm tra user tồn tại và database đang ở revision yêu cầu.

Các guard khác:

- Không log raw câu hỏi, đáp án hoặc nội dung cá nhân trong MCP adapter.
- Domain error được chuyển thành `ToolError` an toàn; exception nội bộ chỉ nằm trong server log.
- Rate limit và LLM budget dùng lại đúng service của FastAPI.
- `approve_learning_plan` yêu cầu literal `confirmation="APPROVE"` và chỉ nên được gọi sau xác nhận rõ ràng của người học.
- Không mở Streamable HTTP khi chưa có OAuth principal-to-user mapping.

Theo tài liệu SDK, stdio dùng process launcher làm security boundary; Streamable HTTP production cần cơ chế bearer/OAuth. Xem [official authorization guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/authorization.md).

## 6. Chạy server

Cài dependency:

```powershell
python -m pip install -r requirements.txt
```

Đảm bảo `.env` có database, LLM/Qdrant/course settings và user ID hợp lệ. Sau đó:

```powershell
python academic_mcp_server.py
```

Không có output và tiến trình đứng chờ là hành vi đúng của stdio server. `stdout` dành riêng cho MCP wire protocol; dùng logging qua `stderr`, không thêm `print()` lúc import hoặc serving.

Mở bằng MCP Inspector:

```powershell
mcp dev academic_mcp_server.py
```

Ví dụ cấu hình host local:

```json
{
  "mcpServers": {
    "academic-learning": {
      "command": "C:\\absolute\\path\\python.exe",
      "args": [
        "E:\\AGENTIC RAG FOOD\\academic_mcp_server.py"
      ],
      "env": {
        "ACADEMIC_MCP_USER_ID": "1"
      }
    }
  }
}
```

Không ghi LLM API key trực tiếp vào file config host nếu project đã đọc chúng từ `.env` hoặc secret manager.

## 7. Contract evaluation

Chạy:

```powershell
python -m scripts.evaluate_academic_mcp_contract
```

Metric hiện tại:

| Metric | Kết quả baseline |
| --- | --- |
| Tool coverage | `1.0` - đủ 8/8 tool |
| Structured output | `1.0` |
| Annotation accuracy | `1.0` |
| Identity argument exposure | `0` |
| Human approval guard | `true` |

Unit test dùng official in-memory `Client(server)` để chạy MCP discovery và `tools/call` thật, không chỉ gọi trực tiếp function Python.

## 8. Files chính

```text
academic_mcp/config.py       # user-bound stdio configuration
academic_mcp/adapter.py      # adapter tái sử dụng application services
academic_mcp/server.py       # MCPServer và 8 tool
academic_mcp/evaluation.py   # contract metrics
academic_mcp_server.py       # entry point ổn định cho host
tests/test_academic_mcp.py   # protocol + isolation tests
```

Giai đoạn 9 không cần migration mới. Database head vẫn là `20260826_0008`.

## 9. Giới hạn và bước tiếp theo

Chưa triển khai Streamable HTTP/OAuth, multi-tenant network server hoặc MCP sampling/elicitation. Các phần này không cần cho demo đồ án local và sẽ làm tăng phạm vi security đáng kể.

Giai đoạn 10 nên tập trung tích hợp demo và thực nghiệm cuối đồ án: chạy một kịch bản end-to-end qua MCP, thu agent trace/event, đo RAG + multi-agent + automation metrics và chuẩn bị dữ liệu trình bày hội đồng. Chỉ triển khai HTTP/OAuth nếu yêu cầu deployment thực tế xuất hiện.
