# Giai đoạn 6 - Assessment Agent và Bayesian Knowledge Tracing

## 1. Mục tiêu

Giai đoạn 6 triển khai UC02 của đồ án: chọn câu hỏi phù hợp với trạng thái người học, chấm câu trả lời, kiểm tra kết quả và cập nhật mức độ thành thạo theo concept.

Phạm vi được giữ gọn:

- Ngân hàng câu hỏi trắc nghiệm do giảng viên hoặc quản trị nội dung duyệt.
- Mỗi câu hỏi gắn với một concept, độ khó và citation tới tài liệu môn học.
- Assessment Agent chọn câu dựa trên mastery và lịch sử làm bài.
- Verification Agent kiểm tra câu hỏi và kết quả chấm.
- BKT cập nhật xác suất thành thạo sau mỗi câu trả lời.
- Mastery được cô lập theo người học, môn, phiên bản môn và concept.

Không dùng LLM để đoán một đáp án trắc nghiệm đúng hay sai. Kimi/Gemini vẫn được giữ cho các tác vụ cần hiểu ngôn ngữ; chấm trắc nghiệm và BKT dùng thuật toán xác định để kết quả có thể tái lập khi bảo vệ đồ án.

## 2. Luồng multi-agent

### Bắt đầu một lượt đánh giá

```text
API start
   |
   v
Orchestrator Agent
   |
   v
Assessment Agent
   |-- đọc mastery theo concept
   |-- đọc số lần từng câu đã xuất hiện
   |-- chọn concept yếu nhất
   `-- chọn câu ít lặp và có độ khó phù hợp
   |
   v
Verification Agent
   |-- PASS  -> lưu attempt PENDING -> trả câu hỏi
   `-- BLOCK -> không tạo attempt
```

### Nộp câu trả lời

```text
API submit
   |
   v
Orchestrator Agent
   |
   v
Assessment Agent -- chấm theo đáp án chuẩn trong snapshot
   |
   v
Verification Agent -- tính lại và đối chiếu kết quả chấm
   |-- BLOCK -> không cập nhật mastery
   `-- PASS
         |
         v
       BKT update
         |
         v
       lưu attempt COMPLETED + mastery mới
```

Một lượt làm bài chỉ được nộp một lần. Đáp án đúng nằm trong snapshot phía backend và không xuất hiện trong response bắt đầu bài.

## 3. Bayesian Knowledge Tracing

Mỗi concept có xác suất thành thạo hiện tại `P(L)`. Bốn tham số cơ bản nằm trong ngân hàng câu hỏi:

| Tham số | Ý nghĩa | Mặc định |
| --- | --- | --- |
| `p_initial` | Xác suất đã biết trước khi có quan sát | `0.20` |
| `p_learn` | Xác suất học được sau một lượt | `0.15` |
| `p_guess` | Xác suất đoán đúng khi chưa biết | `0.20` |
| `p_slip` | Xác suất trả lời sai dù đã biết | `0.10` |
| `mastery_threshold` | Ngưỡng coi concept đã thành thạo | `0.80` |

Nếu trả lời đúng:

```text
P(L|đúng) = P(L)(1-slip)
             / [P(L)(1-slip) + (1-P(L))guess]
```

Nếu trả lời sai:

```text
P(L|sai) = P(L)slip
            / [P(L)slip + (1-P(L))(1-guess)]
```

Sau đó áp dụng chuyển trạng thái học:

```text
P(L mới) = P(L|quan sát) + (1-P(L|quan sát))learn
```

Ví dụ với cấu hình mặc định và mastery ban đầu `0.20`:

- Trả lời đúng: mastery thành `0.60`.
- Trả lời sai: mastery thành `0.175758`.

Phân loại dùng cho bước tiếp theo:

- `< 0.50`: `weak` → `review_concept`.
- `0.50` tới dưới ngưỡng mastery: `developing` → `continue_practice`.
- Từ ngưỡng mastery trở lên: `mastered` → `concept_mastered`.

Các tham số mặc định chỉ là baseline kỹ thuật. Khi có dữ liệu người học thật, cần ước lượng hoặc thực nghiệm lại thay vì tuyên bố đây là tham số tối ưu.

## 4. Ngân hàng câu hỏi đa môn

Trong mỗi Course Package, tạo:

```text
course_packages/<course_id>/
├── course.yaml
├── documents/
└── assessment/
    └── questions.json
```

Template:

```text
course_packages/_template/assessment/questions.example.json
```

Mỗi câu hỏi cần:

- `question_id` duy nhất trong môn.
- `concept_id` và `concept_name`.
- `question_type: multiple_choice`.
- `difficulty` từ 1 đến 5.
- Từ 2 đến 6 lựa chọn có `option_id` duy nhất.
- `correct_option_id` tồn tại trong danh sách lựa chọn.
- Giải thích đáp án.
- Citation có tài liệu nguồn và ít nhất một locator trang, dòng hoặc đoạn.

Theo phạm vi đã khóa ở Giai đoạn 1, môn chính nên có tối thiểu 30 câu hỏi đã duyệt và phủ các concept trọng tâm; file template một câu chỉ dùng để minh họa schema.

Khi chạy ingestion, `questions.json` được kiểm tra scope, schema và tài liệu citation. Bản chuẩn hóa được ghi tự động vào:

```text
data/courses/<course_id>/<course_version>/assessment/questions.json
```

Nếu Course Package chưa có ngân hàng câu hỏi, ingestion kiến thức vẫn chạy được nhưng API assessment của môn đó báo chưa sẵn sàng. Vì vậy thêm môn mới không cần sửa agent, workflow hoặc database schema.

## 5. Quy tắc chọn câu thích ứng

Assessment Agent thực hiện theo thứ tự:

1. Nếu người dùng chọn concept, chỉ xét câu thuộc concept đó.
2. Nếu không chọn, lấy concept có mastery thấp nhất.
3. Quy đổi mastery sang độ khó mục tiêu từ 1 đến 5.
4. Ưu tiên câu có số lần xuất hiện ít nhất.
5. Trong nhóm đó, chọn độ khó gần mục tiêu nhất.
6. Dùng `question_id` làm tie-breaker để kết quả tái lập.

Quy tắc này đủ rõ để hội đồng kiểm chứng và làm baseline so sánh. Sau này có thể thay chiến lược chọn câu mà không thay format ngân hàng hoặc BKT persistence.

## 6. API

Runtime dùng chung cờ của academic multi-agent:

```dotenv
ACADEMIC_AGENT_ENABLED=true
COURSE_DATA_ROOT=data/courses
```

Trước khi chạy code mới trên database hiện có:

```powershell
alembic upgrade head
```

Revision yêu cầu:

```text
20260826_0006
```

### Bắt đầu đánh giá

```http
POST /api/academic-assistant/assessments/start

{
  "course_id": "political_philosophy",
  "course_version": "1.0.0",
  "concept_id": "matter"
}
```

`concept_id` có thể bỏ trống để agent tự chọn concept yếu nhất.

### Nộp đáp án

```http
POST /api/academic-assistant/assessments/<attempt_id>/submit

{
  "selected_option_id": "A"
}
```

Response trả kết quả đúng/sai, giải thích, mastery trước/sau, mức mastery và hành động tiếp theo.

### Xem hồ sơ mastery

```http
GET /api/academic-assistant/assessments/mastery?course_id=political_philosophy&course_version=1.0.0
```

Các concept chưa làm câu nào vẫn xuất hiện với `p_initial`, giúp frontend và Planning Agent sau này không phải tự suy đoán dữ liệu thiếu.

Tất cả endpoint yêu cầu đăng nhập. Start/submit có database-backed rate limit riêng nhưng không trừ ngân sách LLM vì workflow trắc nghiệm hiện tại không gọi provider.

## 7. Persistence và an toàn

Migration tạo hai bảng:

| Bảng | Vai trò |
| --- | --- |
| `assessment_attempts` | Lưu snapshot câu hỏi, trạng thái, đáp án nộp, kết quả và mastery trước/sau |
| `learner_concept_masteries` | Lưu mastery tổng hợp theo user/course/version/concept |

Các bảo vệ chính:

- Unique constraint cho một mastery record trong đúng scope.
- Check constraint giữ xác suất trong `[0, 1]` và số câu đúng không vượt tổng lượt.
- Khóa row người học khi cập nhật để hạn chế lost update trên PostgreSQL.
- Attempt thuộc người nào chỉ người đó được nộp.
- Attempt hoàn thành không được nộp lại.
- Verification phải `PASS` trước khi BKT được ghi.
- Không log đáp án đúng hoặc toàn bộ snapshot trong agent trace.

## 8. Đánh giá thực nghiệm

Template case:

```text
course_packages/_template/evaluation/assessment_cases.example.json
```

Chạy đánh giá:

```powershell
python -m scripts.evaluate_course_assessment `
  data\courses\political_philosophy\1.0.0\assessment\questions.json `
  course_packages\political_philosophy\evaluation\assessment_cases.json `
  --output data\evaluation\political_philosophy_assessment.json
```

Metric hiện có:

| Metric | Ý nghĩa |
| --- | --- |
| `concept_selection_accuracy` | Agent chọn đúng concept kỳ vọng từ hồ sơ mastery |
| `question_selection_accuracy` | Agent chọn đúng câu theo chiến lược baseline |
| `grading_accuracy` | Kết quả chấm đúng ground truth |
| `verification_pass_rate` | Tỷ lệ output hợp lệ được verifier chấp nhận |
| `bkt_boundedness_rate` | Tỷ lệ cập nhật BKT luôn nằm trong `[0, 1]` |

Để đánh giá tác động sư phạm, cần bổ sung thí nghiệm người học hoặc replay log có ground truth. Unit test và metric kỹ thuật không đủ để khẳng định BKT làm tăng kết quả học tập.

## 9. Kiểm thử

Giai đoạn 6 bao phủ:

- Công thức BKT cho quan sát đúng và sai.
- Phân loại weak/developing/mastered.
- Validation đáp án, option, locator và scope môn.
- Registry cache riêng theo môn/version và chặn path traversal.
- Ingestion tự chuẩn hóa ngân hàng câu hỏi tùy chọn.
- Chọn concept yếu, chọn độ khó và tránh lặp câu.
- Từ chối concept không có trong ngân hàng.
- Verification phát hiện kết quả chấm bị sửa.
- Không lộ `correct_option_id` khi bắt đầu bài.
- Persistence attempt và mastery.
- Chặn submit lặp.
- API authentication/runtime/rate-limit dependency.
- Bộ metric assessment.

Kết quả regression:

```text
Ran 216 tests
OK (skipped=1)
```

Test bị skip là integration migration PostgreSQL cần database riêng, không phải lỗi Assessment Agent hoặc BKT.

## 10. Giới hạn và bước tiếp theo

Giai đoạn 6 chưa làm:

- Câu trả lời ngắn và so sánh concept bằng LLM.
- Ước lượng tham số BKT từ dữ liệu người học thật.
- Diagnostic quiz gồm nhiều câu và điều kiện dừng thích ứng.
- Planning Agent sử dụng mastery để tạo lịch học.
- Tự động phát event `MASTERY_UPDATED` và `REPLAN_REQUIRED`.
- Giao diện làm bài.

Bước tiếp theo đúng trọng tâm đồ án là Giai đoạn 7: Planning Agent tạo lộ trình từ mục tiêu, thời gian và mastery hiện tại; Verification Agent kiểm tra constraint; sau kết quả assessment, Orchestrator có thể phát hiện concept yếu để đề xuất lập lại kế hoạch. MCP nên được thêm sau khi contract Knowledge và Assessment đã ổn định, dưới dạng một server dùng chung cho mọi môn.
