# SRC-LEARNING UI V3 — Codex, GAnti và Figma

## Nguồn thiết kế

- Figma Design: https://www.figma.com/design/8pN0vZFtubvtTE1XCgMLdi
- Tên file: `SRC-LEARNING UI V3`
- Stack triển khai: Python + PyQt5.
- Figma là nguồn sự thật cho UI/UX; code Python là nguồn sự thật cho hành vi
  ứng dụng.

Các page đã chuẩn bị trong file Figma:

1. `00 — Cover & Brief`
2. `01 — Foundations`
3. `02 — Components`
4. `03 — Screens Light & Dark`
5. `04 — Prototype & Handoff`

## Phân vai

### Codex

- Dùng Graft để quản lý phạm vi và blast radius của thay đổi.
- Kiểm tra architecture, business logic, accessibility và test.
- Tạo/chỉnh sửa variables, components, screens và prototype trên Figma.
- Viết prompt và acceptance criteria cho GAnti.
- Review diff của GAnti và quản lý Git khi được người dùng cho phép.

### GAnti

- Đọc frame/node đã duyệt từ Figma qua local desktop MCP.
- Dịch thiết kế sang Python/PyQt5, QSS, `QPalette` và
  `QPropertyAnimation` khi cần.
- Chỉ làm trong phạm vi UI được Development Gate cho phép.
- Được dùng mọi Figma write tool mà official MCP server thực sự cung cấp cho
  Antigravity, trong đúng file/frame do người dùng chỉ định.
- Nếu không có `use_figma`, chuyển phần ghi canvas cho Codex; không dùng browser
  automation hoặc wrapper Node để vượt giới hạn client.
- Không chạy Git và không đưa Node/web stack vào SRC-LEARNING.

### Figma

- Chứa foundations, design tokens, components, light/dark screens, states và
  prototype đã duyệt.
- Mỗi frame bàn giao phải có tên ổn định để Codex và GAnti cùng tham chiếu.

## Phạm vi màn hình V3 phát hiện từ Graft

| Thứ tự | Màn hình/lớp hiện tại | Mục tiêu thiết kế |
| --- | --- | --- |
| 1 | `AppHeader`, `BrandButton` | Điều hướng toàn cục, home, theme và action states. |
| 2 | `HomeScreen` | Danh sách môn học, loading/empty và responsive grid. |
| 3 | `ModeScreen` | Chọn chế độ, tiến độ, bảng câu yếu và quick review. |
| 4 | `FlashcardScreen` | Câu hỏi, reveal, rating, history và navigation. |
| 5 | `CrammingScreen` | Chọn đáp án, grading, vòng ôn tập và mastered states. |
| 6 | `ExamConfigScreen` | Chọn category, số câu, cảnh báo và bắt đầu thi. |
| 7 | `ExamScreen` | Câu hỏi, timer, sidebar, keyboard và submit flow. |
| 8 | `ResultScreen` | Điểm, thống kê và xem lại từng câu. |
| 9 | `SettingsScreen` | Data path, theme, crop preview và validation. |
| 10 | `HistoryScreen` | Danh sách lần thi, selection và xóa lịch sử. |

Component foundations cần dựng trước screens:

- Color variables cho Light/Dark.
- Typography và spacing scale.
- Button variants và interaction states.
- Subject card, status capsule và progress indicator.
- Answer options, assessment sidebar và image viewer.
- Dialog, empty/loading/error states và keyboard-focus treatment.

## Quy trình cho mỗi batch UI

```text
Codex dùng Graft xác định screen + dependency
  → Codex tạo/chỉnh frame trên Figma
  → Codex cung cấp frame URL/node + acceptance criteria
  → GAnti đọc frame bằng Figma desktop MCP
  → GAnti chạy Graft Development Gate
  → GAnti triển khai Python/PyQt5 và test hẹp
  → Codex review visual/architecture/test
  → Người dùng duyệt trước bước Git tiếp theo
```

Không bàn giao cả mười màn hình trong một batch. Bắt đầu bằng foundations và
components, sau đó làm từng màn hình hoặc một user flow nhỏ.

## Prompt handoff chuẩn cho GAnti

```text
Project: SRC-LEARNING
Task: Implement UI V3 for <screen/component>
Figma file: https://www.figma.com/design/8pN0vZFtubvtTE1XCgMLdi
Figma frame/node: <paste exact selection link>

Follow .agents/rules/src-learning-ui-only.md and run the GAnti Development Gate.
Use Graft before editing. Implement with Python and PyQt5 only.
Do not introduce Node.js or web frontend tooling. Do not run Git.

Allowed files: <exact app/ui files and UI tests supplied by Codex>
Required states: <light/dark/default/hover/focus/pressed/disabled/loading/error>
Acceptance criteria:
1. <visual criterion>
2. <interaction criterion>
3. <accessibility/keyboard criterion>
4. <test criterion>

Return the Figma node used, files changed, states covered, tests run,
remaining differences, and Graft token savings.
```

## Kết nối GAnti với Figma Desktop

Workspace đã có `.agents/mcp_config.json` trỏ tới:

`http://127.0.0.1:3845/mcp`

Trước mỗi phiên thiết kế-to-code:

1. Mở file `SRC-LEARNING UI V3` bằng Figma Desktop.
2. Chuyển sang Dev Mode và bật desktop MCP server.
3. Mở đúng workspace SRC-LEARNING trong Antigravity.
4. Refresh MCP Servers và kiểm tra `figma-desktop` đang connected.
5. Chọn frame trong Figma hoặc cung cấp link node chính xác cho GAnti.

Workspace không còn chặn bất kỳ Figma MCP tool nào. Tuy nhiên, tại thời điểm
chuẩn bị tài liệu này, official Figma MCP chỉ cung cấp Antigravity quyền đọc.
Khi `use_figma` không xuất hiện trong tool list, thao tác ghi canvas được chuyển
cho Codex. Nếu Figma mở quyền write cho Antigravity trong tương lai, GAnti có
thể dùng ngay mà không cần sửa lại `.agents/mcp_config.json`.
