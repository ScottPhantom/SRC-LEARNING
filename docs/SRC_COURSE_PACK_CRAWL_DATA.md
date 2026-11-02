# SRC Course Pack — Đặc tả Bước 1: Crawl Data

> Trạng thái: Draft v0.1
> Cập nhật: 14/08/2026
> Đối tượng chính: developer của SRC LEARNING APP

## 1. Tổng quan

**SRC Course Pack** là công cụ nội bộ hỗ trợ đội phát triển SRC LEARNING thu thập ảnh đề thi cũ từ kho tài liệu công khai [FUOverflow — Tài liệu các môn học](https://fuoverflow.com/categories/subjects/). Kết quả crawl là dữ liệu thô có nguồn gốc rõ ràng, dùng làm đầu vào cho các bước kiểm tra, phân loại câu hỏi, tạo đáp án và đưa vào ngân hàng đề của SRC LEARNING.

Bước đầu tiên chỉ giải quyết bài toán: **developer nhập mã/tên môn học và tool tự tìm, duyệt, tải các ảnh/tệp phù hợp của môn đó**.

## 2. Mục tiêu và phạm vi

### 2.1. Mục tiêu

- Cho phép nhập mã môn, ví dụ `ITE302c`, không phân biệt hoa/thường.
- Tìm đúng chuyên mục môn học dù môn nằm trong Kỳ 0–9 hoặc “Tổng hợp – Chưa rõ kỳ”.
- Duyệt toàn bộ các trang của chuyên mục môn, không chỉ trang đầu.
- Chỉ lấy các bài đăng đề thi phù hợp, ưu tiên prefix **Đề Thi FE**.
- Thu thập metadata của bài đăng và tải ảnh/tệp đính kèm từ các host được cho phép.
- Chống tải trùng, hỗ trợ chạy lại và tiếp tục sau lỗi.
- Sinh manifest và báo cáo để developer kiểm tra nguồn, số lượng và lỗi.
- Không làm hỏng hoặc ghi đè dữ liệu ngân hàng đề đang active.

### 2.2. Ngoài phạm vi Bước 1

- OCR nội dung và đáp án.
- Cắt một ảnh dài thành từng câu hỏi.
- Phân loại ảnh vào `Fill_blanks`, `Selections_1_choose`, `Selections_Multiple_choose`, `True_False`.
- Tự xác nhận đáp án đúng.
- Đưa dữ liệu thô trực tiếp vào `DATA/<Môn học>` của SRC LEARNING.
- Crawl tài liệu cần đăng nhập, vượt CAPTCHA, né rate limit hoặc vượt cơ chế kiểm soát truy cập.
- Crawl toàn bộ website khi người dùng chỉ yêu cầu một môn.

## 3. Cấu trúc nguồn đã xác minh

Kiểm tra công khai ngày 14/08/2026 cho thấy nguồn có cấu trúc logic:

```text
TÀI LIỆU CÁC MÔN HỌC
├── Tổng hợp – Chưa rõ kỳ
├── Kỳ 0 … Kỳ 9
│   └── Forum môn học, ví dụ ITE302c
│       └── Thread đề thi
│           ├── Prefix, ví dụ: Đề Thi FE
│           ├── Tiêu đề, ví dụ: ITE302c - SU 2024 - FE
│           ├── Metadata: campus, học kỳ, loại tài liệu
│           ├── Bài viết gốc và phản hồi
│           └── Ảnh/tệp đính kèm
└── File ảnh có thể được phục vụ từ data.fuoverflow.com
```

Các trang tham chiếu:

- [Danh mục các môn học](https://fuoverflow.com/categories/subjects/)
- [Ví dụ forum ITE302c](https://fuoverflow.com/forums/ITE302c/)
- [Ví dụ thread ITE302c - SU 2024 - FE](https://fuoverflow.com/threads/ite302c-su-2024-fe.2529/)
- [Điều khoản và luật lệ](https://fuoverflow.com/help/terms/)

Lưu ý: website đang dùng XenForo và HTML có thể thay đổi. Crawler không được phụ thuộc duy nhất vào vị trí phần tử hoặc class CSS khó ổn định; cần có parser test bằng HTML fixture.

## 4. Trải nghiệm sử dụng đề xuất

### 4.1. CLI cho MVP

```bash
python tools/crawl_course_data.py --subject ITE302c
```

Các tùy chọn dự kiến:

```text
--subject CODE          Mã môn bắt buộc
--output-dir PATH       Mặc định: CRAWL_DATA
--exam-type TYPE        Mặc định: FE
--dry-run               Chỉ liệt kê nguồn và kế hoạch tải
--resume                Tiếp tục phiên trước; mặc định bật
--max-threads N         Giới hạn số thread để test
--request-delay SEC     Khoảng nghỉ tối thiểu giữa request
--refresh               Kiểm tra lại URL đã crawl bằng metadata HTTP
```

Ví dụ kết quả trên terminal:

```text
Môn học: ITE302c
Chuyên mục: https://fuoverflow.com/forums/ITE302c/
Thread phù hợp: 14
File phát hiện: 326
Mới tải: 320 | Đã có: 6 | Lỗi: 0
Manifest: CRAWL_DATA/ITE302c/manifest.json
```

### 4.2. GUI sau MVP

Khi CLI ổn định, có thể thêm màn hình dành cho developer gồm:

1. Ô nhập mã môn.
2. Nút “Kiểm tra nguồn” để chạy dry-run.
3. Bộ lọc loại đề: FE mặc định; RE/PE là tùy chọn tương lai.
4. Bảng thread tìm được với checkbox chọn/bỏ chọn.
5. Thanh tiến trình và log lỗi.
6. Nút “Mở thư mục dữ liệu thô”.

GUI chỉ gọi service dùng chung với CLI, không chứa logic crawl riêng.

## 5. Luồng xử lý

```text
Nhập mã môn
  → Chuẩn hóa và kiểm tra input
  → Đọc trang danh mục môn học
  → Tìm chính xác forum của môn
  → Duyệt pagination của forum
  → Lọc thread theo prefix/metadata/tiêu đề
  → Duyệt pagination của từng thread
  → Trích xuất attachment từ bài gốc và phản hồi
  → Xác thực URL, host, MIME và kích thước
  → Tải file vào vùng staging
  → Kiểm tra ảnh + tính SHA-256
  → Chống trùng và ghi manifest nguyên tử
  → Sinh summary/report
```

### 5.1. Chuẩn hóa input

- Trim khoảng trắng và chuẩn hóa Unicode NFC.
- Chấp nhận `ite302c`, lưu canonical là `ITE302c` khi tìm thấy forum tương ứng.
- Chỉ chấp nhận mã an toàn theo cấu hình, đề xuất `^[A-Za-z0-9_-]{2,20}$`.
- Không dùng input trực tiếp để ghép đường dẫn; tên thư mục phải qua hàm sanitize.
- Nếu có nhiều kết quả gần giống, không tự chọn bằng fuzzy match; hiển thị danh sách ứng viên.

### 5.2. Tìm forum môn học

Thứ tự ưu tiên:

1. Đọc danh mục gốc và lấy liên kết có label trùng mã môn sau khi case-fold.
2. Duyệt cả “Tổng hợp – Chưa rõ kỳ” và Kỳ 0–9.
3. Lưu `term_bucket`, `subject_code`, `subject_forum_url` vào manifest.
4. Nếu không tìm thấy, trả lỗi `SUBJECT_NOT_FOUND` và gợi ý các mã gần nhất; không tạo dữ liệu rỗng như một phiên thành công.

### 5.3. Lọc thread

Một thread được chọn khi thỏa ít nhất một tín hiệu mạnh và không có tín hiệu loại trừ:

- Prefix hiển thị là `Đề Thi FE`; hoặc
- Metadata `Loại tài liệu = FE`; hoặc
- Tiêu đề kết thúc/chứa token độc lập `FE`.

Không dùng phép kiểm tra substring đơn giản vì `FE` có thể xuất hiện bên trong token khác. Nếu các tín hiệu mâu thuẫn, đánh dấu `needs_review` thay vì tự tải trong chế độ mặc định.

Parser nên lưu cả tiêu đề thô và các trường chuẩn hóa nếu nhận diện được:

```json
{
  "subject": "ITE302c",
  "season": "SU",
  "year": 2024,
  "exam_type": "FE",
  "campus": "Hà Nội"
}
```

Không giả định mọi tiêu đề đều cùng một format; ví dụ thực tế có thể viết `SP24`, `SP 2025`, `FESP24` hoặc thiếu dấu phân cách.

### 5.4. Trích xuất tệp

- Quét bài viết gốc và phản hồi vì ảnh/tệp bổ sung có thể nằm trong reply.
- Ưu tiên URL attachment/original, không tải thumbnail nếu có bản gốc công khai.
- Resolve URL tương đối bằng URL của trang hiện tại.
- Chỉ cho phép `https` và hostname trong allowlist cấu hình, ban đầu gồm `fuoverflow.com` và `data.fuoverflow.com` cùng subdomain được duyệt rõ ràng.
- Không gửi cookie/token sang host ngoài allowlist.
- Chấp nhận theo MIME và magic bytes, không tin phần mở rộng URL.
- MVP hỗ trợ ảnh `image/jpeg`, `image/png`, `image/webp`; file khác ghi vào manifest là `unsupported`, không âm thầm bỏ qua.
- Dùng streaming download, giới hạn kích thước cấu hình và timeout cho mỗi request.

### 5.5. Chống trùng và chạy lại

- Khóa nguồn: URL canonical sau khi bỏ fragment và tracking query không cần thiết.
- Khóa nội dung: SHA-256 của bytes đã tải.
- Cùng URL, cùng hash: `unchanged`.
- URL khác, cùng hash: chỉ giữ một blob vật lý và ghi nhiều source reference.
- Cùng URL, hash mới: tạo revision mới, không ghi đè lịch sử.
- Ghi file tạm, verify, sau đó atomic rename; file tải dở không được xem là thành công.
- Manifest cập nhật sau mỗi file thành công để `--resume` không tải lại toàn bộ.

## 6. Cấu trúc dữ liệu đầu ra

Dữ liệu crawl nằm ở vùng staging riêng:

```text
CRAWL_DATA/
└── ITE302c/
    ├── manifest.json
    ├── crawl.log
    ├── reports/
    │   └── crawl-20260814T120000+0700.json
    ├── blobs/
    │   └── <sha256>.<ext>
    └── threads/
        └── 2529/
            ├── thread.json
            └── attachments.json
```

Không lưu trực tiếp theo tên attachment gốc vì ví dụ thực tế có nhiều file cùng tên trong một thread. Hash nội dung là tên blob an toàn và ổn định.

### 6.1. Manifest tối thiểu

```json
{
  "schema_version": 1,
  "crawler_version": "0.1.0",
  "subject": {
    "input": "ite302c",
    "code": "ITE302c",
    "term_bucket": "Kỳ 5",
    "forum_url": "https://fuoverflow.com/forums/ITE302c/"
  },
  "source": {
    "site": "FUOverflow",
    "category_url": "https://fuoverflow.com/categories/subjects/",
    "crawled_at": "2026-08-14T12:00:00+07:00"
  },
  "filters": {
    "exam_type": "FE"
  },
  "threads": [],
  "summary": {
    "threads_discovered": 0,
    "threads_selected": 0,
    "files_discovered": 0,
    "files_downloaded": 0,
    "files_duplicate": 0,
    "files_failed": 0
  }
}
```

Mỗi attachment cần lưu tối thiểu:

- `source_url`, `thread_url`, `thread_id`, `post_id` nếu có.
- `original_name`, `content_type`, `content_length` nếu có.
- `sha256`, `local_blob`, `downloaded_at`.
- `http_status`, `status`, `error_code`, `error_message`.
- `width`, `height`, `detected_format` sau khi verify ảnh.

## 7. Kiến trúc phần mềm đề xuất

```text
tools/crawl_course_data.py             # CLI adapter
app/services/course_crawler/
├── service.py                         # Điều phối use case
├── client.py                          # HTTP, retry, rate limit
├── discovery.py                       # Tìm forum và pagination
├── parsers.py                         # Parse category/forum/thread
├── filters.py                         # Quy tắc chọn thread
├── downloader.py                      # Streaming + verify + hash
├── storage.py                         # Blob, manifest, atomic write
├── models.py                          # Dataclass/domain models
└── errors.py                          # Error code ổn định
tests/
├── fixtures/course_crawler/           # HTML đã rút gọn, không chứa ảnh đề
├── test_course_crawler_parsers.py
├── test_course_crawler_filters.py
├── test_course_crawler_storage.py
└── test_course_crawler_e2e.py
```

HTTP client và parser phải tách rời để unit test không gọi website thật. Test online chỉ là smoke test thủ công/định kỳ và phải có giới hạn request thấp.

Đề xuất thêm dependency khi bắt đầu code:

- `httpx`: HTTP client, timeout, redirect và streaming.
- `beautifulsoup4` + `lxml`: parse HTML chịu lỗi tốt.
- `Pillow` hiện đã có trong dự án, dùng verify/đọc metadata ảnh. Cần xác nhận build Pillow hỗ trợ WebP.

## 8. Vận hành có trách nhiệm và an toàn

Trước khi chạy crawl production, đội dự án cần xác nhận quyền sử dụng/tái phân phối dữ liệu với chủ website và người sở hữu nội dung khi cần. Điều khoản FUOverflow nêu rằng nội dung do người dùng đăng vẫn thuộc quyền sở hữu của người đăng và tài liệu phục vụ mục đích tham khảo/học tập cá nhân; vì vậy dữ liệu thu thập không mặc nhiên được phép phát hành lại trong sản phẩm.

Crawler bắt buộc:

- Tôn trọng `robots.txt`, điều khoản hiện hành và yêu cầu gỡ bỏ.
- Dùng User-Agent nhận diện rõ công cụ và kênh liên hệ của dự án.
- Giới hạn concurrency thấp; mặc định đề xuất 1–2 request đồng thời và delay tối thiểu 1 giây, sau đó điều chỉnh theo phản hồi máy chủ/chủ website.
- Retry có exponential backoff + jitter cho lỗi tạm thời; tôn trọng `Retry-After`.
- Dừng hoặc giảm tốc khi gặp `429`, `403`, CAPTCHA hoặc dấu hiệu chặn.
- Không đăng nhập tự động, không vượt kiểm soát truy cập, không thu thập dữ liệu cá nhân không cần thiết.
- Không log cookie, token hoặc query chứa bí mật.
- Giữ URL nguồn và metadata provenance để xử lý yêu cầu xóa.

## 9. Xử lý lỗi

Các mã lỗi ổn định đề xuất:

| Mã | Ý nghĩa | Hành vi |
|---|---|---|
| `INVALID_SUBJECT` | Input không hợp lệ | Dừng trước khi gọi mạng |
| `SUBJECT_NOT_FOUND` | Không có forum trùng khớp | Dừng, gợi ý ứng viên |
| `SOURCE_BLOCKED` | 403/CAPTCHA/kiểm soát truy cập | Dừng an toàn |
| `RATE_LIMITED` | 429 | Chờ theo `Retry-After`, giới hạn retry |
| `PARSE_CHANGED` | Không tìm thấy cấu trúc bắt buộc | Lưu diagnostic HTML đã làm sạch |
| `DOWNLOAD_FAILED` | Timeout/5xx/mất kết nối | Retry rồi ghi lỗi |
| `UNSUPPORTED_FILE` | MIME/format ngoài phạm vi | Ghi manifest, không import |
| `CORRUPT_IMAGE` | Bytes không phải ảnh hợp lệ | Cách ly file, ghi lỗi |
| `STORAGE_FAILED` | Không thể ghi file/manifest | Dừng để tránh trạng thái sai |

Một file lỗi không làm hỏng toàn bộ phiên crawl, trừ lỗi quyền truy cập, storage hoặc dấu hiệu website yêu cầu dừng.

## 10. Kiểm thử

### 10.1. Unit test

- Chuẩn hóa mã môn và chặn path traversal.
- Tìm đúng môn ở mỗi kỳ và “Chưa rõ kỳ”.
- Duyệt pagination không lặp vô hạn.
- Nhận diện FE theo prefix, metadata và token tiêu đề.
- Không nhầm `FE` với substring khác.
- Trích xuất ảnh từ bài gốc và reply.
- Resolve URL, chặn scheme/host không hợp lệ.
- Nhận biết MIME giả bằng magic bytes/Pillow.
- Deduplicate theo URL và SHA-256.
- Atomic write và resume sau khi process bị dừng.

### 10.2. Integration test

Dùng mock HTTP server với các trường hợp:

- Nhiều trang forum và thread.
- Redirect attachment sang host ảnh hợp lệ.
- 429 có `Retry-After`, 500 tạm thời, timeout.
- Hai URL trả cùng nội dung.
- Attachment đổi nội dung giữa hai lần chạy.
- HTML thiếu selector do layout thay đổi.

### 10.3. Smoke test thủ công

```bash
python tools/crawl_course_data.py --subject ITE302c --dry-run --max-threads 2
```

Smoke test không được tải cả môn và không chạy trong CI mặc định.

## 11. Tiêu chí nghiệm thu MVP

- Nhập `ite302c` tìm đúng forum `ITE302c`.
- Dry-run liệt kê các thread FE và không tải attachment.
- Chế độ thật duyệt được pagination của forum và thread.
- Tải được ảnh JPEG/PNG/WebP công khai, verify được ảnh và ghi SHA-256.
- Chạy lại không tải lại file không đổi.
- Dừng giữa chừng rồi chạy lại có thể tiếp tục.
- Tệp trùng nội dung không tạo blob thứ hai.
- Mỗi file truy vết được về thread, post và URL nguồn.
- Không có file thô nào được ghi trực tiếp vào `DATA/`.
- Gặp 403/CAPTCHA thì dừng, không tìm cách vượt qua.
- Test parser/filter/storage chạy offline và không phụ thuộc website thật.
- Báo cáo cuối khớp số thread/file thành công, trùng, bỏ qua và thất bại.

## 12. Lộ trình triển khai

### Milestone 1 — Discovery và dry-run

- Domain models, HTTP client có rate limit.
- Parser trang danh mục và forum.
- Subject lookup, pagination, lọc FE.
- CLI `--dry-run` và unit test bằng fixture.

### Milestone 2 — Download và provenance

- Parse thread/post/attachment.
- Streaming download, validation, SHA-256.
- Blob storage, manifest, deduplication, resume.
- Báo cáo phiên crawl.

### Milestone 3 — Hardening

- Retry/backoff, 429/403 handling.
- Revision tracking, refresh và quarantine.
- Integration test với mock server.
- Tài liệu vận hành và quy trình gỡ dữ liệu.

### Milestone 4 — Kết nối pipeline SRC LEARNING

- Tool review dữ liệu thô.
- Chuyển WebP sang format đầu vào nếu pipeline sau cần thiết, giữ nguyên blob gốc.
- Tách/crop câu hỏi và phân loại category ở một bước độc lập.
- Chỉ import dữ liệu đã review vào quy trình version hóa ngân hàng đề hiện có.

## 13. Quyết định thiết kế ban đầu

- **CLI-first:** phù hợp developer và giúp kiểm thử logic trước khi làm GUI.
- **Staging riêng:** `CRAWL_DATA` không trộn với `DATA` đang được app quét.
- **Content-addressed storage:** tránh trùng khi nhiều attachment có cùng tên hoặc URL khác nhau.
- **Manifest-first:** mọi ảnh đều có provenance và trạng thái xử lý.
- **Public-only, polite crawler:** không tự động hóa đăng nhập hoặc vượt bảo vệ website.
- **FE mặc định:** đúng phạm vi hiện tại; RE/PE mở rộng bằng filter cấu hình sau.

## 14. Câu hỏi cần chốt trước khi code Milestone 2

1. Có crawl chỉ bài gốc hay cả attachment trong phản hồi? Đặc tả hiện chọn **cả hai** để tránh thiếu ảnh.
2. Chỉ lấy FE hay bao gồm RE/PE? Đặc tả hiện chọn **FE mặc định**.
3. Dữ liệu sau crawl chỉ dùng nội bộ hay sẽ phân phối cho người dùng SRC LEARNING? Cần xác nhận quyền sử dụng trước khi phân phối.
4. Có cần lưu nội dung text của bài viết/reply không? Đề xuất chỉ lưu metadata tối thiểu và source URL, trừ khi pipeline sau chứng minh cần text.
5. Ai là đầu mối liên hệ hiển thị trong User-Agent và tiếp nhận yêu cầu gỡ dữ liệu?
