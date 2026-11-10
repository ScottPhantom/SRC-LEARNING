# Subject Statistics — bản thử

Chạy từ thư mục gốc `SRC-LEARNING`:

```bash
python main.py -t -ss
```

Lệnh này quét **chỉ** các thư mục `*_t` trong `.src-learning-test/data/`,
đọc/đồng bộ tiến độ trong `.src-learning-test/test_progress.sqlite3`, rồi ghi
`subject_statistics.json` tại đây và PNG/CSV EDA Mock Exam trong
`<môn>_t/Date-of-Statistical_<ngày>/`. Không dùng `DATA/` hoặc database của
app thường. Nếu chưa có môn thử, lệnh báo lỗi và không tạo báo cáo rỗng.

Báo cáo JSON là bản chụp tại thời điểm chạy lệnh, không tự cập nhật khi bạn
học tiếp. Mỗi môn có `question_count`, `card_stats` (`new`, `learning`, `known`),
thông tin `answer_key` và `categories` cho bốn loại câu. Mỗi loại ghi:

- `not_learned`: toàn bộ câu mới/chưa thuộc theo thứ tự file; gồm đường dẫn
  ảnh tương đối, đáp án đúng và trạng thái thẻ.
- `top_errors`: tối đa 20 câu có lỗi sai theo đúng thứ tự xếp hạng của giao
  diện; gồm số lần sai, tổng lần làm và tỷ lệ sai.

PNG/CSV bên cạnh JSON ghi tần suất mỗi câu xuất hiện trong Mock Exam, số lần
làm và số lần sai. Đây là thống kê cho người phát triển, khác với hai tab
thống kê trên giao diện môn học. Với `AIL303M_t`, EDA chỉ tính 154 ảnh trong
`exam_first_154.json`, đúng tập câu của Mock Exam; JSON thống kê học vẫn bao
gồm đủ 500 câu của môn thử hiện tại.

Đây là dữ liệu tiến độ và đáp án của máy cá nhân. JSON và các thư mục PNG/CSV
được `.gitignore` loại khỏi commit; chỉ tài liệu hướng dẫn này được theo dõi
trong Git.
