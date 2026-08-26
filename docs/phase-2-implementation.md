# Giai đoạn 2 - Nền tảng đa môn và Gemini/Kimi

## 1. Kết quả đã xây dựng

Giai đoạn này đã bắt đầu code nhưng chưa thay luồng RAG ẩm thực bằng luồng học tập.

Các phần đã hoàn thành:

- Schema `CourseManifest` dùng chung cho các môn lý luận chính trị.
- Database model `CourseModel` và `CourseVersionModel`.
- Alembic migration `20260825_0005`.
- Course Registry để đăng ký, liệt kê và lấy chi tiết môn.
- Course Package validator cho YAML/JSON và thư mục tài liệu.
- API tạo, kiểm tra và xem môn học.
- Quyền `is_content_manager` cho người quản lý nội dung.
- Provider abstraction dùng chung cho Gemini và Kimi.
- Template để tạo môn mới.
- Unit test và API integration test.

## 2. Cấu trúc được thêm

```text
courses/
├── naming.py
├── package.py
└── registry.py

llm/
└── provider.py

schemas/
└── course.py

routers/
└── courses.py

course_packages/
└── _template/
    ├── course.yaml
    └── documents/
```

## 3. Database

Migration mới tạo:

```text
users.is_content_manager

courses
├── course_id
├── name
├── domain
├── language
├── description
└── created_by_user_id

course_versions
├── course_pk
├── version
├── status
├── vector_alias
├── graph_namespace
└── manifest_json
```

Chạy migration trước khi khởi động backend mới:

```powershell
alembic upgrade head
```

Backend hiện yêu cầu revision:

```text
20260825_0005
```

## 4. Cấu hình Gemini/Kimi

Gemini vẫn là mặc định khi phát triển:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key
LLM_BASE_URL=
LLM_MODEL=
LLM_REASONING_EFFORT=
```

Chuyển sang Kimi:

```dotenv
LLM_PROVIDER=kimi
KIMI_API_KEY=your-key
LLM_BASE_URL=
LLM_MODEL=
LLM_REASONING_EFFORT=
```

Khi các trường override để trống, hệ thống chọn mặc định theo provider:

| Provider | Base URL | Model | Reasoning effort |
| --- | --- | --- | --- |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-3.6-flash` | `minimal` |
| Kimi | `https://api.moonshot.ai/v1` | `kimi-k3` | `low` |

`LLM_API_KEY` vẫn là biến override chung nếu cần.

## 5. Course Package tối thiểu

Sao chép thư mục mẫu:

```powershell
Copy-Item -Recurse course_packages\_template course_packages\political_philosophy
```

Sửa `course.yaml` và đặt ít nhất một file PDF, DOCX, TXT hoặc Markdown thật vào `documents/`.

Kiểm tra package:

```powershell
python -m scripts.validate_course_package course_packages\political_philosophy
```

Ví dụ kết quả:

```json
{
  "valid": true,
  "course_id": "political_philosophy",
  "version": "1.0.0",
  "documents": 1,
  "vector_alias": "course_political_philosophy_current",
  "graph_namespace": "political_philosophy:1_0_0"
}
```

Giai đoạn này chỉ kiểm tra cấu trúc package. Parse PDF, chunk, embedding và upload Qdrant sẽ được làm ở ingestion pipeline.

## 6. API đã có

| Method | Endpoint | Quyền | Chức năng |
| --- | --- | --- | --- |
| POST | `/api/courses/validate-manifest` | Content manager | Kiểm tra manifest trước khi lưu |
| POST | `/api/courses` | Content manager | Tạo môn hoặc thêm phiên bản `DRAFT` |
| GET | `/api/courses` | User đã đăng nhập | Liệt kê môn và phiên bản |
| GET | `/api/courses/{course_id}` | User đã đăng nhập | Xem chi tiết một môn |

Tài khoản đăng ký mới là sinh viên. Trong môi trường phát triển, có thể cấp quyền quản lý nội dung trực tiếp trong PostgreSQL:

```sql
UPDATE users
SET is_content_manager = true
WHERE username = 'ten_dang_nhap';
```

Giao diện quản trị role chưa nằm trong Giai đoạn 2.

## 7. Ví dụ request tạo môn

```json
{
  "course_id": "political_philosophy",
  "name": "Triết học Mác - Lênin",
  "domain": "political_theory",
  "version": "1.0.0",
  "language": "vi",
  "description": "Môn chính của đồ án",
  "retrieval": {
    "dense": true,
    "keyword": true,
    "graph_expansion": true
  },
  "assessment": {
    "mastery_model": "bkt",
    "allowed_question_types": [
      "multiple_choice",
      "short_answer"
    ]
  },
  "automation": {
    "adaptive_replanning": true,
    "reminders": true
  }
}
```

Đăng ký cùng `course_id` với version `1.1.0` sẽ tạo phiên bản mới. Đăng ký trùng cả `course_id` và version trả về HTTP `409`.

## 8. Quy tắc đã được bảo vệ bằng code

- `course_id` chỉ dùng chữ thường, số và dấu gạch dưới.
- `version` phải có dạng `MAJOR.MINOR.PATCH`.
- Domain hiện chỉ nhận `political_theory`.
- Language hiện chỉ nhận `vi`.
- Mastery model hiện chỉ nhận `bkt`.
- Môn mới bắt đầu ở trạng thái `DRAFT`.
- Mỗi môn có vector alias riêng.
- Mỗi phiên bản có graph namespace riêng.
- Sinh viên không được tạo hoặc kiểm tra manifest qua API quản trị.
- Không thể tạo trùng một phiên bản môn.

## 9. Kết quả kiểm thử

```text
166 tests run
1 PostgreSQL migration test skipped theo cấu hình, 0 failed
```

Các test mới bao phủ:

- Manifest hợp lệ và không hợp lệ.
- Course Package YAML và thư mục documents.
- Thêm môn và thêm version.
- Chặn version trùng hoặc metadata không khớp.
- Chọn mặc định Gemini/Kimi.
- Quyền content manager.
- API validate, create, list và detail.
- Regression test của hệ thống cũ.

## 10. Chưa làm trong Giai đoạn 2

- Chưa upload file qua giao diện.
- Chưa parse hoặc chunk giáo trình.
- Chưa tạo vector index cho môn học.
- Chưa tạo Concept Graph.
- Chưa tạo năm learning agent.
- Chưa có BKT và automation.
- Chưa kích hoạt version `ACTIVE`.

Các phần này chưa làm vì Course Registry phải ổn định trước khi dữ liệu và agent phụ thuộc vào nó.

## 11. Điều kiện kết thúc Giai đoạn 2

- [x] Có schema môn học dùng chung.
- [x] Có database migration.
- [x] Có Course Registry.
- [x] Có Course Package validator.
- [x] Có template nạp môn.
- [x] Có API quản lý cơ bản.
- [x] Có phân quyền tối thiểu.
- [x] Gemini và Kimi dùng chung provider abstraction.
- [x] Test cũ và test mới đều chạy thành công.

Giai đoạn tiếp theo nên là **Giai đoạn 3: xây ingestion pipeline cho Course Package**, bắt đầu từ TXT/Markdown/PDF và metadata citation, chưa làm agent ngay.
