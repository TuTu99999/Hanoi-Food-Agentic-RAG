# Giai đoạn 8 - Closed-loop Learning Automation

## 1. Mục tiêu

Giai đoạn 8 đóng vòng UC04 của đồ án trợ lý học tập AI đa tác tử:

```text
Assessment Agent chấm bài
          |
          v
      BKT cập nhật mastery
          |
          v
Orchestrator Agent đánh giá tín hiệu
          |
          v
Planning Agent tạo revision (khi cần)
          |
          v
Verification Agent kiểm tra constraint
          |
          v
PROPOSED -- người học duyệt --> ACTIVE
```

Điểm agentic nằm ở việc hệ thống quan sát kết quả, tự quyết định bước tiếp theo, gọi đúng agent và duy trì trạng thái dài hạn. Kimi/Gemini vẫn đảm nhiệm tác vụ ngôn ngữ ở Knowledge Agent; chính sách kích hoạt và lịch học dùng code xác định để dễ giải thích, tái lập và đánh giá.

## 2. Chính sách kích hoạt baseline

Orchestrator chỉ yêu cầu lập lại kế hoạch khi đồng thời thỏa ba điều kiện:

1. Người học vừa trả lời sai.
2. BKT sau cập nhật nhỏ hơn `0.50`, tức mức `weak`.
3. Có một kế hoạch `ACTIVE` đúng user/course/version.

Nếu đã có một revision `REPLAN` đang `PROPOSED` cho kế hoạch đó, hệ thống dùng lại revision đang chờ thay vì tạo bản trùng. Đây là guard chống proposal spam.

Các mã quyết định có thể quan sát:

| Mã | Ý nghĩa |
| --- | --- |
| `NO_ACTIVE_PLAN` | Chỉ cập nhật mastery vì chưa có kế hoạch đang chạy |
| `ANSWER_CORRECT` | Không cần lập lại sau câu đúng |
| `MASTERY_NOT_WEAK` | Trả lời sai nhưng mastery chưa ở mức yếu |
| `WEAKNESS_DETECTED` | Phát hiện điểm yếu và tạo đề xuất mới |
| `PENDING_REPLAN_EXISTS` | Dùng lại đề xuất đang chờ duyệt |
| `REPLAN_BLOCKED` | Cần lập lại nhưng constraint thời gian/dữ liệu chưa cho phép |

Đây là baseline có chủ đích, chưa tuyên bố là chính sách sư phạm tối ưu. Ngưỡng và trigger có thể được hiệu chỉnh bằng thực nghiệm sau khi có dữ liệu người học.

## 3. Transaction và an toàn

Một lần nộp bài ghi trong cùng transaction:

- Kết quả assessment.
- Mastery BKT mới.
- Event `MASTERY_UPDATED`.
- Event `REPLAN_REQUIRED` nếu có.
- Revision `PROPOSED` đã qua Verification nếu đủ constraint.
- Event `PLAN_PROPOSED`.

Nếu hết hạn hoặc không đủ quỹ thời gian, assessment và mastery vẫn được lưu; event ghi trạng thái `BLOCKED`, còn hệ thống không tạo một kế hoạch sai constraint.

AI không tự kích hoạt revision. Chỉ endpoint duyệt của người học mới chuyển revision sang `ACTIVE` và kế hoạch cũ sang `REPLACED`. Đây là Human-in-the-Loop bắt buộc.

## 4. Persistence

Migration hiện tại:

```text
20260826_0008
```

Chạy:

```powershell
alembic upgrade head
```

`learning_plans` được bổ sung:

- `proposal_kind`: `INITIAL` hoặc `REPLAN`.
- `parent_plan_id`: kế hoạch active làm nguồn cho revision.
- `trigger_event_id`: event khiến Orchestrator lập lại.

Bảng `learning_events` lưu event theo user/course/version:

- `MASTERY_UPDATED`
- `REPLAN_REQUIRED`
- `PLAN_PROPOSED`
- `PLAN_APPROVED`

`event_type + correlation_id` là duy nhất để chống ghi lặp khi cùng thao tác bị retry.

## 5. API

Luồng tự động chạy ngay trong API nộp bài hiện có:

```http
POST /api/academic-assistant/assessments/<attempt_id>/submit
```

Response có thêm `automation` gồm:

- Có cần lập lại hay không.
- Mã lý do.
- `proposed_plan_id` nếu đã tạo hoặc dùng lại revision.
- Agent trace của quyết định và workflow planning.
- Thông báo cần người học duyệt.

Xem audit trail của người đang đăng nhập:

```http
GET /api/academic-assistant/events?course_id=political_philosophy&course_version=1.0.0&limit=50
```

Duyệt revision vẫn dùng:

```http
POST /api/academic-assistant/plans/<plan_id>/approve
```

## 6. Hỗ trợ nhiều môn chính trị

Automation không chứa điều kiện riêng cho Triết học. Scope luôn lấy từ assessment và active plan:

```text
(user_id, course_id, course_version)
```

Khi nạp môn chính trị mới có question bank và learning map hợp lệ, vòng kín dùng lại nguyên code. Nội dung môn, concept, prerequisite, citation và thời lượng nằm trong Course Package; không sửa Orchestrator, Assessment Agent hay Planning Agent.

## 7. Đánh giá

Template:

```text
course_packages/_template/evaluation/automation_cases.example.json
```

Chạy offline:

```powershell
python -m scripts.evaluate_learning_automation `
  course_packages/_template/evaluation/automation_cases.example.json
```

Metric:

| Metric | Ý nghĩa |
| --- | --- |
| `trigger_accuracy` | Orchestrator quyết định đúng có cần lập lại |
| `proposal_decision_accuracy` | Quyết định đúng có tạo proposal mới |
| `duplicate_prevention_rate` | Không tạo trùng khi đã có revision chờ duyệt |
| `human_approval_compliance_rate` | Automation không tự chuyển plan sang ACTIVE |

Template baseline hiện đạt `1.0` cho cả bốn metric. Đây là kiểm tra chính sách xác định, không phải bằng chứng về learning gain ngoài thực tế.

## 8. Kiểm thử chính

- Sai + mastery yếu + active plan tạo revision đã Verification `PASS`.
- Active plan vẫn active cho tới khi người học duyệt.
- Revision mang đúng parent plan và trigger event.
- Lần yếu tiếp theo dùng lại proposal đang chờ.
- Duyệt revision thay thế kế hoạch cũ và phát `PLAN_APPROVED`.
- Không có active plan thì chỉ ghi mastery event.
- Kế hoạch hết hạn trả `REPLAN_BLOCKED` nhưng không làm mất kết quả assessment.
- Event API luôn dùng scope của user đã xác thực.

## 9. Giới hạn và giai đoạn tiếp theo

Giai đoạn 8 chưa tự động hóa lịch ngoài hệ thống, chưa đánh dấu từng phiên học hoàn thành và chưa dùng dữ liệu thực để hiệu chỉnh trigger. Bước tiếp theo phù hợp đề tài là Giai đoạn 9: bọc các capability ổn định thành MCP tools (knowledge search, assessment, mastery, planning và event audit), vẫn giữ Orchestrator của hệ thống làm bộ điều phối trung tâm.
