from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
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
