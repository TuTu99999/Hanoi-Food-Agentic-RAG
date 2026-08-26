# Giai đoạn 3 - Nạp và chuẩn hóa dữ liệu nhiều môn

## 1. Mục tiêu

Giai đoạn 3 xây dựng đầu vào kiến thức dùng chung cho các môn lý luận chính trị. Người quản trị chỉ cần tạo một `Course Package`, khai báo tài liệu và chạy một lệnh nạp; không phải sửa parser hoặc mã nguồn theo từng môn.

Phạm vi của giai đoạn này chỉ gồm **ingestion và chuẩn hóa dữ liệu**. Embedding, Qdrant, truy xuất RAG và các agent sẽ được nối ở các giai đoạn sau.

## 2. Luồng xử lý

```text
Course Package
    -> kiểm tra course.yaml và đường dẫn tài liệu
    -> đọc TXT / Markdown / PDF / DOCX
    -> tách section theo heading, trang hoặc đoạn
    -> chia chunk có overlap
    -> gắn citation và metadata môn học
    -> tính hash dữ liệu, tạo knowledge_version
    -> ghi chunks.json và ingestion_manifest.json
```

Thiết kế này giữ `course_id`, `course_version` và `knowledge_version` trong mọi chunk, nên dữ liệu giữa các môn không bị trộn.

## 3. Course Package

Cấu trúc tối thiểu:

```text
course_packages/
└── triet_hoc_mac_lenin/
    ├── course.yaml
    └── documents/
        ├── giao_trinh.pdf
        └── de_cuong.md
```

Ví dụ `course.yaml`:

```yaml
course_id: triet_hoc_mac_lenin
name: Triết học Mác - Lênin
domain: political_theory
language: vi
version: "1.0.0"
description: Dữ liệu phục vụ trợ lý học tập môn Triết học Mác - Lênin.
sources:
  - path: documents/giao_trinh.pdf
    document_id: giao_trinh_chinh_thuc
    title: Giáo trình Triết học Mác - Lênin
    source_type: official_textbook
    source_authority: Bộ Giáo dục và Đào tạo
    publication_year: 2021
  - path: documents/de_cuong.md
    document_id: de_cuong_mon_hoc
    title: Đề cương môn học
    source_type: syllabus
```

Các loại nguồn được chấp nhận:

- `official_textbook`
- `syllabus`
- `lecture_notes`
- `question_bank`
- `reference`

Khai báo `sources` là tùy chọn. Nếu không khai báo, pipeline vẫn nạp tài liệu và tự suy ra tên cùng `document_id`; tuy nhiên nên khai báo đầy đủ cho dữ liệu chính thức để citation rõ ràng.

## 4. Cách chạy

Kiểm tra package trước:

```powershell
python -m scripts.validate_course_package course_packages\triet_hoc_mac_lenin
```

Chạy thử, không ghi file:

```powershell
python -m scripts.ingest_course_package course_packages\triet_hoc_mac_lenin --dry-run
```

Nạp thật:

```powershell
python -m scripts.ingest_course_package course_packages\triet_hoc_mac_lenin
```

Mặc định mỗi chunk tối đa 220 từ và overlap 30 từ. Có thể chỉnh khi thực nghiệm:

```powershell
python -m scripts.ingest_course_package course_packages\triet_hoc_mac_lenin --max-words 250 --overlap-words 40
```

Nếu output của cùng `course_version` đã tồn tại, pipeline sẽ dừng để tránh ghi đè. Khi dữ liệu thay đổi, cách đúng là tăng `version` trong `course.yaml`. Cờ `--force` chỉ nên dùng lúc phát triển.

## 5. Output

```text
data/courses/
└── triet_hoc_mac_lenin/
    └── 1.0.0/
        └── processed/
            ├── chunks.json
            └── ingestion_manifest.json
```

Mỗi chunk có dạng rút gọn:

```json
{
  "chunk_id": "triet_hoc_mac_lenin__1_0_0__giao_trinh_chinh_thuc__chunk_0001",
  "course_id": "triet_hoc_mac_lenin",
  "course_version": "1.0.0",
  "knowledge_version": "triet_hoc_mac_lenin-12_ky_tu_hash",
  "document_id": "giao_trinh_chinh_thuc",
  "section_id": "section-1",
  "content": "Nội dung học thuật...",
  "vector_text": "Môn học: Triết học Mác - Lênin\nTài liệu: Giáo trình Triết học Mác - Lênin\nMục: Chương 1\nNội dung: Nội dung học thuật...",
  "citation": {
    "document_title": "Giáo trình Triết học Mác - Lênin",
    "source_path": "documents/giao_trinh.pdf",
    "page_number": 1,
    "section_title": "Chương 1"
  }
}
```

`ingestion_manifest.json` lưu tổng số tài liệu, section, chunk, hash từng nguồn, cấu hình chunk và hash của toàn bộ output. Cùng một bộ dữ liệu và cấu hình sẽ tạo cùng `knowledge_version`.

## 6. Citation theo định dạng

| Định dạng | Vị trí citation |
| --- | --- |
| PDF | Số trang |
| TXT/Markdown | Dòng bắt đầu và kết thúc |
| DOCX | Đoạn bắt đầu và kết thúc |

Citation sử dụng đường dẫn tương đối trong Course Package, không ghi đường dẫn tuyệt đối của máy phát triển vào dữ liệu.

## 7. Các chốt an toàn

- Chỉ nhận `.txt`, `.md`, `.pdf`, `.docx`.
- Một tài liệu tối đa 50 MB.
- Một package tối đa 100 tài liệu và 200 MB.
- Chặn đường dẫn đi ra ngoài Course Package.
- Chặn `document_id` và `chunk_id` trùng nhau.
- Ghi JSON theo cơ chế file tạm rồi thay thế.
- Không tự ghi đè output đã có nếu thiếu `--force`.
- PDF scan không có text sẽ báo lỗi rõ ràng thay vì tạo dữ liệu rỗng.

## 8. Giới hạn có chủ đích

Giai đoạn 3 chưa làm:

- OCR cho PDF scan.
- Trích xuất bảng và hình ảnh phức tạp.
- Sinh embedding và nạp Qdrant.
- Hybrid retrieval hoặc GraphRAG.
- Tự động sinh concept graph.
- API upload tài liệu trên giao diện.
- Orchestrator và các agent học tập.

Các phần trên không bị bỏ quên; chúng được tách khỏi ingestion để đồ án có từng lớp rõ ràng và dễ kiểm thử.

## 9. Kiểm thử

Đã kiểm tra:

- Parser Markdown, DOCX và PDF.
- Citation theo dòng, đoạn và trang.
- Chunk overlap không tạo đoạn cuối bị lặp.
- Nạp Course Package từ đầu đến cuối.
- Output có version và không bị ghi đè ngoài ý muốn.
- Hai môn khác nhau có ID, version dữ liệu và thư mục độc lập.
- Không làm hỏng luồng cũ của dự án.

Kết quả toàn bộ test suite tại thời điểm hoàn thành:

```text
Ran 175 tests
OK (skipped=1)
```

Test được skip là bài integration migration PostgreSQL cần một database PostgreSQL riêng; không phải lỗi của pipeline ingestion.

## 10. Điều kiện hoàn thành Giai đoạn 3

Giai đoạn 3 được xem là hoàn thành khi một Course Package hợp lệ có thể tạo ra các chunk:

- đúng môn và đúng phiên bản;
- có citation quay về nguồn;
- có ID ổn định;
- có manifest kiểm chứng dữ liệu;
- không yêu cầu sửa code khi thêm một môn lý luận chính trị mới.

Bước tiếp theo hợp lý là Giai đoạn 4: sinh embedding, index theo `course_id`/`knowledge_version` và xây retrieval dùng chung cho nhiều môn.
