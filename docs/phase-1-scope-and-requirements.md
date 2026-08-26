# Giai đoạn 1 - Phạm vi và yêu cầu của đồ án

## 1. Đề tài và hướng triển khai

### Tên đề tài giữ nguyên

**Xây dựng hệ thống trợ lý ảo theo mô hình AI đa tác tử sử dụng Kimi**

### Hướng triển khai cụ thể

Xây dựng trợ lý học tập đa tác tử cho nhóm môn lý luận chính trị. Hệ thống hỗ trợ hỏi đáp có dẫn nguồn, đánh giá kiến thức, lập kế hoạch học và tự điều chỉnh kế hoạch theo kết quả của người học.

Hệ thống được thiết kế để thêm môn chính trị mới bằng cách nạp một Course Package và cấu hình, không sửa agent hoặc workflow cốt lõi.

### Phạm vi môn học

| Vai trò | Môn học | Phạm vi |
| --- | --- | --- |
| Môn chính | Triết học Mác - Lênin | Triển khai và đánh giá đầy đủ |
| Môn minh chứng | Tư tưởng Hồ Chí Minh | Nạp 1-2 chương để kiểm tra khả năng mở rộng |
| Môn tương lai | Kinh tế chính trị Mác - Lênin, Chủ nghĩa xã hội khoa học và các môn chính trị liên quan | Hỗ trợ bằng kiến trúc, chưa cần nạp đầy đủ trong đồ án |

## 2. Mục tiêu đồ án

### Mục tiêu tổng quát

Xây dựng một trợ lý ảo sử dụng Kimi có khả năng điều phối nhiều AI agent để tự động hỗ trợ quá trình học tập các môn lý luận chính trị.

### Mục tiêu cụ thể

1. Xây dựng Orchestrator điều phối các agent theo mục tiêu và trạng thái học tập.
2. Trả lời kiến thức dựa trên tài liệu của đúng môn và có citation kiểm chứng được.
3. Đánh giá mức độ thành thạo của người học theo từng concept.
4. Lập kế hoạch học theo mục tiêu, thời gian và kiến thức còn yếu.
5. Tự động cập nhật mastery và đề xuất điều chỉnh kế hoạch sau mỗi bài kiểm tra.
6. Có Verification Agent kiểm tra câu trả lời, câu hỏi và kế hoạch trước khi sử dụng.
7. Cho phép quản trị viên nạp, kiểm tra, duyệt và kích hoạt môn học mới.
8. Chứng minh việc thêm môn minh chứng không cần sửa agent, workflow và database schema cốt lõi.

## 3. Trọng tâm để không lạc đề tài

Thứ tự ưu tiên của đồ án:

1. **Multi-agent orchestration**.
2. **Tự động hóa chu trình học tập**.
3. **Grounded RAG và verification**.
4. **Cá nhân hóa bằng BKT**.
5. **MCP tool integration**.
6. **Nạp và quản lý nhiều môn**.
7. **Giao diện người dùng**.

Course management chỉ cung cấp dữ liệu cho agent. Không phát triển thành hệ thống quản lý đào tạo, lớp học hoặc học phí.

## 4. Người sử dụng

### Sinh viên

- Chọn môn đang học.
- Hỏi kiến thức và xem nguồn trích dẫn.
- Làm bài kiểm tra đầu vào hoặc bài luyện tập.
- Khai báo mục tiêu và thời gian học.
- Xem, duyệt và thực hiện kế hoạch.
- Theo dõi concept mạnh/yếu và tiến độ.

### Giảng viên hoặc quản trị nội dung

- Tạo môn học ở trạng thái nháp.
- Nạp giáo trình, đề cương và ngân hàng câu hỏi.
- Xem lỗi xử lý tài liệu.
- Duyệt concept, quan hệ, câu hỏi và citation.
- Kích hoạt hoặc khóa một phiên bản môn học.

Không xây vai trò quản trị trường học trong phạm vi đồ án.

## 5. Hệ thống đa tác tử tối thiểu

| Agent | Trách nhiệm chính | Không được làm |
| --- | --- | --- |
| Orchestrator Agent | Hiểu mục tiêu, chọn agent/tool, theo dõi trạng thái và quyết định bước tiếp theo | Tự trả lời kiến thức khi chưa gọi Knowledge Agent |
| Knowledge Agent | Tìm tài liệu, giải thích kiến thức và tạo citation | Tự sửa mastery hoặc kế hoạch học |
| Assessment Agent | Chọn câu hỏi, chấm bài và xác định concept yếu | Tự kích hoạt lịch học bên ngoài |
| Planning Agent | Tạo hoặc điều chỉnh lộ trình học | Bỏ qua mục tiêu, thời gian và prerequisite |
| Verification Agent | Kiểm tra citation, câu hỏi, độ khó và ràng buộc kế hoạch | Tự tạo nội dung mới thay agent bị từ chối |

Một workflow chỉ được coi là multi-agent khi:

- Orchestrator chọn nhánh xử lý theo trạng thái thực tế.
- Mỗi agent có input, output và tool riêng.
- Output của agent trước được dùng bởi agent sau.
- Verification Agent có thể trả về `PASS`, `REVISE` hoặc `BLOCK`.
- Số vòng sửa lỗi được giới hạn tối đa 2 lần ở bản đầu.
- Log thể hiện agent nào đã thực hiện hành động nào.

Việc đặt nhiều tên agent nhưng tất cả cùng dùng một prompt và chạy tuần tự cố định không được coi là đạt yêu cầu.

## 6. Use case bắt buộc

### UC01 - Hỏi đáp kiến thức có dẫn nguồn

1. Sinh viên chọn môn.
2. Sinh viên đặt câu hỏi.
3. Orchestrator gọi Knowledge Agent.
4. Knowledge Agent truy xuất tài liệu theo `course_id` và `course_version`.
5. Verification Agent kiểm tra câu trả lời và citation.
6. Hệ thống trả lời hoặc thông báo chưa đủ căn cứ.

Kết quả bắt buộc: citation gồm tài liệu, chương hoặc mục, số trang và chunk nếu có.

### UC02 - Kiểm tra chẩn đoán

1. Sinh viên chọn mục tiêu học.
2. Assessment Agent lấy câu hỏi theo các concept liên quan.
3. Sinh viên trả lời.
4. Hệ thống chấm và cập nhật BKT.
5. Hệ thống trả về concept mạnh, yếu và giải thích.

### UC03 - Lập kế hoạch học cá nhân

1. Sinh viên nhập ngày thi, số ngày và số phút học mỗi ngày.
2. Orchestrator lấy mục tiêu môn học và mastery hiện tại.
3. Planning Agent lập kế hoạch.
4. Verification Agent kiểm tra thời gian, prerequisite và độ phủ nội dung.
5. Sinh viên duyệt kế hoạch trước khi lưu.

### UC04 - Tự động điều chỉnh kế hoạch

1. Sinh viên hoàn thành bài luyện tập.
2. Assessment Agent cập nhật mastery.
3. Hệ thống phát hiện concept yếu hoặc tiến độ chậm.
4. Orchestrator gọi Planning Agent tạo thay đổi.
5. Verification Agent kiểm tra.
6. Sinh viên duyệt thay đổi lớn trước khi áp dụng.

Đây là use case chính thể hiện tính tự động hóa của đề tài.

### UC05 - Nạp môn học mới

1. Quản trị viên tạo `course_id` và phiên bản.
2. Tải giáo trình, đề cương và dữ liệu bổ sung.
3. Pipeline parse, chunk, index và đề xuất concept.
4. Hệ thống chạy validation.
5. Giảng viên duyệt dữ liệu quan trọng.
6. Môn được chuyển từ `DRAFT` sang `ACTIVE`.

Kết quả bắt buộc: môn mới sử dụng được bằng các agent hiện có mà không tạo workflow riêng.

### UC06 - Cô lập dữ liệu giữa các môn

1. Sinh viên chọn một môn.
2. Mọi retrieval và mastery đều được lọc theo môn.
3. Hệ thống không dùng nguồn của môn khác nếu truy vấn không cho phép liên môn.

## 7. Chu trình tự động hóa chính

```text
Người học đặt mục tiêu
        |
        v
Kiểm tra chẩn đoán
        |
        v
Cập nhật BKT mastery
        |
        v
Lập kế hoạch học
        |
        v
Verification + người học duyệt
        |
        v
Thực hiện phiên học và bài kiểm tra
        |
        v
Cập nhật mastery
        |
        +---- đạt mục tiêu ----> Hoàn thành
        |
        +---- chưa đạt --------> Tự đề xuất lập lại kế hoạch
```

Các event tối thiểu:

```text
GOAL_CREATED
DIAGNOSTIC_COMPLETED
PLAN_PROPOSED
PLAN_APPROVED
QUIZ_COMPLETED
MASTERY_UPDATED
REPLAN_REQUIRED
PLAN_COMPLETED
```

## 8. Yêu cầu nạp nhiều môn dễ dàng

### Yêu cầu bắt buộc

- Mọi bảng dữ liệu học tập có `course_id` khi phù hợp.
- Nội dung đã xuất bản có `course_version`.
- Mỗi môn có vector collection/alias và graph namespace riêng.
- Prompt của agent không hard-code tên môn.
- Tool nhận `course_id` thay vì gọi database của một môn cố định.
- Cấu hình môn nằm trong Course Package.
- Có trạng thái `DRAFT`, `PROCESSING`, `REVIEW_REQUIRED`, `VALIDATED`, `ACTIVE` và `ARCHIVED`.
- Có validation trước khi kích hoạt môn.

### Tiêu chí thành công

Khi nạp môn Tư tưởng Hồ Chí Minh làm minh chứng:

- Không sửa code của năm agent.
- Không sửa LangGraph workflow.
- Không sửa schema database cốt lõi.
- Không tạo MCP server mới.
- Chỉ thêm Course Package, cấu hình và dữ liệu đánh giá của môn.

Nếu môn mới có loại bài tập hoàn toàn khác, hệ thống có thể cần thêm assessment adapter. Trường hợp này nằm ngoài minh chứng chính của đồ án.

## 9. Yêu cầu dữ liệu

### Nguồn được sử dụng

- Giáo trình chính thức hoặc tài liệu được nhà trường chấp nhận.
- Đề cương môn học và chuẩn đầu ra.
- Ngân hàng câu hỏi có đáp án hoặc rubric.
- Tài liệu phải có quyền sử dụng phù hợp và thông tin nguồn rõ ràng.

### Metadata tối thiểu

```text
course_id
course_version
document_id
document_title
chapter_id
section_id
page_number
source_type
source_authority
```

Không đưa nguồn web không kiểm soát vào knowledge base chính trong phiên bản đồ án.

## 10. Quyết định kỹ thuật được khóa

| Thành phần | Quyết định Giai đoạn 1 |
| --- | --- |
| Backend | FastAPI |
| Frontend | React/Vite |
| Orchestration | LangGraph |
| LLM bản final | Kimi |
| LLM khi phát triển | Gemini qua provider abstraction |
| Database nghiệp vụ | PostgreSQL |
| Vector database | Qdrant |
| Retrieval | BM25 + vector + RRF + concept graph expansion |
| Cá nhân hóa | Bayesian Knowledge Tracing cơ bản |
| Tool protocol | Một `academic-learning-mcp` server |
| Graph storage bản đầu | PostgreSQL hoặc cấu trúc đơn giản; chưa bắt buộc Neo4j |
| Câu hỏi | Trắc nghiệm và trả lời ngắn |

## 11. Yêu cầu phi chức năng

- Không trộn dữ liệu giữa các user và giữa các môn.
- Các hành động ghi dữ liệu phải chống thực hiện trùng.
- Agent loop luôn có giới hạn.
- Lỗi nội bộ không được trả trực tiếp ra giao diện.
- Có log theo `request_id`, `session_id`, agent và tool.
- Không ghi API key vào source code hoặc log.
- Câu trả lời thiếu evidence phải từ chối hoặc nói rõ giới hạn.
- Các thay đổi lớn với lịch học phải được người dùng duyệt.
- Một phiên bản môn đang `ACTIVE` không bị ghi đè trực tiếp.

## 12. Câu hỏi nghiên cứu

### RQ1 - Multi-agent

Hệ thống đa tác tử có tăng tỷ lệ hoàn thành đúng nhiệm vụ và tuân thủ ràng buộc so với một agent đơn không?

So sánh bằng Task Completion Rate, Tool Selection Accuracy và Planning Constraint Satisfaction.

### RQ2 - Verification

Verification Agent có làm giảm câu trả lời thiếu căn cứ, citation sai và kế hoạch không hợp lệ không?

So sánh hệ thống có và không có Verification Agent.

### RQ3 - Cá nhân hóa và tự động hóa

BKT kết hợp adaptive replanning có tạo lựa chọn câu hỏi và kế hoạch phù hợp với trạng thái người học hơn cách tính điểm và lập kế hoạch tĩnh không?

Đánh giá bằng tình huống học mô phỏng, đánh giá chuyên gia và thử nghiệm người dùng nhỏ nếu có điều kiện.

Khả năng nạp nhiều môn là mục tiêu kỹ thuật cần chứng minh, không cần tách thành câu hỏi nghiên cứu thứ tư.

## 13. Bộ chỉ số và ngưỡng mục tiêu

Đây là ngưỡng mong muốn để kiểm thử, chưa phải kết quả đã đạt.

| Nhóm | Chỉ số | Mục tiêu ban đầu |
| --- | --- | ---: |
| Retrieval | Recall@5 | >= 85% |
| Grounding | Citation Accuracy | >= 90% |
| Grounding | Faithfulness | >= 90% |
| Safety | Cross-course leakage | 0 case trong bộ test cô lập môn |
| Agent | Task Completion Rate | >= 85% |
| Agent | Tool Selection Accuracy | >= 90% |
| Planning | Constraint Satisfaction | >= 90% |
| Verification | Lỗi hợp lệ được phát hiện | >= 85% |
| Automation | Event processing success | >= 95% trong integration test |
| Automation | Duplicate write | 0 trong test idempotency |
| Multi-course | Sửa core code khi nạp môn minh chứng | 0 file |

Nếu không đạt ngưỡng, báo cáo phải trình bày nguyên nhân và giới hạn thay vì sửa số liệu.

## 14. Dữ liệu đánh giá tối thiểu

### Môn chính

- Tối thiểu 100 câu hỏi retrieval/QA có đáp án và citation chuẩn.
- Tối thiểu 30 câu hỏi đánh giá kiến thức theo concept.
- Tối thiểu 15 kịch bản multi-agent hoàn chỉnh.
- Có câu hỏi định nghĩa, so sánh, quan hệ, vận dụng ngắn và ngoài phạm vi.

### Môn minh chứng

- Tối thiểu 30 câu hỏi retrieval/QA.
- Có câu hỏi cố tình gây nhiễu giữa hai môn.
- Có ít nhất 3 kịch bản hỏi đáp hoặc đánh giá dùng chung workflow.

## 15. Phạm vi không làm

- Không xây LMS hoàn chỉnh.
- Không quản lý lớp, học phí, điểm danh hoặc bảng điểm chính thức.
- Không triển khai đầy đủ tất cả môn chính trị.
- Không dùng DKT khi chưa có dataset lịch sử đủ lớn.
- Không fine-tune mô hình lớn trong phiên bản đầu.
- Không chấm tự động bài luận dài.
- Không cho agent tự gửi email hoặc thay đổi lịch bên ngoài mà chưa được duyệt.
- Không xây full GraphRAG hoặc nhiều MCP server nếu phần cốt lõi chưa hoàn thiện.

## 16. Kịch bản demo cuối khóa

1. Admin nạp và kích hoạt môn Triết học Mác - Lênin.
2. Sinh viên chọn môn và đặt mục tiêu ôn trong 7 ngày, mỗi ngày 45 phút.
3. Orchestrator gọi Assessment Agent kiểm tra đầu vào.
4. BKT ghi nhận các concept yếu.
5. Planning Agent lập lộ trình.
6. Verification Agent phát hiện một ràng buộc chưa phù hợp và yêu cầu sửa.
7. Sinh viên duyệt kế hoạch đã sửa.
8. Sau bài luyện tập, hệ thống cập nhật mastery và tự đề xuất điều chỉnh kế hoạch.
9. Câu trả lời kiến thức hiển thị citation từ giáo trình.
10. Admin nạp 1-2 chương Tư tưởng Hồ Chí Minh bằng Course Package.
11. Hệ thống sử dụng lại agent và workflow mà không sửa core code.

## 17. Điều kiện kết thúc Giai đoạn 1

- [x] Tên đề tài được giữ nguyên và hướng triển khai không mâu thuẫn.
- [x] Chốt một môn chính và một môn minh chứng.
- [x] Chốt hai vai trò người dùng.
- [x] Chốt năm agent và trách nhiệm riêng.
- [x] Chốt sáu use case bắt buộc.
- [x] Chốt chu trình tự động hóa chính.
- [x] Chốt nguyên tắc nạp nhiều môn bằng cấu hình.
- [x] Chốt ba câu hỏi nghiên cứu.
- [x] Chốt metric và ngưỡng mục tiêu ban đầu.
- [x] Chốt rõ những phần không làm.
- [x] Có một kịch bản demo bám sát đề tài.

Giai đoạn tiếp theo là **Giai đoạn 2: tạo schema dùng chung, Course Registry và lớp chuyển đổi Gemini/Kimi**.
