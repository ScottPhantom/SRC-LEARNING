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

- `Selections_1_choose`, `Fill_blanks`: một ký tự trong các lựa chọn của câu.
- `True_False`: A = True, B = False; trên giao diện nhấn phím A/B tương ứng.
- `Selections_Multiple_choose`: từ 2 ký tự khác nhau trở lên trong các lựa chọn
  của câu, ví dụ `ACD` hoặc `CE`.

Ngân hàng cũ không khai báo số lựa chọn dùng mặc định A–D (Đúng/Sai dùng A–B).
Câu có lựa chọn E trở lên phải có `question_metadata.csv` trong gói môn, với
hai cột `image_name,option_letters`; ví dụ
`Selections_1_choose/Q107.png,ABCDE`. Khi dùng cột `option_letters`, khai báo
đủ mọi ảnh trong môn bằng dãy liên tục từ A đến chữ cuối (tối đa Z). Gói tải
từ Drive bị từ chối nếu metadata thiếu, trùng hoặc có dãy lựa chọn không hợp lệ.

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

Khi chạy từ source, ứng dụng mặc định đọc dữ liệu tại `DATA/` và lưu database
tại `study_progress.sqlite3`. Bản đóng gói lưu cả database và dữ liệu tải về
trong `~/.luyen_thi_hinh_anh/`, vì thư mục cài đặt có thể không cho phép ghi.
Người dùng vẫn có thể đổi thư mục dữ liệu trong phần Cài đặt.
Khi kiểm thử một bản build, có thể đặt biến `SRC_LEARNING_STATE_DIR` cho tiến
trình app, trỏ tới một thư mục trống riêng. Database, log, bộ nhớ đệm danh mục
và DATA mặc định của lần chạy đó nằm trong thư mục riêng; khi không đặt biến,
ứng dụng giữ nguyên vị trí dữ liệu mặc định.

### Chạy các môn thử với `-t`

Từ thư mục `SRC-LEARNING`, chạy:

```bash
python main.py -t
```

App mở thẳng giao diện Thư viện như khi chạy không có cờ; không hiện launcher,
nhãn hay tiêu đề "test". Khác biệt chỉ ở nguồn dữ liệu và tiến độ: chế độ này
đọc các thư mục môn có tên kết thúc bằng `_t` trong
`.src-learning-test/data/` và lưu DB tại
`.src-learning-test/test_progress.sqlite3` (log tại
`.src-learning-test/study_app.log`). `DATA/` và `study_progress.sqlite3` của
app thường không bị sử dụng. Toàn bộ `.src-learning-test/` là dữ liệu local
và bị `.gitignore` loại khỏi Git.

Để thêm một môn thử, chép **nguyên thư mục** `TênMôn_t/` vào
`.src-learning-test/data/`, hoặc nhấn nút `+` rồi chọn thư mục nguồn: app sẽ
kiểm tra và tạo một bản sao vật lý. Môn mới xuất hiện trên Home sau khi nhấn
**Làm mới** hoặc mở lại app. Môn thử của các mã đã biết (ví dụ `AIL303M_t`)
được xếp vào cùng học kỳ với mã gốc; môn chưa có học kỳ có thể khai báo
`academic_term.json` trong thư mục môn. Trong Cài đặt, đường dẫn DATA được khóa
để không vô tình chuyển sang dữ liệu thường; Quản lý môn học chỉ tác động lên bản thử.
Nếu muốn chỉnh ảnh, `answers.csv` hay metadata, hãy chỉnh **bản sao** trong
`.src-learning-test/data/TênMôn_t/` khi app đã đóng, rồi mở lại. Sửa thư mục
nguồn ban đầu sẽ không tự đồng bộ vào bản sao.

Bản sao hiện có là `AIL303M_t` với 500 câu học. Riêng môn này, Mock Exam chỉ
dùng 154 ảnh liệt kê trong `exam_first_154.json`; môn thử khác không có giới
hạn đặc biệt. Chế độ này mới được kiểm thử từ source trên macOS; dữ liệu thử
không được đưa vào bản phát hành Windows.

### Xuất thống kê môn học với `-ss`

```bash
python main.py -ss       # dữ liệu và tiến độ app thường
python main.py -t -ss    # chỉ các môn *_t và tiến độ thử
```

Lệnh `-ss` tạo báo cáo rồi thoát, không mở giao diện. Bản thường ghi JSON tại
`docs/subject_statistics.json` và PNG/CSV EDA Mock Exam cho từng môn tại
`docs/<môn>/Date-of-Statistical_<ngày>/`. Bản thử ghi JSON tại
`docs/Test_Ver/subject_statistics.json` và PNG/CSV tại
`docs/Test_Ver/<môn>_t/Date-of-Statistical_<ngày>/`. JSON chứa số thẻ mới/
chưa thuộc/đã thuộc, toàn bộ câu chưa học và tối đa 20 câu lỗi sai mỗi loại,
đúng như màn hình "Thống kê môn ... & Ôn tập nhanh". PNG/CSV là thống kê tần
suất câu hỏi Mock Exam dành cho người phát triển; không phải biểu đồ của hai
tab giao diện. Hai chế độ đọc database riêng; báo cáo chứa dữ liệu cá nhân và
được Git bỏ qua. Xem thêm `docs/Test_Ver/README.md` để hiểu bản thử.

### Thêm môn học từ Google Drive

1. Mở màn hình Home.
2. Nhấn nút `+` ở cụm chức năng bên phải Header.
3. Nhập Google Drive File ID hoặc link chia sẻ do quản trị viên cung cấp.
4. Chọn **Tải và cài đặt**.

Ứng dụng chỉ nhận các mã có trong manifest đã phê duyệt. Trước khi ghi vào
`DATA/<Tên môn>`, ứng dụng kiểm tra SHA-256, giải nén trong thư mục tạm, chặn
đường dẫn ZIP không an toàn, xác minh ảnh câu hỏi và `answers.csv`. Nếu môn đã
tồn tại, người dùng phải xác nhận thay thế. Dữ liệu cũ được giữ nguyên khi tải,
checksum, giải nén hoặc xác minh thất bại.

Khi thay một môn đã cài, app chuyển lịch sử `answer_versions` **trên máy người
dùng** sang gói đã xác minh, rồi so bộ câu hỏi/đáp án mới với manifest đang
hoạt động. Có thay đổi thì tạo `vN+1` và thông báo thay đổi; gói không đổi vẫn
giữ `vN`. Lịch sử version kèm trong ZIP không được ghi đè lịch sử trên máy.
App chỉ báo cài thành công sau khi cả dữ liệu lẫn answer version được lưu;
nếu bước phiên bản lỗi, app khôi phục môn cũ. Môn cũ có `answers.csv` nhưng
chưa có manifest version phải được làm mới/quét lại trước khi thay gói.

Danh mục trực tuyến do chủ dự án quản lý trong tab `GOOGLE_IDS` của Google Sheet
`SRC_APP`. Chỉ những dòng có cột `App manifest` bằng chính xác `Đã bật` mới
được app chấp nhận. Mỗi dòng được bật phải có Google file ID, SHA-256 ZIP,
kích thước byte và số câu đúng với gói thực tế. App tải bản CSV đã **xuất bản
riêng cho tab này**, không dùng URL chỉnh sửa Sheet hoặc thông tin đăng nhập
Google của người dùng. Khi không tải được CSV, app dùng bản danh mục hợp lệ đã
lưu gần nhất; nếu chưa có, app chỉ nhận các gói trong manifest đóng kèm. Bản
CSV hợp lệ mới thay thế bản lưu cũ, còn dữ liệu sai không được ghi đè. Việc tắt
một môn trên Sheet chỉ có hiệu lực ngay với thiết bị tải được danh mục mới;
thiết bị offline vẫn có thể dùng danh mục đã lưu đến lần kết nối tiếp theo.
Manifest đóng kèm là bản chụp tại thời điểm build; nếu ZIP trên Drive đã đổi,
ứng dụng cần đọc được CSV mới để lấy checksum và số câu đúng trước khi cài.

URL CSV công khai của riêng tab `GOOGLE_IDS` (`gid=105`) đã được tích hợp làm
nguồn mặc định cho các bản build mới. Nếu về sau phải đổi URL xuất bản, đặt tệp
`catalog_source_url.txt` **cạnh file `.exe`**, chứa duy nhất URL CSV mới để
không cần tạo lại `.exe`. Khi phát triển có thể dùng biến môi trường
`SRC_LEARNING_CATALOG_CSV_URL` thay cho tệp này. Nếu không tải được nguồn
trực tuyến, app dùng bản hợp lệ đã lưu từ trước hoặc manifest đi kèm.
URL chỉnh sửa Sheet hoặc URL export của Sheet riêng tư không dùng được; trên
máy người dùng URL phải tải được CSV mà không đăng nhập Google. Chỉ cần đặt
tệp URL cạnh `.exe` khi muốn ghi đè nguồn mặc định; việc thêm môn về sau chỉ
cần đăng ZIP đúng định dạng và cập nhật tab `GOOGLE_IDS`, không cần tạo lại
`.exe`. Cơ chế này chỉ có trong bản `.exe`
được build **sau thay đổi này**; artifact VER_01 đã phát hành trước đó vẫn cần
được thay một lần.

Không chọn xuất bản toàn bộ `SRC_APP`: các tab câu hỏi/đáp án không cần công
khai. Bất kỳ cột nào trong `GOOGLE_IDS`, kể cả ghi chú, đều có thể được xem qua
URL CSV đã xuất bản. Trước khi bật một dòng mới, cần duyệt dữ liệu, kiểm tra
ZIP không đăng nhập, SHA-256, số câu và khả năng đọc đáp án trong app. Sau khi
chỉnh Sheet, nội dung CSV công khai có thể mất vài phút mới cập nhật.

### Quản lý môn học

Trên màn Thư viện, các môn đã cài được nhóm theo **năm → học kỳ**. Các gói cũ
ITE303c thuộc SU26 (Summer 2026); AIL303m, CPV301, DAP391m và SSG105 thuộc
FA26 (Fall 2026). Năm mới hiện trước năm cũ; trong mỗi năm, thứ tự là
Fall → Summer → Spring. Từ 2027 trở đi, mỗi gói có thể khai báo tệp tùy chọn
`academic_term.json` ngay trong thư mục môn, ví dụ
`{"year": 2027, "semester": "SP"}`. Ba mã học kỳ hợp lệ là `SP` (Spring),
`SU` (Summer), `FA` (Fall). Gói có khai báo này sẽ vào đúng nhóm khi được cài;
môn chưa có học kỳ sẽ nằm trong “Chưa phân loại” và vẫn học được bình thường.
Nếu cùng mã môn được học ở năm khác, metadata trong gói mới sẽ thay phân loại
mặc định; app hiện chưa hỗ trợ cài đồng thời hai bản cùng mã môn.

Trên Home, chọn **Cài đặt → Quản lý môn học** để xem các môn trong thư mục DATA, số câu,
dung lượng, đường dẫn và trạng thái. Chọn một môn rồi chọn **Xóa môn đã chọn**;
ứng dụng yêu cầu nhập đúng tên môn. Thư mục môn được chuyển nguyên vẹn vào
`.src-learning-recovery` cạnh DATA để có thể khôi phục thủ công. Lịch sử học và
thi trong SQLite được giữ nguyên; các câu hỏi của môn đã xóa được đánh dấu
không hoạt động. Khi môn có phiên học hoặc bài thi đang diễn ra, ứng dụng yêu cầu
xử lý phiên trước khi xóa hoặc thay thế. Ứng dụng sẽ hỏi trước khi hủy
phiên học dở dang; tiến độ đánh giá câu hỏi và lịch sử đã lưu vẫn được giữ.
Không cần học hết câu hỏi hoặc đạt 100% mới được xóa môn. Với bài thi đang làm,
hãy nộp hoặc xác nhận thoát bài thi trong hộp thoại.

Nếu nhập mã tải cho môn đã cài, chọn **Hủy** hoặc **Xác minh và thay thế**.
Ứng dụng xác minh toàn bộ gói trước, chuyển thư mục cũ vào vùng khôi phục, rồi
đổi thư mục mới vào DATA. Nếu bước đổi thất bại, ứng dụng tự đưa bản cũ trở lại.
Không trộn từng tệp của hai phiên bản. Vùng khôi phục không được tự động dọn;
người dùng có thể kiểm tra và quản lý dung lượng ở đó.

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
- `1`–`9` hoặc `A`–`Z`: chọn đáp án tương ứng nếu câu có lựa chọn đó; từ lựa
  chọn thứ 10 trở đi dùng phím chữ.
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

Riêng macOS dùng spec dạng `.app` onedir để tương thích cơ chế bảo mật của hệ
điều hành:

```bash
pyinstaller --clean study_app_macos.spec
```

Không thể build một binary duy nhất chạy trên cả ba hệ điều hành. Workflow CI
build riêng artifact Windows x64, macOS Apple Silicon và Linux x86_64. Trên
macOS, spec đồng thời tạo `SRC Learning.app`.

Icon tĩnh của ứng dụng có nền kính trong suốt và được tạo lại bằng
`python tools/build_app_icon.py`. Lệnh này xuất PNG 32–1024 px, ICO cho Windows
và ICNS cho macOS (ICNS cần chạy trên macOS). Khi chạy `python main.py` hoặc
bản đóng gói, cửa sổ chào hiển thị hoạt ảnh SRC trong 2,5 giây. Icon ở Dock,
Taskbar và trình khởi chạy vẫn là ảnh tĩnh theo cơ chế của hệ điều hành.

Trên Linux, Qt đặt icon cho cửa sổ đang chạy. Để icon xuất hiện trong trình
khởi chạy sau khi cài bản PyInstaller, cài thêm
`packaging/linux/src-learning.desktop` vào `~/.local/share/applications/` và
`app/resources/brand/src-learning-256.png` vào
`~/.local/share/icons/hicolor/256x256/apps/src-learning.png`; file thực thi
`LuyenThiHinhAnh` cần nằm trong `PATH`.

Ứng dụng Core đóng gói không bao gồm OpenCV, Tesseract hoặc bộ `DATA`. Người
dùng cài từng môn bằng nút `+` trên Header. OCR được nạp theo nhu cầu trong môi
trường source và không chặn ứng dụng Core khởi động khi các thư viện OCR không
có mặt.

## Xử lý lỗi thường gặp

- **Home không có môn học:** kiểm tra `DATA/<Tên môn>/<Loại câu>/ảnh` và đường dẫn đã lưu trong Cài đặt.
- **Mock Exam báo 0 câu:** kiểm tra các đáp án trống hoặc không hợp lệ trong `answers.csv`.
- **Ảnh không được nhận diện:** xác nhận file là PNG/JPG/JPEG hợp lệ.
- **Đáp án bị lộ hoặc ảnh bị cắt quá nhiều:** điều chỉnh vùng crop trong Cài đặt.
- **`pip`, `pytest` hoặc `pyinstaller` báo bad interpreter sau khi di chuyển project:** xóa và tạo lại `.venv` tại vị trí hiện tại.
