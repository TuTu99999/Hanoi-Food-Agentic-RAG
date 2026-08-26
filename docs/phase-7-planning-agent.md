# Giai đoạn 7 - Planning Agent và lộ trình học cá nhân

## 1. Mục tiêu

Giai đoạn 7 triển khai UC03: tạo lộ trình học từ ngày mục tiêu, số ngày học, số phút mỗi ngày và mastery BKT hiện tại.

Hệ thống hiện có đủ năm agent đã xác định ở Giai đoạn 1:

| Agent | Vai trò đã triển khai |
| --- | --- |
| Orchestrator Agent | Chọn và điều phối workflow kiến thức, đánh giá hoặc lập kế hoạch |
| Knowledge Agent | Hỏi đáp có evidence và citation |
| Assessment Agent | Chọn câu thích ứng và chấm bài |
| Planning Agent | Tạo lịch học từ mastery, quỹ thời gian và prerequisite |
| Verification Agent | Kiểm tra grounding, kết quả chấm và constraint kế hoạch |

Planning Agent ở giai đoạn này dùng thuật toán xác định. Kimi/Gemini vẫn được giữ cho tác vụ ngôn ngữ; không dùng LLM để tự tạo lịch khó tái lập khi các constraint có thể kiểm tra bằng code.

## 2. Workflow agentic

```text
Người học nhập mục tiêu + quỹ thời gian
                   |
                   v
          Orchestrator Agent
                   |
                   v
             Planning Agent
          - đọc mastery BKT
          - lấy concept yếu
          - thêm prerequisite closure
          - ước lượng thời lượng còn thiếu
          - chia phiên học theo ngày
                   |
                   v
          Verification Agent
          - thời gian/ngày
          - khoảng ngày hợp lệ
          - độ phủ concept
          - thứ tự prerequisite
             |             |
           BLOCK          PASS
             |             |
       không lưu      lưu PROPOSED
                           |
                           v
                    người học duyệt
                           |
                           v
                         ACTIVE
```

Kế hoạch không được tự kích hoạt. Verification phải `PASS`, sau đó người học vẫn phải duyệt qua endpoint riêng. Đây là Human-in-the-Loop bắt buộc của UC03.

## 3. Learning Map dùng chung cho nhiều môn

Mỗi Course Package có thể thêm:

```text
course_packages/<course_id>/planning/learning_map.json
```

Template:

```text
course_packages/_template/planning/learning_map.example.json
```

Mỗi concept khai báo:

- `concept_id`, `concept_name` và thứ tự gợi ý.
- `estimated_minutes` từ 15 đến 480 phút.
- Danh sách `prerequisite_ids`.
- Mục tiêu học tập.
- Citation tới giáo trình hoặc đề cương, có trang/dòng/đoạn.

Validation chặn:

- Concept bị trùng.
- Prerequisite không tồn tại.
- Concept phụ thuộc chính nó.
- Đồ thị prerequisite có chu trình.
- Citation trỏ tới file không có trong Course Package.
- Concept trong question bank không tồn tại trong Learning Map.
- Sai `course_id` hoặc `course_version`.

Ingestion tự chuẩn hóa file vào:

```text
data/courses/<course_id>/<course_version>/planning/learning_map.json
```

`LearningMapRegistry` tự tải và cache theo môn/version. Thêm môn chính trị mới không sửa Planning Agent hoặc LangGraph.

## 4. Chiến lược lập kế hoạch baseline

Planning Agent thực hiện:

1. Nếu có `focus_concept_ids`, chọn các concept đó.
2. Nếu không có focus, chọn các concept có mastery thấp hơn ngưỡng BKT.
3. Nếu tất cả đã đạt ngưỡng, chọn concept có mastery thấp nhất để review.
4. Bổ sung toàn bộ prerequisite của các concept đã chọn.
5. Sắp xếp topo; trong các concept đã đủ prerequisite, ưu tiên mastery thấp hơn.
6. Ước lượng thời gian còn thiếu:

```text
required = estimated_minutes × max(0.25, 1 - mastery)
```

7. Làm tròn lên theo bước 5 phút và chia thành phiên học theo giới hạn mỗi ngày.

Activity được gán theo mastery:

- `< 0.50`: `learn`.
- Từ `0.50` tới dưới ngưỡng mastery: `practice`.
- Đã đạt ngưỡng: `review`.

Đây là baseline minh bạch để đánh giá. Chưa tuyên bố công thức thời lượng là tối ưu sư phạm; sau này có thể hiệu chỉnh từ log người học mà không đổi contract của Course Package.

## 5. Verification constraints

Verification Agent chỉ cho `PASS` khi:

- Không còn concept chưa xếp lịch.
- Tổng thời lượng đã xếp bằng tổng thời lượng cần học.
- Không ngày nào vượt `minutes_per_day`.
- Mọi phiên học nằm từ `start_date` đến trước `target_date`.
- Mọi concept ưu tiên đều xuất hiện.
- Mọi prerequisite xuất hiện và hoàn thành trước concept phụ thuộc.
- Không có concept ngoài Learning Map.

Nếu quỹ thời gian không đủ, API trả `422` kèm lý do và không tạo plan record.

## 6. Persistence và duyệt kế hoạch

Migration mới:

```text
20260826_0007
```

Chạy trước khi bật backend:

```powershell
alembic upgrade head
```

Bảng `learning_plans` lưu request, draft đã xác minh, agent trace và trạng thái:

```text
PROPOSED -> ACTIVE -> COMPLETED
               |
               `-> REPLACED khi duyệt revision mới
```

Một revision mới được tạo tuần tự theo user/course/version. Khi duyệt plan mới, plan `ACTIVE` cũ cùng scope chuyển thành `REPLACED`.

## 7. API

### Tạo đề xuất

```http
POST /api/academic-assistant/plans

{
  "course_id": "political_philosophy",
  "course_version": "1.0.0",
  "target_date": "2026-10-15",
  "study_days": 21,
  "minutes_per_day": 60,
  "focus_concept_ids": [],
  "title": "Ôn thi Triết học"
}
```

Nếu bỏ `study_days`, hệ thống dùng toàn bộ số ngày từ hôm nay tới trước ngày mục tiêu.

### Duyệt đề xuất

```http
POST /api/academic-assistant/plans/<plan_id>/approve
```

### Lấy kế hoạch đang hoạt động

```http
GET /api/academic-assistant/plans/current?course_id=political_philosophy&course_version=1.0.0
```

Endpoint yêu cầu đăng nhập. Create/approve có rate limit riêng và không trừ ngân sách LLM vì workflow hiện tại không gọi provider.

## 8. Đánh giá kỹ thuật

Template case:

```text
course_packages/_template/evaluation/planning_cases.example.json
```

Chạy:

```powershell
python -m scripts.evaluate_course_planning `
  data\courses\political_philosophy\1.0.0\planning\learning_map.json `
  course_packages\political_philosophy\evaluation\planning_cases.json `
  --output data\evaluation\political_philosophy_planning.json
```

Metric:

| Metric | Ý nghĩa |
| --- | --- |
| `verification_outcome_accuracy` | PASS/BLOCK đúng kỳ vọng |
| `priority_selection_accuracy` | Agent chọn đúng thứ tự concept kỳ vọng |
| `daily_capacity_compliance_rate` | Không vượt phút học mỗi ngày |
| `prerequisite_order_compliance_rate` | Thứ tự nền tảng trước phụ thuộc hợp lệ |
| `concept_coverage_rate` | Tỷ lệ concept ưu tiên được xếp lịch |

CLI chạy trên template đạt đúng outcome, priority và constraint. Đây chỉ là kiểm tra kỹ thuật trên dữ liệu mẫu, không phải bằng chứng lộ trình làm tăng kết quả học tập.

## 9. Kiểm thử

Giai đoạn 7 bao phủ:

- Learning Map chặn prerequisite thiếu hoặc có chu trình.
- Registry cô lập scope và chặn path traversal.
- Ingestion tự chuẩn hóa Learning Map.
- Chọn concept yếu và prerequisite closure.
- Chia phiên không vượt phút/ngày.
- Verification chặn thiếu capacity.
- Lưu plan chỉ sau Verification `PASS`.
- Trạng thái `PROPOSED` yêu cầu người học duyệt.
- Duyệt revision mới thay thế plan active cũ.
- Cô lập plan theo user/course/version.
- Rate limit và API dependencies.
- Bộ metric planning.

Kết quả regression:

```text
Ran 228 tests
OK (skipped=1)
```

Test skip là integration migration PostgreSQL cần database riêng, không phải lỗi Planning Agent.

## 10. Giới hạn và bước tiếp theo

Giai đoạn 7 chưa có:

- Đánh dấu từng phiên học hoàn thành.
- Tự phát hiện tiến độ chậm.
- Tự tạo revision sau khi mastery thay đổi.
- Event `MASTERY_UPDATED`, `REPLAN_REQUIRED`, `PLAN_APPROVED`.
- Ngày nghỉ, khung giờ hoặc lịch cá nhân.
- Nhắc lịch ra Google Calendar/Todoist.
- MCP server chạy độc lập.

Giai đoạn 8 phù hợp nhất là đóng vòng UC04: sau assessment, hệ thống phát event mastery; Orchestrator kiểm tra plan active, đề xuất revision khi cần; Verification kiểm tra và người học duyệt thay đổi lớn. Sau khi vòng này ổn định mới bọc các tool Knowledge/Assessment/Planning vào một MCP server dùng chung cho mọi môn.
