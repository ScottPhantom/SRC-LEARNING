from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QApplication, QStyle, QStyleOptionFrame

from app.ui.data_import_dialog import DataImportDialog
from app.ui.themes import ThemeManager


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("font_pixels", [None, 24])
def test_import_code_text_has_vertical_room_after_error(
    theme: str, font_pixels: int | None
) -> None:
    app = QApplication.instance() or QApplication([])
    manager = ThemeManager(app)
    manager.apply(theme)
    dialog = DataImportDialog()
    code = "1uw-ts9-mYyjgkvoqlZmhIynQzbUwriJz"
    try:
        field = dialog.code_input
        field.setText(code)
        if font_pixels is not None:
            field.setStyleSheet(f"font-size: {font_pixels}px;")
        dialog.set_running(True)
        dialog.show_error("Mã này chưa nằm trong danh sách môn học được phê duyệt.")
        dialog.show()
        app.processEvents()

        option = QStyleOptionFrame()
        option.initFrom(field)
        option.lineWidth = field.style().pixelMetric(
            QStyle.PM_DefaultFrameWidth, option, field
        )
        text_area = field.style().subElementRect(
            QStyle.SE_LineEditContents, option, field
        )

        assert field.text() == code
        assert field.isVisible()
        assert text_area.height() >= field.fontMetrics().height() + 8
    finally:
        dialog.close()
        dialog.deleteLater()
        manager.apply("light")


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("terminal", ["error", "complete"])
@pytest.mark.parametrize("font_pixels", [None, 24])
def test_import_status_does_not_overlap_code_or_progress(
    theme: str, terminal: str, font_pixels: int | None
) -> None:
    app = QApplication.instance() or QApplication([])
    manager = ThemeManager(app)
    manager.apply(theme)
    dialog = DataImportDialog()
    try:
        if font_pixels is not None:
            dialog.status_label.setStyleSheet(f"font-size: {font_pixels}px;")
        dialog.code_input.setText("1KBpqVnqdmv7TymK4wNXjdUu283seNlAE")
        dialog.show()
        app.processEvents()
        dialog.set_running(True)
        dialog.update_progress("install", 99, "Đang hoàn tất phiên bản đáp án…")
        app.processEvents()
        message = (
            "Đã cài CPV301 với 284 câu hỏi; answer bank v4. Bản cũ: "
            "D:\\a\\_temp\\src-learning-release-qa\\profile\\.src-learning-recovery\\"
            "CPV301-e7d3bb0a115244cba6743f7866183f1f"
        )
        if terminal == "error":
            dialog.show_error("Không hoàn tất cập nhật. " + message)
        else:
            dialog.show_complete(message)
        app.processEvents()
        label = dialog.status_label
        code_bottom = dialog.code_input.mapTo(dialog, QPoint(0, dialog.code_input.height())).y()
        label_top = label.mapTo(dialog, QPoint(0, 0)).y()
        label_bottom = label.mapTo(dialog, QPoint(0, label.height())).y()
        progress_top = dialog.progress_bar.mapTo(dialog, QPoint(0, 0)).y()
        assert label_top >= code_bottom + 8
        assert label.height() >= label.heightForWidth(label.width())
        assert progress_top >= label_bottom + 8
    finally:
        dialog.close()
        dialog.deleteLater()
        manager.apply("light")
