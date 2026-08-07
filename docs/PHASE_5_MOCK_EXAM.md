# Phase 5 — Mock Exam, timer và chấm điểm

## Prompt/specification cập nhật

Triển khai Mock Exam với thang điểm tổng là **10 điểm**. Với đề có `N` câu, giá trị tối đa của mỗi câu là:

```text
question_value = 10 / N
```

### Single Choice, True/False và Fill Blanks

- Đáp án người dùng trùng hoàn toàn với đáp án đúng: nhận `question_value`.
- Sai hoặc không trả lời: nhận `0`.

### Multiple Choice — partial credit có phạt lựa chọn sai

```text
correct_selected = số đáp án đúng mà người dùng đã chọn
wrong_selected   = số lựa chọn của người dùng không thuộc tập đáp án đúng
correct_total    = tổng số đáp án đúng của câu

question_score = max(
    0,
    (correct_selected - wrong_selected) * (question_value / correct_total)
)
```

Điểm câu không được vượt quá `question_value`. Thứ tự đáp án không ảnh hưởng kết quả, ví dụ `ACD` và `DCA` tương đương.

### Làm tròn và lưu trữ

- Tính điểm từng câu và tổng điểm bằng giá trị float chưa làm tròn để tránh sai số cộng dồn.
- Điểm tổng lưu vào SQLite dưới dạng `REAL`, làm tròn hai chữ số thập phân, trong cột `exam_attempts.score`.
- Điểm từng câu lưu vào `exam_answers.awarded_score`, làm tròn hai chữ số thập phân.
- Duy trì `score_percent = score * 10` để tương thích giao diện/lịch sử cũ.
- `is_correct` chỉ mang nghĩa đúng hoàn toàn; câu được partial credit vẫn có thể có `is_correct = 0` nhưng `awarded_score > 0`.

### Hiển thị kết quả

- Tổng kết: `Điểm X.XX/10 (YY.YY%)`.
- Mỗi câu hiển thị một trong ba trạng thái: Đúng, Đúng một phần, Sai.
- Hiển thị điểm nhận được, đáp án người dùng và đáp án đúng.
- Chế độ feedback ngay phải hiển thị partial credit ngay sau khi xác nhận câu.

### Answer key

- Đọc tại `DATA/<Tên môn học>/answers.csv`.
- Chuẩn hóa `\\` thành `/` và Unicode về NFC trước khi đối chiếu.
- Canonical key là đường dẫn tương đối gồm category, ví dụ `Selections_1_choose/Câu 119.png`.
- Cho phép tương thích có kiểm soát với đường dẫn có tiền tố môn học hoặc basename duy nhất.
- Log đường dẫn CSV tuyệt đối, tổng số dòng, số dòng map thành công, số dòng bị reject và lý do reject.
- Nếu không tồn tại CSV, giao diện phải hiển thị chính xác đường dẫn file đang thiếu.

### Adaptive learning và lấy mẫu có trọng số

- SQLite lưu `total_attempts` và `wrong_count` theo `question_id` trong bảng `question_error_stats`; `error_rate = wrong_count / total_attempts` được tính khi đọc.
- Cramming ghi một lượt ngay khi người dùng nhấn `Enter`. Mock Exam chỉ ghi các câu đã trả lời khi bài được nộp; câu bỏ trống không làm tăng số lượt.
- Trọng số tạo đề kết hợp trạng thái Flashcard, tỷ lệ sai, tổng số lần sai và số lần đúng. Câu đã thuộc hoặc đã trả lời đúng nhiều lần được giảm trọng số, còn câu sai thường xuyên được ưu tiên rõ rệt.
- Lấy mẫu có trọng số được thực hiện không hoàn lại, vì vậy một câu không thể xuất hiện hai lần trong cùng đề.

## Tiêu chí nghiệm thu

- Đề có 30 câu đúng toàn bộ phải đạt chính xác `10.00`, không phải `9.90` do làm tròn từng câu.
- Multiple choice đúng một phần nhận điểm theo công thức và lựa chọn sai làm giảm điểm.
- Điểm mỗi câu không âm và không vượt giá trị tối đa của câu.
- Điểm tổng và điểm từng câu được đọc lại đúng sau khi khởi động lại ứng dụng.
- Database schema cũ được migrate mà không mất lịch sử thi.
