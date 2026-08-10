# SRC LEARNING

Ứng dụng desktop ngoại tuyến bằng Python/PyQt5 để học từ ảnh theo ba chế độ:

- Flash Cards: nhấn `Space` để hiện đáp án, tự đánh dấu Đã thuộc/Chưa thuộc.
- Học cấp tốc: chia ngẫu nhiên thành vòng 10 câu; câu sai quay lại cuối hàng đợi.
- Mock Exam: trộn bốn nhóm câu, có đồng hồ, lưới đáp án, chấm điểm và lịch sử.

Giao diện và thông báo của ứng dụng sử dụng tiếng Việt. Tiến trình học và kết quả thi được lưu cục bộ trong `study_progress.sqlite3`.

Trước khi nâng cấp một database có schema cũ, ứng dụng tự tạo bản backup SQLite
nhất quán cùng thư mục, theo mẫu
`study_progress.pre-v<version>.<UTC timestamp>.sqlite3`. Migration chỉ bắt đầu
sau khi bản backup vượt qua `PRAGMA integrity_check`; nếu backup thất bại, ứng
dụng dừng khởi động và giữ nguyên database cũ.

Header toàn cục luôn hiển thị nút thương hiệu `SRC Learning`; nhấn nút này từ bất kỳ màn hình nào sẽ trở về màn hình chọn môn học. Trên Home, cụm Lịch sử/Làm mới/Cài đặt có animation hover 200 ms: phóng nhẹ khoảng 1,05×, đổi nền và tăng bóng xanh. Nếu Mock Exam còn đang làm, ứng dụng yêu cầu chọn hủy thao tác, nộp rồi thoát, hoặc thoát không lưu.

## Yêu cầu hệ thống

- Python 3.11 hoặc 3.12.
- Windows 10/11, macOS hoặc Linux có giao diện desktop.
- Tesseract OCR chỉ cần khi tạo `answers.csv`; Main App không chạy OCR.

## Cấu trúc dữ liệu

```text
DATA/
└── ITE303c/
    ├── Fill_blanks/
    ├── Selections_1_choose/
    ├── Selections_Multiple_choose/
    ├── True_False/
    └── answers.csv
```

Ứng dụng tự quét các thư mục cấp một trong `DATA`. Ảnh được hỗ trợ: `.png`, `.jpg`, `.jpeg`.

`answers.csv` dùng UTF-8, có đúng hai cột. `image_name` phải gồm cả tên thư mục loại câu:

```csv
image_name,correct_answer
Selections_1_choose/Câu 119.png,B
Selections_Multiple_choose/Câu 100.png,BCD
```

Quy tắc đáp án:

- `Selections_1_choose`, `Fill_blanks`: một ký tự A–D.
- `True_False`: A hoặc B.
- `Selections_Multiple_choose`: 2–4 ký tự khác nhau A–D, ví dụ `ACD`.

Câu không có đáp án hợp lệ vẫn dùng được trong Flashcard; Cramming tự chấm và Mock Exam chỉ dùng các câu có đáp án hợp lệ.

## Cài đặt

### Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Cài Tesseract từ bản phân phối dành cho Windows, sau đó thêm thư mục chứa `tesseract.exe` vào biến môi trường `PATH`.

### macOS

```bash
brew install python@3.11 tesseract
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install python3.11-venv tesseract-ocr libgl1
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Tự động kích hoạt môi trường (không bắt buộc)

Repository có `.envrc` dùng được với `direnv` trên macOS, Linux, WSL và các
terminal tương thích POSIX. File tự nhận diện cả cấu trúc `.venv/bin` và
`.venv/Scripts`, đồng thời bỏ qua an toàn nếu virtual environment chưa được tạo:

```bash
direnv allow
```

`.envrc` không phải điều kiện bắt buộc để chạy ứng dụng. Trên Windows PowerShell
hoặc Command Prompt, sử dụng lệnh kích hoạt tương ứng trong phần Windows ở trên.

Kiểm tra Tesseract:

```bash
tesseract --version
```

Package Python `pytesseract` không chứa Tesseract binary. Nếu lệnh trên không chạy, công cụ OCR cũng không chạy.

## Tạo đáp án bằng OCR

Xử lý tất cả môn học:

```bash
python tools/build_answers.py --data-dir DATA
```

Chỉ xử lý một môn:

```bash
python tools/build_answers.py --data-dir DATA --subject ITE303c
```

Mặc định script giữ nguyên các đáp án hợp lệ đã được sửa thủ công. Muốn OCR lại toàn bộ:

```bash
python tools/build_answers.py --data-dir DATA --subject ITE303c --overwrite
```

Lưu vùng crop của các ảnh thất bại để kiểm tra:

```bash
python tools/build_answers.py --data-dir DATA --failed-crops ocr_failures
```

Vùng đáp án mặc định là 25% chiều rộng bên trái và 10% chiều cao cuối ảnh. Nếu bộ ảnh khác định dạng, truyền `x,y,width,height` theo tỷ lệ 0–1:

```bash
python tools/build_answers.py --data-dir DATA --region 0,0.88,0.30,0.12
```

Nếu OCR không đọc được hoặc trả về đáp án sai loại, script để trống `correct_answer`, in `WARNING` và tiếp tục. Mở CSV bằng trình soạn thảo hỗ trợ UTF-8 để điền các ô trống, không đổi tên hai cột.

## Chạy ứng dụng

```bash
python main.py
```

### Flash Cards

1. Chọn môn học → Học bình thường.
2. Nhấn `Space` hoặc nút đáp án để toggle hiện/ẩn đáp án.
3. Đáp án chuẩn từ `answers.csv` xuất hiện trong panel bên phải; ảnh câu hỏi luôn giữ trạng thái đã cắt đáp án.
4. Chọn “Đã thuộc” hoặc “Chưa thuộc”.
5. Có thể đóng ứng dụng và tiếp tục phiên sau.
6. Phím `→` bỏ qua câu hiện tại và đánh dấu Chưa thuộc; phím `←` mở lịch sử chỉ xem; `ESC` quay lại.
7. Nút “Học lại” kết thúc tiến trình hiện tại, xáo trộn và đưa phiên mới về câu 1. Sau khi hoàn thành câu cuối, ứng dụng tự gọi hành động này sau hộp thoại chúc mừng.

### Chi tiết môn học và góc yếu điểm

- Ba chế độ học dùng card vuông 264×264 px có thể click toàn bộ. Khi hover, card tăng mượt lên 317×317 px trong 240 ms, bóng đổ đậm hơn và hai card còn lại được làm mờ để tập trung thị giác.
- Vùng card được cố định theo kích thước hover tối đa nên animation không đẩy lệch tiêu đề hoặc dashboard. Chuyển từ menu môn học sang màn hình học dùng fade-out/fade-in tổng 300 ms.
- Tab thống kê có chiều rộng tối thiểu 130 px và padding ngang 16 px để nhãn tiếng Việt không bị cắt.
- Dashboard “Thống kê lỗi sai & Ôn tập nhanh” chia bốn tab theo loại câu và hiển thị tối đa 20 câu có tỷ lệ sai cao nhất.
- Mỗi dòng cho biết tên ảnh, số lần sai/tổng lượt làm và tỷ lệ sai. Double-click hoặc chọn dòng rồi nhấn `Space` để mở cửa sổ ôn tập nhanh với ảnh đã crop và đáp án đúng.
- Trong Quick Review, dùng `←`/`→` để duyệt các câu của tab hiện tại; ở biên danh sách phím tương ứng không làm gì. `Space` hoặc `Enter` đóng cửa sổ và trở về dashboard.
- Dữ liệu dashboard được chuẩn bị bởi `AdaptiveReviewService`; View không đọc SQLite trực tiếp.

### Phím tắt Image Viewer

- `Ctrl/Cmd` + `+` hoặc `=`: phóng to ảnh.
- `Ctrl/Cmd` + `-`: thu nhỏ ảnh.
- `Ctrl/Cmd` + `C`: sao chép pixmap đã crop vào clipboard.
- Shortcut có phạm vi cửa sổ nên vẫn hoạt động khi focus nằm ở sidebar hoặc nút điều khiển khác trong màn hình học/thi.

### Học cấp tốc

1. Mỗi chu kỳ xáo trộn toàn bộ câu và chia thành vòng 10 câu; vòng cuối có thể ít hơn 10.
2. Chọn đáp án bằng các nút vuông A–D rồi nhấn `Enter` để kiểm tra. Mỗi nút có gợi ý phím số tương ứng.
3. `Enter` chỉ chấm và cập nhật queue: câu đúng rời queue, câu sai xuống cuối queue. Kết quả xanh/đỏ được giữ nguyên trên màn hình cho tới khi người dùng chủ động điều hướng.
4. Sau khi chấm, dùng `→` để sang đầu queue kế tiếp hoặc `←` để xem câu liền trước ở chế độ chỉ đọc. `→` trước khi chấm chỉ hiện nhắc nhở, không tự tính sai và không đổi queue.
5. Cramming tự chấm nên chỉ dùng các câu có đáp án hợp lệ trong `answers.csv`.
6. Trạng thái queue được lưu ngay sau mỗi lần chấm.
7. Sidebar hiển thị các câu trong vòng hiện tại: xanh lá là đã đúng, đỏ là đã sai và còn trong queue, viền xanh dương là câu đang xem. Có thể click câu chưa hoàn thành để đưa câu đó lên đầu queue.
8. Câu chọn nhiều được chấm exact match: thiếu, dư hoặc chọn nhầm một phương án đều tính sai và quay lại cuối queue.
9. Mỗi lần chấm được lưu vào SQLite với tổng lượt làm, số lượt sai và tỷ lệ sai của từng câu.

### Mock Exam

1. Chọn các nhóm câu muốn trộn.
2. Chọn số câu/thời gian; chọn “Khác” để nhập số riêng.
   Số câu tối đa được cập nhật theo các loại đang tích. Nếu pool nhỏ hơn lựa chọn hiện tại, giao diện tự chuyển sang “Khác”, điền mức tối đa và không cho nhập vượt giới hạn.
3. Chọn chấm ngay hoặc chấm sau khi nộp.
4. Single choice và multiple choice dùng chung lưới nút bo góc; câu chọn nhiều cho phép bật đồng thời nhiều nút.
5. Bài thi đang dở không được khôi phục. Khi bấm Quay lại, `📖` hoặc đóng ứng dụng, hộp thoại cho phép `Cancel`, `Yes — Nộp và Thoát` để chấm/lưu lịch sử, hoặc `No — Thoát và Không lưu`.
6. Lưới điều hướng đổi xanh `#30D158` cho câu đúng, đỏ `#FF453A` cho câu sai, nền sẫm cho câu đã trả lời và viền xanh dương cho câu hiện tại.
7. Có thể click trực tiếp một ô số để chuyển câu (chế độ chấm ngay yêu cầu xác nhận câu hiện tại trước).
8. `ExamBankAllocator` chia số câu theo tỷ trọng category bằng constrained largest-remainder. Category lớn nhất ưu tiên câu có exposure thấp để phủ ngân hàng; mỗi category thiểu số dành khoảng 40% quota cho câu từng sai và lấy ngẫu nhiên phần còn lại. Tổng quota luôn đúng số câu của đề và không có câu trùng trong cùng đề.
9. Màn hình kết quả có menu `↻ RE-Test`: tạo ngay đề mới bằng đúng cấu hình vừa dùng hoặc quay về màn hình cấu hình để chọn option khác.
10. Kết quả chi tiết hiển thị bằng bảng 3 cột `NO / Correct answer / Điểm`; chọn một hàng để mở ảnh review. Hàng Total hiển thị tổng điểm và `PASS` từ 7.0 điểm trở lên, ngược lại là `FAIL`.
11. Lịch sử bài thi được gom theo cây hai cấp `📁 Môn học → Bài thi #ID`; thời gian được đổi sang múi giờ máy và hiển thị `dd/MM/yyyy HH:mm`. Chỉ node bài thi có thể được chọn bằng `Ctrl/Cmd` hoặc `Shift` để dùng `🗑️ Xóa bài thi`; node môn học không thể xóa. Việc xóa luôn yêu cầu xác nhận và xóa cascade toàn bộ chi tiết câu trả lời liên quan.

### Phím tắt khi học/làm bài

- `1`–`8` hoặc `A`–`H`: bật/tắt đáp án tương ứng nếu câu hỏi có lựa chọn đó.
- `Enter`: kiểm tra câu Cramming hoặc câu Mock Exam chấm ngay; trong chế độ chấm cuối, mở xác nhận nộp bài.
- `←` / `→`: câu trước / câu tiếp. Trong Cramming, chỉ được sang câu tiếp sau khi đã chấm bằng `Enter`.

#### Cách chấm điểm

Bài thi dùng thang 10. Với `N` câu, mỗi câu có tối đa `10/N` điểm. Câu chọn một phải đúng hoàn toàn. Câu chọn nhiều được chấm từng phần:

```text
max(0, (số lựa chọn đúng - số lựa chọn sai) × ((10/N) / tổng đáp án đúng))
```

Điểm tổng và điểm từng câu được lưu dạng float, làm tròn hai chữ số thập phân. Xem đặc tả đầy đủ tại `docs/PHASE_5_MOCK_EXAM.md`.

### Điều khiển ảnh

Mọi màn hình học/thi có toolbar nổi `+`, `↻`, `−`, `📋` để phóng to, đưa về chế độ vừa màn hình, thu nhỏ và sao chép ảnh. Nút `📋` hoặc `Ctrl/Cmd+C` sẽ đưa toàn bộ ảnh đã crop vào clipboard và hiện thông báo xác nhận trong 1,6 giây. `Ctrl/Cmd` kết hợp `+`, `=` hoặc `-` điều khiển zoom trong toàn cửa sổ, kể cả khi focus nằm ở sidebar. Zoom có giới hạn để tránh tỷ lệ quá lớn hoặc quá nhỏ.

Toolbar được neo vào góc trên-phải của chính Image Viewer nên không di chuyển theo ảnh hoặc thanh cuộn. Câu thuộc `Selections_Multiple_choose` có nhãn cảnh báo ở góc trên-trái.

## Cài đặt và vùng cắt đáp án

Trong “Cài đặt” có thể chọn Sáng, Tối hoặc Giống hệ thống; giao diện đổi ngay khi chọn để xem trước và chỉ được lưu cho lần mở sau khi bấm “Lưu cài đặt”. “Giống hệ thống” ưu tiên `darkdetect` để dò Light/Dark của hệ điều hành rồi áp dụng đúng QSS tương ứng; nếu môi trường Python cũ chưa cài dependency này, ứng dụng dùng cơ chế dò gốc của macOS/Windows/Linux thay vì dừng khởi động. Có thể đổi thư mục DATA và hiệu chỉnh vùng crop theo phần trăm; tổng `X + rộng` và `Y + cao` không được vượt 100%.

Vùng đáp án nằm sát cạnh dưới nên viewer cắt toàn bộ dải ảnh bắt đầu từ tọa độ `Crop Y`. Không còn lớp phủ và thao tác “Hiện đáp án” không khôi phục phần ảnh đã cắt.

## Kiểm thử

```bash
pytest
```

Test bao phủ scanner Unicode, answer key, lưu Flashcard, queue Cramming, tạo/chấm đề và lịch sử SQLite.

Smoke test không cần màn hình trên Linux/macOS:

```bash
QT_QPA_PLATFORM=offscreen python main.py
```

## Đóng gói

PyInstaller phải chạy trên đúng hệ điều hành cần phát hành:

```bash
pyinstaller --clean study_app.spec
```

Main App không đóng gói OpenCV/Tesseract vì OCR là công cụ tiền xử lý độc lập. Sao chép thư mục `DATA` cạnh ứng dụng hoặc chọn vị trí DATA trong Cài đặt.

## Xử lý lỗi thường gặp

- **Home không có môn học:** kiểm tra cấu trúc `DATA/<Tên môn>/<Loại câu>/ảnh` hoặc chọn lại đường dẫn DATA.
- **Mock Exam báo 0 câu:** chạy OCR, sửa các ô trống trong `answers.csv`, rồi bấm Làm mới.
- **Cần debug answers.csv:** terminal và `study_app.log` ghi đường dẫn CSV tuyệt đối, tổng dòng, số dòng map thành công và nguyên nhân từng dòng bị từ chối. Nếu file chưa tồn tại, ứng dụng hiển thị chính xác đường dẫn cần tạo.
- **Không tìm thấy Tesseract:** thêm binary vào PATH và mở terminal mới.
- **Ảnh không được nhận diện:** chỉ dùng PNG/JPG/JPEG hợp lệ; ảnh lỗi được bỏ qua.
- **Đáp án bị lộ hoặc ảnh bị cắt quá nhiều:** chỉnh X/Y/rộng/cao của crop trong Cài đặt; mặc định `Y=90%`.

## Kiến trúc mã nguồn

```text
app/domain          Dataclass và quy tắc chuẩn hóa
app/repositories    SQLite và answers.csv
app/services        Scanner, Flashcard, Cramming, Mock Exam
app/controllers     Điều phối màn hình và filesystem watcher
app/ui              PyQt5 views, theme và image viewer
tools               Công cụ OCR tiền xử lý
tests               Unit/integration tests
```

View không truy cập trực tiếp filesystem hoặc SQLite; mọi dữ liệu đi qua controller/service/repository.
