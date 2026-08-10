from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

try:
    import darkdetect as _darkdetect
except ImportError:  # Dependency mới chưa được cài trong môi trường Python cũ.
    _darkdetect = None

LIGHT_STYLE = """
QWidget { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 14px; }
QMainWindow { background: #EEF3FA; color: #1d1d1f; }
QWidget#page, QWidget#homePage { background: transparent; color: #1d1d1f; }
QWidget#appShell { background: #EEF3FA; }
QFrame#globalHeader {
  background: rgba(255, 255, 255, 210);
  border: 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  border-top-left-radius: 0px;
  border-top-right-radius: 0px;
  border-bottom-left-radius: 18px;
  border-bottom-right-radius: 18px;
}
QFrame#globalHeader[homeMode="true"] {
  background: rgba(255, 255, 255, 115);
  border: 0;
  border-bottom: 1px solid rgba(95, 105, 125, 0.35);
  border-top-left-radius: 0px;
  border-top-right-radius: 0px;
  border-bottom-left-radius: 18px;
  border-bottom-right-radius: 18px;
}
QPushButton#globalHomeButton {
  background: transparent; color: #1d1d1f; border: 0; border-radius: 8px;
  padding: 0; font-size: 18px; font-weight: 700;
}
QPushButton#globalHomeButton:hover { background: rgba(0, 0, 0, 0.06); }
QLabel#globalAppTitle {
  color: #1d1d1f; font-size: 16px; font-weight: 700; letter-spacing: 0.2px;
}
QFrame#headerActionCapsule {
  background: rgba(240, 243, 248, 180); border: 1px solid rgba(0, 0, 0, 0.08); border-radius: 18px;
}
QFrame#headerActionCapsule[homeMode="true"] {
  background: rgba(255, 255, 255, 88);
  border: 1px solid rgba(255, 255, 255, 180);
  border-radius: 18px;
}
QPushButton#headerActionButton {
  background: transparent; border: 0; border-radius: 14px;
  padding: 0px; margin: 0px;
}
QPushButton#headerActionButton:pressed { background: rgba(0, 0, 0, 0.12); }
QPushButton#headerActionButton:focus { border: 2px solid #0A84FF; outline: none; }

QStackedWidget#contentStack { background: transparent; border: none; }
QWidget#homePage { background: transparent; color: #1d1d1f; }
QScrollArea#homeScroll { background: transparent; border: 0; }
QWidget#homeViewport { background: transparent; border: 0; }
QWidget#homeCanvas { background: transparent; border: 0; }
QWidget#homeContentContainer, QWidget#homeCardsContainer { background: transparent; border: 0; }
QScrollArea#settingsScrollArea { background: transparent; border: 0; }
QScrollArea#settingsScrollArea > QWidget > QWidget { background: transparent; }
QWidget#settingsContent { background: transparent; }
QFrame#settingsPreviewPlaceholder {
  background: rgba(255, 255, 255, 105); border: 2px dashed rgba(120, 120, 128, 64);
  border-radius: 12px;
}
QLabel#settingsPreviewPlaceholderText {
  color: #6E6E73; background: transparent; border: 0; font-size: 14px; font-weight: 600;
}
QLabel#homeTitle { color: #1d1d1f; font-size: 34px; font-weight: 700; letter-spacing: -0.5px; }
QLabel#homeSubtitle { color: #6e6e73; font-size: 15px; font-weight: 400; }

QFrame#homeStatus {
  background: transparent; border: none;
}
QLabel#statusText { color: #3a3a3c; font-size: 13px; font-weight: 500; }
QPushButton#statusActionButton {
  background: transparent; color: #0A84FF; border: 0; font-size: 13px; font-weight: 600; text-decoration: underline;
}

QFrame#subjectCard {
  background: transparent; border: none;
}
QLabel#subjectName { color: #1d1d1f; font-size: 22px; font-weight: 700; }
QLabel#subjectCount { color: #6e6e73; font-size: 14px; font-weight: 500; }
QLabel#subjectAction { color: #0A84FF; font-size: 15px; font-weight: 600; }

QFrame#card { background: white; border: 1px solid #dce2ec; border-radius: 10px; }
QFrame#studyModeCard {
  background: #ffffff; border: 1px solid #dce2ec; border-radius: 18px;
}
QFrame#studyModeCard[hovered="true"] {
  background: #f8fbff; border: 2px solid #60a5fa;
}
QFrame#studyModeFocusOverlay {
  background: rgba(15, 23, 42, 190); border: 0; border-radius: 20px;
}
QLabel#studyModeIcon { background: transparent; font-size: 53px; }
QLabel#studyModeTitle {
  background: transparent; color: #172033; font-size: 18px; font-weight: 800;
}
QLabel#studyModeDescription {
  background: transparent; color: #64748b; font-size: 12px;
}
QLabel#subjectProgressSummary { color: #475569; font-weight: 650; }
QLabel#dashboardHeading { color: #172033; font-size: 19px; font-weight: 800; }
QTabWidget#weaknessDashboard::pane {
  background: #ffffff; border: 1px solid #dce2ec; border-radius: 10px;
}
QTabWidget#weaknessDashboard QTabBar::tab {
  background: #e8edf5; color: #475569; border: 0; min-width: 130px;
  padding: 8px 16px;
  margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px;
  font-weight: 700;
}
QTabWidget#weaknessDashboard QTabBar::tab:selected {
  background: #ffffff; color: #0A84FF;
}
QTableWidget#weakQuestionTable {
  background: #ffffff; alternate-background-color: #f7f9fc; color: #172033;
  border: 0; gridline-color: #e5e9f0; selection-background-color: #dbeafe;
  selection-color: #172033;
}
QTableWidget#weakQuestionTable QHeaderView::section {
  background: #eef2f7; color: #334155; border: 0;
  border-bottom: 1px solid #cbd5e1; padding: 7px; font-weight: 800;
}
QDialog#quickReviewDialog { background: #f5f7fb; color: #172033; }
QLabel#quickReviewTitle { font-size: 17px; font-weight: 800; }
QLabel#quickReviewCaption { color: #64748b; font-size: 12px; font-weight: 700; }
QLabel#quickReviewAnswer { color: #0A84FF; font-size: 38px; font-weight: 900; }
QPushButton { background: #2563eb; color: white; border: 0; border-radius: 7px;
              padding: 9px 16px; font-weight: 600; }
QPushButton:hover { background: #1d4ed8; }
QPushButton:disabled { background: #9ca3af; }
QPushButton[secondary="true"] { background: #e5e7eb; color: #172033; }
QPushButton[danger="true"] { background: #dc2626; }
QPushButton#deleteExamButton:disabled { background: #fecaca; color: #991b1b; }
QPushButton#settingsSaveButton {
  background: #0A84FF; color: #FFFFFF; border: 2px solid #0A84FF;
  border-radius: 10px; padding: 0 18px; font-weight: 600;
}
QPushButton#settingsSaveButton:hover {
  background: #0077ED; border-color: #0077ED;
}
QPushButton#settingsSaveButton:pressed {
  background: #0068D6; border-color: #0068D6;
}
QPushButton#settingsSaveButton:focus {
  background: #0A84FF; border-color: #75B9FF; outline: none;
}
QPushButton#settingsSaveButton:disabled {
  background: #B8C2D0; color: #3A4553; border-color: #B8C2D0;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QTreeWidget {
  background: white; color: #172033; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px;
}
QProgressBar#studyProgress, QProgressBar#segmentedProgress {
  border: none; background: #d1d5db; border-radius: 4px; padding: 0px;
}
QProgressBar#studyProgress::chunk { background: #0A84FF; border-radius: 4px; }
QProgressBar#segmentedProgress::chunk { background: #0A84FF; border-radius: 4px; }
QProgressBar#segmentedProgress[segmentState="completed"]::chunk {
  background: #30B85A;
}
QRadioButton#answerOption, QCheckBox#answerOption {
  border: 1px solid transparent; border-radius: 6px; padding: 7px 12px;
}
QRadioButton#answerOption[answerState="correct"],
QCheckBox#answerOption[answerState="correct"] {
  color: #16803A; border-color: #30B85A; background: #EAF8EE;
}
QRadioButton#answerOption[answerState="wrong"],
QCheckBox#answerOption[answerState="wrong"] {
  color: #C42B1C; border-color: #E5484D; background: #FDECEC;
}
QFrame#assessmentSidebar {
  background: #ffffff; border: 1px solid #dce2ec; border-radius: 12px;
}
QFrame#assessmentSidebar QGroupBox {
  border: 0; margin-top: 18px; font-weight: 700;
}
QFrame#assessmentSidebar QGroupBox::title { subcontrol-origin: margin; left: 0; }
QPushButton#answerOptionButton {
  background: #eef2f7; color: #172033; border: 1px solid #cbd5e1;
  border-radius: 11px; padding: 10px; font-size: 19px; font-weight: 800;
}
QPushButton#answerOptionButton:hover { background: #dbeafe; border-color: #60a5fa; }
QPushButton#answerOptionButton:checked {
  background: #0A84FF; color: white; border-color: #0A84FF;
}
QPushButton#answerOptionButton[answerState="correct"] {
  background: #EAF8EE; color: #16803A; border: 2px solid #30B85A;
}
QPushButton#answerOptionButton[answerState="wrong"] {
  background: #FDECEC; color: #C42B1C; border: 2px solid #E5484D;
}
QLabel#answerShortcutHint {
  color: #64748b; background: transparent; border: 0; font-size: 10px; font-weight: 700;
}
QPushButton#answerOptionButton:checked QLabel#answerShortcutHint { color: #ffffff; }
QLabel#navigationSummary { font-size: 14px; font-weight: 700; }
QScrollArea#questionGridScroll { background: transparent; border: 0; }
QScrollArea#questionGridScroll > QWidget > QWidget { background: transparent; }
QPushButton#questionNavButton {
  background: transparent; color: #475569; border: 1px solid #cbd5e1;
  border-radius: 9px; padding: 0; font-weight: 700;
}
QPushButton#questionNavButton[navState="answered"] { background: #dbe3ef; color: #172033; }
QPushButton#questionNavButton[navState="correct"] { background: #30B85A; color: white; border-color: #30B85A; }
QPushButton#questionNavButton[navState="wrong"] { background: #E5484D; color: white; border-color: #E5484D; }
QPushButton#questionNavButton[current="true"] { border: 3px solid #0A84FF; }
QFrame#sidebarSeparator { color: #dce2ec; }
QFrame#imageToolbar {
  background: rgba(255, 255, 255, 205); border: 1px solid rgba(148, 163, 184, 150);
  border-radius: 10px;
}
QPushButton#imageZoomButton {
  background: rgba(226, 232, 240, 220); color: #172033; border: 0;
  border-radius: 7px; padding: 0; font-size: 18px; font-weight: 800;
}
QPushButton#imageZoomButton:hover { background: #bfdbfe; color: #1d4ed8; }
QLabel#imageCopyToast {
  background: rgba(30, 41, 59, 225); color: #ffffff; border: 0;
  border-radius: 7px; padding: 7px 11px; font-size: 12px; font-weight: 700;
}
QTableWidget#resultTable {
  background: #ffffff; alternate-background-color: #f7f9fc;
  color: #172033; border: 1px solid #dce2ec; border-radius: 9px;
  gridline-color: #e5e9f0; selection-background-color: #dbeafe;
  selection-color: #172033;
}
QTableWidget#resultTable QHeaderView::section {
  background: #eef2f7; color: #334155; border: 0;
  border-bottom: 1px solid #cbd5e1; padding: 9px; font-weight: 800;
}
QTreeWidget#examHistoryTree {
  background: #ffffff; color: #1d1d1f; border: 1px solid #dce2ec;
  border-radius: 10px; alternate-background-color: #f7f9fc;
}
QTreeWidget#examHistoryTree::item { min-height: 34px; padding: 3px 6px; }
QTreeWidget#examHistoryTree::item:hover { background: #eef5ff; }
QTreeWidget#examHistoryTree::item:selected { background: #dbeafe; color: #172033; }
QTreeWidget#examHistoryTree QHeaderView::section {
  background: #eef2f7; color: #334155; border: 0;
  border-bottom: 1px solid #cbd5e1; padding: 8px; font-weight: 800;
}
QLabel#multipleChoiceNotice {
  background: rgba(255, 255, 255, 220); color: #9A6700;
  border: 1px solid rgba(217, 119, 6, 150); border-radius: 7px;
  padding: 6px 10px; font-size: 12px; font-style: italic; font-weight: 700;
}
QFrame#flashAnswerPanel {
  background: #ffffff; border: 1px solid #dce2ec; border-radius: 12px;
}
QLabel#flashAnswerTitle { color: #64748b; font-size: 15px; font-weight: 700; }
QLabel#flashAnswerValue { color: #0A84FF; font-size: 82px; font-weight: 900; }
QFrame#hotkeyHints { background: #eef2f7; border: 1px solid #dce2ec; border-radius: 9px; }
QLabel#hotkeyTitle { color: #64748b; font-size: 10px; font-weight: 800; }
QLabel#hotkeyText { color: #334155; font-size: 12px; }
QLabel#title { font-size: 25px; font-weight: 700; }
QLabel#subtitle { color: #64748b; }
"""

DARK_STYLE = """
QWidget { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 14px; }
QMainWindow { background: #0E0F12; color: #F5F5F7; }
QWidget#page, QWidget#homePage { background: transparent; color: #F5F5F7; }
QWidget#appShell { background: #0E0F12; }
QFrame#globalHeader {
  background: rgba(18, 20, 26, 210);
  border: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  border-top-left-radius: 0px;
  border-top-right-radius: 0px;
  border-bottom-left-radius: 18px;
  border-bottom-right-radius: 18px;
}
QFrame#globalHeader[homeMode="true"] {
  background: rgba(18, 20, 26, 210);
  border: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  border-top-left-radius: 0px;
  border-top-right-radius: 0px;
  border-bottom-left-radius: 18px;
  border-bottom-right-radius: 18px;
}
QPushButton#globalHomeButton {
  background: transparent; color: #f5f5f7; border: 0; border-radius: 8px;
  padding: 0; font-size: 18px; font-weight: 700;
}
QPushButton#globalHomeButton:hover { background: rgba(255, 255, 255, 0.08); }
QLabel#globalAppTitle {
  color: #f5f5f7; font-size: 16px; font-weight: 700; letter-spacing: 0.2px;
}
QFrame#headerActionCapsule {
  background: rgba(28, 30, 38, 190); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 18px;
}
QFrame#headerActionCapsule[homeMode="true"] {
  background: rgba(28, 30, 38, 190);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 18px;
}
QPushButton#headerActionButton {
  background: transparent; border: 0; border-radius: 14px;
  padding: 0px; margin: 0px;
}
QPushButton#headerActionButton:pressed { background: rgba(255, 255, 255, 0.18); }
QPushButton#headerActionButton:focus { border: 2px solid #0A84FF; outline: none; }

QStackedWidget#contentStack { background: transparent; border: none; }
QWidget#homePage { background: transparent; color: #F5F5F7; }
QScrollArea#homeScroll { background: transparent; border: 0; }
QWidget#homeViewport { background: transparent; border: 0; }
QWidget#homeCanvas { background: transparent; border: 0; }
QWidget#homeContentContainer, QWidget#homeCardsContainer { background: transparent; border: 0; }
QScrollArea#settingsScrollArea { background: transparent; border: 0; }
QScrollArea#settingsScrollArea > QWidget > QWidget { background: transparent; }
QWidget#settingsContent { background: transparent; }
QFrame#settingsPreviewPlaceholder {
  background: rgba(23, 26, 33, 190); border: 2px dashed rgba(255, 255, 255, 45);
  border-radius: 12px;
}
QLabel#settingsPreviewPlaceholderText {
  color: #A1A1A6; background: transparent; border: 0; font-size: 14px; font-weight: 600;
}
QLabel#homeTitle { color: #f5f5f7; font-size: 34px; font-weight: 700; letter-spacing: -0.5px; }
QLabel#homeSubtitle { color: #a1a1a6; font-size: 15px; font-weight: 400; }

QFrame#homeStatus {
  background: transparent; border: none;
}
QLabel#statusText { color: #e5e5ea; font-size: 13px; font-weight: 500; }
QPushButton#statusActionButton {
  background: transparent; color: #60A5FA; border: 0; font-size: 13px; font-weight: 600; text-decoration: underline;
}

QFrame#subjectCard {
  background: transparent; border: none;
}
QLabel#subjectName { color: #f5f5f7; font-size: 22px; font-weight: 700; }
QLabel#subjectCount { color: #a1a1a6; font-size: 14px; font-weight: 500; }
QLabel#subjectAction { color: #60A5FA; font-size: 15px; font-weight: 600; }

QFrame#card { background: #171A21; border: 1px solid #343844; border-radius: 10px; }
QFrame#studyModeCard {
  background: #171A21; border: 1px solid #343844; border-radius: 18px;
}
QFrame#studyModeCard[hovered="true"] {
  background: #1B202A; border: 2px solid #0A84FF;
}
QFrame#studyModeFocusOverlay {
  background: rgba(2, 6, 23, 205); border: 0; border-radius: 20px;
}
QLabel#studyModeIcon { background: transparent; font-size: 53px; }
QLabel#studyModeTitle {
  background: transparent; color: #f8fafc; font-size: 18px; font-weight: 800;
}
QLabel#studyModeDescription {
  background: transparent; color: #94a3b8; font-size: 12px;
}
QLabel#subjectProgressSummary { color: #cbd5e1; font-weight: 650; }
QLabel#dashboardHeading { color: #f8fafc; font-size: 19px; font-weight: 800; }
QTabWidget#weaknessDashboard::pane {
  background: #171A21; border: 1px solid #343844; border-radius: 10px;
}
QTabWidget#weaknessDashboard QTabBar::tab {
  background: #1B202A; color: #A1A1A6; border: 0; min-width: 130px;
  padding: 8px 16px;
  margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px;
  font-weight: 700;
}
QTabWidget#weaknessDashboard QTabBar::tab:selected {
  background: #171A21; color: #60a5fa;
}
QTableWidget#weakQuestionTable {
  background: #171A21; alternate-background-color: #141820; color: #F5F5F7;
  border: 0; gridline-color: #343844; selection-background-color: #1e3a5f;
  selection-color: #ffffff;
}
QTableWidget#weakQuestionTable QHeaderView::section {
  background: #273345; color: #cbd5e1; border: 0;
  border-bottom: 1px solid #4b5563; padding: 7px; font-weight: 800;
}
QDialog#quickReviewDialog { background: #171A21; color: #F5F5F7; }
QLabel#quickReviewTitle { color: #f8fafc; font-size: 17px; font-weight: 800; }
QLabel#quickReviewCaption { color: #94a3b8; font-size: 12px; font-weight: 700; }
QLabel#quickReviewAnswer { color: #0A84FF; font-size: 38px; font-weight: 900; }
QPushButton { background: #3b82f6; color: white; border: 0; border-radius: 7px;
              padding: 9px 16px; font-weight: 600; }
QPushButton:hover { background: #2563eb; }
QPushButton:disabled { background: #4b5563; color: #9ca3af; }
QPushButton[secondary="true"] { background: #374151; color: #e5e7eb; }
QPushButton[danger="true"] { background: #dc2626; }
QPushButton#deleteExamButton:disabled { background: #4b1f24; color: #9ca3af; }
QPushButton#settingsSaveButton {
  background: #0A84FF; color: #FFFFFF; border: 2px solid #0A84FF;
  border-radius: 10px; padding: 0 18px; font-weight: 600;
}
QPushButton#settingsSaveButton:hover {
  background: #409CFF; border-color: #409CFF;
}
QPushButton#settingsSaveButton:pressed {
  background: #0077ED; border-color: #0077ED;
}
QPushButton#settingsSaveButton:focus {
  background: #0A84FF; border-color: #8CC8FF; outline: none;
}
QPushButton#settingsSaveButton:disabled {
  background: #3A4350; color: #AEB7C4; border-color: #3A4350;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QTreeWidget {
  background: #171C24; color: #F5F5F7; border: 1px solid #3F4654; border-radius: 6px; padding: 6px;
}
QProgressBar#studyProgress, QProgressBar#segmentedProgress {
  border: none; background: #333333; border-radius: 4px; padding: 0px;
}
QProgressBar#studyProgress::chunk { background: #0A84FF; border-radius: 4px; }
QProgressBar#segmentedProgress::chunk { background: #0A84FF; border-radius: 4px; }
QProgressBar#segmentedProgress[segmentState="completed"]::chunk {
  background: #30D158;
}
QRadioButton#answerOption, QCheckBox#answerOption {
  border: 1px solid transparent; border-radius: 6px; padding: 7px 12px;
}
QRadioButton#answerOption[answerState="correct"],
QCheckBox#answerOption[answerState="correct"] {
  color: #30D158; border-color: #30D158; background: #153D25;
}
QRadioButton#answerOption[answerState="wrong"],
QCheckBox#answerOption[answerState="wrong"] {
  color: #FF453A; border-color: #FF453A; background: #481D1B;
}
QFrame#assessmentSidebar {
  background: #171A21; border: 1px solid #343844; border-radius: 12px;
}
QFrame#assessmentSidebar QGroupBox {
  border: 0; margin-top: 18px; font-weight: 700;
}
QFrame#assessmentSidebar QGroupBox::title { subcontrol-origin: margin; left: 0; }
QPushButton#answerOptionButton {
  background: #273345; color: #e5e7eb; border: 1px solid #4b5563;
  border-radius: 11px; padding: 10px; font-size: 19px; font-weight: 800;
}
QPushButton#answerOptionButton:hover { background: #334155; border-color: #60a5fa; }
QPushButton#answerOptionButton:checked {
  background: #0A84FF; color: white; border-color: #0A84FF;
}
QPushButton#answerOptionButton[answerState="correct"] {
  background: #153D25; color: #30D158; border: 2px solid #30D158;
}
QPushButton#answerOptionButton[answerState="wrong"] {
  background: #481D1B; color: #FF453A; border: 2px solid #FF453A;
}
QLabel#answerShortcutHint {
  color: #94a3b8; background: transparent; border: 0; font-size: 10px; font-weight: 700;
}
QPushButton#answerOptionButton:checked QLabel#answerShortcutHint { color: #ffffff; }
QLabel#navigationSummary { font-size: 14px; font-weight: 700; }
QScrollArea#questionGridScroll { background: transparent; border: 0; }
QScrollArea#questionGridScroll > QWidget > QWidget { background: transparent; }
QPushButton#questionNavButton {
  background: transparent; color: #cbd5e1; border: 1px solid #4b5563;
  border-radius: 9px; padding: 0; font-weight: 700;
}
QPushButton#questionNavButton[navState="answered"] { background: #374151; color: #f8fafc; }
QPushButton#questionNavButton[navState="correct"] { background: #1F7A3B; color: #ECFFF1; border-color: #30D158; }
QPushButton#questionNavButton[navState="wrong"] { background: #8B2C27; color: #FFF1F0; border-color: #FF453A; }
QPushButton#questionNavButton[current="true"] { border: 3px solid #0A84FF; }
QFrame#sidebarSeparator { color: #374151; }
QFrame#imageToolbar {
  background: rgba(17, 24, 39, 205); border: 1px solid rgba(100, 116, 139, 170);
  border-radius: 10px;
}
QPushButton#imageZoomButton {
  background: rgba(55, 65, 81, 220); color: #f8fafc; border: 0;
  border-radius: 7px; padding: 0; font-size: 18px; font-weight: 800;
}
QPushButton#imageZoomButton:hover { background: #475569; color: #60a5fa; }
QLabel#imageCopyToast {
  background: rgba(15, 23, 42, 235); color: #f8fafc;
  border: 1px solid rgba(48, 209, 88, 150); border-radius: 7px;
  padding: 7px 11px; font-size: 12px; font-weight: 700;
}
QTableWidget#resultTable {
  background: #111827; alternate-background-color: #182132;
  color: #f8fafc; border: 1px solid #374151; border-radius: 9px;
  gridline-color: #2f3a4c; selection-background-color: #1e3a5f;
  selection-color: #ffffff;
}
QTableWidget#resultTable QHeaderView::section {
  background: #1f2937; color: #cbd5e1; border: 0;
  border-bottom: 1px solid #4b5563; padding: 9px; font-weight: 800;
}
QTreeWidget#examHistoryTree {
  background: #151821; color: #f5f5f7; border: 1px solid #343844;
  border-radius: 10px; alternate-background-color: #1b1f2a;
}
QTreeWidget#examHistoryTree::item { min-height: 34px; padding: 3px 6px; }
QTreeWidget#examHistoryTree::item:hover { background: #252b38; }
QTreeWidget#examHistoryTree::item:selected { background: #1e3a5f; color: #ffffff; }
QTreeWidget#examHistoryTree QHeaderView::section {
  background: #20242f; color: #d1d5db; border: 0;
  border-bottom: 1px solid #3f4654; padding: 8px; font-weight: 800;
}
QLabel#multipleChoiceNotice {
  background: rgba(17, 24, 39, 220); color: #FFD60A;
  border: 1px solid rgba(255, 159, 10, 170); border-radius: 7px;
  padding: 6px 10px; font-size: 12px; font-style: italic; font-weight: 700;
}
QFrame#flashAnswerPanel {
  background: #171A21; border: 1px solid #343844; border-radius: 12px;
}
QLabel#flashAnswerTitle { color: #94a3b8; font-size: 15px; font-weight: 700; }
QLabel#flashAnswerValue { color: #0A84FF; font-size: 82px; font-weight: 900; }
QFrame#hotkeyHints { background: #1B202A; border: 1px solid #343844; border-radius: 9px; }
QLabel#hotkeyTitle { color: #64748b; font-size: 10px; font-weight: 800; }
QLabel#hotkeyText { color: #cbd5e1; font-size: 12px; }
QLabel#title { font-size: 25px; font-weight: 700; }
QLabel#subtitle { color: #94a3b8; }
"""


def _fallback_system_theme() -> str | None:
    """Dò theme bằng công cụ hệ điều hành khi darkdetect chưa khả dụng."""
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
            return "Dark" if result.returncode == 0 and "dark" in result.stdout.casefold() else "Light"
        if system == "Windows":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "Light" if int(value) else "Dark"
        if system == "Linux":
            result = subprocess.run(
                [
                    "gsettings",
                    "get",
                    "org.gnome.desktop.interface",
                    "color-scheme",
                ],
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
            if result.returncode == 0:
                return "Dark" if "dark" in result.stdout.casefold() else "Light"
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def detect_system_theme() -> str | None:
    if _darkdetect is not None:
        try:
            detected = _darkdetect.theme()
            if detected:
                return str(detected)
        except (OSError, RuntimeError):
            pass
    return _fallback_system_theme()


class ThemeManager:
    """Điều phối lựa chọn đã lưu và theme sáng/tối thực tế được áp dụng."""

    def __init__(
        self,
        application: QApplication,
        system_detector: Callable[[], str | None] | None = None,
    ):
        self.application = application
        self.system_detector = system_detector or detect_system_theme
        self.selected_theme = "system"
        self.applied_theme = "light"

    def resolve(self, selected_theme: str) -> str:
        normalized = selected_theme.casefold()
        if normalized in {"light", "dark"}:
            return normalized
        try:
            detected = (self.system_detector() or "").casefold()
        except (OSError, RuntimeError):
            detected = ""
        return "dark" if detected == "dark" else "light"

    def apply(self, selected_theme: str) -> str:
        self.selected_theme = (
            selected_theme if selected_theme in {"system", "light", "dark"} else "system"
        )
        resolved = self.resolve(self.selected_theme)
        self.applied_theme = resolved
        self.application.setProperty("selectedTheme", self.selected_theme)
        self.application.setProperty("appliedTheme", resolved)
        self.application.setStyle("Fusion")
        if resolved == "dark":
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor("#0e0f12"))
            palette.setColor(QPalette.WindowText, QColor("#f5f5f7"))
            palette.setColor(QPalette.Base, QColor("#1c1c1e"))
            palette.setColor(QPalette.AlternateBase, QColor("#141824"))
            palette.setColor(QPalette.Text, QColor("#f5f5f7"))
            palette.setColor(QPalette.Button, QColor("#282a36"))
            palette.setColor(QPalette.ButtonText, QColor("#f5f5f7"))
            palette.setColor(QPalette.Highlight, QColor("#0A84FF"))
            self.application.setPalette(palette)
            self.application.setStyleSheet(DARK_STYLE)
        else:
            self.application.setPalette(self.application.style().standardPalette())
            self.application.setStyleSheet(LIGHT_STYLE)
        return resolved


def apply_theme(application: QApplication, theme: str) -> str:
    """API tương thích; code điều phối chính nên giữ một ThemeManager dùng chung."""
    return ThemeManager(application).apply(theme)
