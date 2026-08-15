# SRC LEARNING

Ứng dụng desktop ngoại tuyến bằng Python và PyQt5 để học từ ngân hàng câu hỏi dạng ảnh.

SRC LEARNING cung cấp ba chế độ:

- **Flash Cards:** xem câu hỏi, hiện đáp án và đánh dấu Đã thuộc/Chưa thuộc.
- **Học cấp tốc:** luyện theo vòng; câu trả lời sai quay lại cuối hàng đợi.
- **Mock Exam:** tạo đề từ nhiều nhóm câu, giới hạn thời gian, chấm điểm và lưu lịch sử.

Giao diện và thông báo sử dụng tiếng Việt. Tiến trình học, kết quả thi và thiết lập được lưu cục bộ trong `study_progress.sqlite3`.

## Yêu cầu hệ thống

- Python 3.11 hoặc 3.12.
- Windows 10/11, macOS hoặc Linux có giao diện desktop.
- Tesseract chỉ cần cho công cụ tạo đáp án bằng OCR; ứng dụng chính không chạy OCR.

## Cấu trúc project

```text
SRC-LEARNING/
├── app/
│   ├── controllers/   điều phối giao diện và tác vụ
│   ├── domain/        model và quy tắc nghiệp vụ
│   ├── repositories/  SQLite và answer key
│   ├── services/      scanner và các chế độ học
│   └── ui/            màn hình, component và theme PyQt5
├── DATA/              ngân hàng môn học đã cài
├── docs/              đặc tả kỹ thuật của ứng dụng
├── tests/             unit/integration test
├── tools/             công cụ bảo trì dữ liệu hiện có
├── main.py            entrypoint
├── requirements.txt
└── study_app.spec     cấu hình PyInstaller
```

View không truy cập trực tiếp filesystem hoặc SQLite; dữ liệu đi qua controller, service và repository.

## Cấu trúc dữ liệu môn học

```text
DATA/
└── ITE303c/
    ├── Fill_blanks/
    ├── Selections_1_choose/
    ├── Selections_Multiple_choose/
    ├── True_False/
    └── answers.csv
```

Ứng dụng tự quét các thư mục cấp một trong `DATA`. Định dạng ảnh được hỗ trợ là `.png`, `.jpg` và `.jpeg`.

`answers.csv` dùng UTF-8 và có hai cột:

```csv
image_name,correct_answer
Selections_1_choose/Câu 119.png,B
Selections_Multiple_choose/Câu 100.png,BCD
```

Quy tắc đáp án:

- `Selections_1_choose`, `Fill_blanks`: một ký tự A–D.
- `True_False`: A hoặc B.
- `Selections_Multiple_choose`: 2–4 ký tự khác nhau A–D, ví dụ `ACD`.

Câu chưa có đáp án hợp lệ vẫn có thể dùng trong Flash Cards. Học cấp tốc và Mock Exam chỉ sử dụng câu có đáp án hợp lệ.

## Cài đặt từ source

Chạy các lệnh sau từ thư mục `SRC-LEARNING`.

### Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### macOS

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install python3.11-venv libgl1
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Project có `.envrc` để tự động kích hoạt `.venv` bằng `direnv` trên các terminal POSIX:

```bash
direnv allow
```

## Chạy ứng dụng

```bash
python main.py
```

Ứng dụng mặc định đọc dữ liệu tại `DATA/` và lưu database tại `study_progress.sqlite3`. Người dùng có thể đổi thư mục dữ liệu trong phần Cài đặt.

## Chức năng chính

### Flash Cards

- Nhấn `Space` để hiện hoặc ẩn đáp án.
- Đánh dấu câu là Đã thuộc hoặc Chưa thuộc.
- Có thể đóng ứng dụng và tiếp tục phiên học sau.
- Quick Review hỗ trợ duyệt lại câu chưa thuộc và câu có tỷ lệ sai cao.

### Học cấp tốc

- Chia câu hỏi thành các vòng luyện tập.
- Câu đúng rời hàng đợi; câu sai quay lại cuối hàng đợi.
- Lưu trạng thái sau mỗi lần chấm.
- Câu chọn nhiều được chấm theo exact match.

### Mock Exam

- Chọn nhóm câu hỏi, số lượng câu và thời gian làm bài.
- Hỗ trợ chấm ngay hoặc chấm sau khi nộp.
- Lưu kết quả, chi tiết đáp án và lịch sử bài thi.
- Câu chọn nhiều được chấm điểm từng phần theo số lựa chọn đúng và sai.

## Điều khiển ảnh và phím tắt

- `Ctrl/Cmd` + `+` hoặc `=`: phóng to.
- `Ctrl/Cmd` + `-`: thu nhỏ.
- `Ctrl/Cmd` + `C`: sao chép ảnh đã crop.
- `1`–`8` hoặc `A`–`H`: chọn đáp án tương ứng.
- `Enter`: kiểm tra câu hoặc nộp bài tùy chế độ.
- `←` / `→`: điều hướng câu hỏi.

Vùng crop đáp án có thể được điều chỉnh trong Cài đặt. Tổng `X + rộng` và `Y + cao` không được vượt quá 100%.

## Công cụ bảo trì dữ liệu hiện có

Tạo hoặc cập nhật `answers.csv` bằng OCR:

```bash
python tools/build_answers.py --data-dir DATA
```

Kiểm tra thay đổi ngân hàng mà không ghi dữ liệu:

```bash
python tools/check_question_bank_updates.py --data-dir DATA --subject ITE303c
```

Áp dụng một version mới:

```bash
python tools/check_question_bank_updates.py --data-dir DATA --subject ITE303c --apply
```

Các công cụ OCR yêu cầu Tesseract được cài riêng và có trong `PATH`.

## Kiểm thử

```bash
python -m pytest
```

Smoke test không cần màn hình trên Linux/macOS:

```bash
QT_QPA_PLATFORM=offscreen python main.py
```

## Đóng gói

PyInstaller phải chạy trên đúng hệ điều hành cần phát hành:

```bash
pyinstaller --clean study_app.spec
```

Ứng dụng đóng gói không bao gồm OpenCV hoặc Tesseract. Sao chép `DATA` cạnh ứng dụng hoặc chọn lại thư mục dữ liệu trong Cài đặt.

## Xử lý lỗi thường gặp

- **Home không có môn học:** kiểm tra `DATA/<Tên môn>/<Loại câu>/ảnh` và đường dẫn đã lưu trong Cài đặt.
- **Mock Exam báo 0 câu:** kiểm tra các đáp án trống hoặc không hợp lệ trong `answers.csv`.
- **Ảnh không được nhận diện:** xác nhận file là PNG/JPG/JPEG hợp lệ.
- **Đáp án bị lộ hoặc ảnh bị cắt quá nhiều:** điều chỉnh vùng crop trong Cài đặt.
- **`pip`, `pytest` hoặc `pyinstaller` báo bad interpreter sau khi di chuyển project:** xóa và tạo lại `.venv` tại vị trí hiện tại.
