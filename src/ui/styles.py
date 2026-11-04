"""
Industry-Grade Modern Dark DCC Theme for RenderFox.
Inspired by Blender 4.x, Unreal Engine 5, and Marmoset Toolbag.
"""

import os
import sys

if getattr(sys, 'frozen', False):
    _BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ICONS_DIR = os.path.join(_BASE_DIR, "resources", "icons").replace("\\", "/")

MODERN_DARK_THEME = """
/* Global Window & Fonts */
QMainWindow, QDialog {
    background-color: #15161c;
    color: #dcdfe8;
}

QWidget {
    background-color: transparent;
    color: #dcdfe8;
    font-family: 'Segoe UI', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 9.5pt;
    selection-background-color: #3b69d8;
    selection-color: #ffffff;
}

/* Central Workspace Background */
QMainWindow > QWidget {
    background-color: #15161c;
}

/* Top-Level Tab Widget & Navigation */
QTabWidget::pane {
    border: 1px solid #282b37;
    background-color: #1b1c23;
    border-radius: 4px;
    top: -1px;
}

QTabWidget::tab-bar {
    left: 4px;
}

QTabBar::tab {
    background-color: #181920;
    color: #8c93a8;
    padding: 7px 14px;
    border: 1px solid #232530;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #1b1c23;
    color: #ffffff;
    border: 1px solid #282b37;
    border-bottom: 2px solid #1b1c23;
    border-top: 2px solid #4b7bec;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background-color: #21232d;
    color: #c0c6d8;
}

/* Nested / Sub-Tabs Styling (Pill / Flat DCC style) */
QTabWidget QTabWidget::pane {
    border: 1px solid #252836;
    background-color: #181920;
    border-radius: 4px;
    padding: 2px;
}

QTabWidget QTabBar::tab {
    background-color: #1e202b;
    color: #8c93a8;
    padding: 5px 12px;
    border: 1px solid #282b3a;
    border-radius: 4px;
    margin: 2px;
    font-size: 9pt;
}

QTabWidget QTabBar::tab:selected {
    background-color: #3b69d8;
    color: #ffffff;
    border: 1px solid #4b7bec;
    border-top: 1px solid #4b7bec;
    font-weight: 600;
}

QTabWidget QTabBar::tab:hover:!selected {
    background-color: #282c3c;
    color: #ffffff;
}

/* Buttons */
QPushButton {
    background-color: #262936;
    color: #e4e7f2;
    border: 1px solid #363b4d;
    padding: 5px 12px;
    border-radius: 4px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #303445;
    border-color: #4b526b;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #1e202b;
    border-color: #2a2e3d;
}

QPushButton:disabled {
    background-color: #1c1d24;
    border-color: #262732;
    color: #55596b;
}

/* Primary Highlight Action Buttons */
QPushButton[primary="true"], QPushButton#primaryBtn {
    background-color: #3b69d8;
    color: #ffffff;
    border: 1px solid #4b7bec;
}

QPushButton[primary="true"]:hover, QPushButton#primaryBtn:hover {
    background-color: #4b7bec;
    border-color: #6a95f3;
}

QPushButton[primary="true"]:pressed, QPushButton#primaryBtn:pressed {
    background-color: #2c52b0;
}

/* Input Fields & Spinners */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {
    background-color: #1e202b;
    border: 1px solid #303446;
    color: #e8ebf5;
    padding: 5px 10px;
    border-radius: 5px;
    min-height: 28px;
}

QTextEdit, QPlainTextEdit {
    background-color: #1e202b;
    border: 1px solid #303446;
    color: #e8ebf5;
    padding: 8px 10px;
    border-radius: 5px;
    font-family: 'Consolas', 'Segoe UI', sans-serif;
    font-size: 12px;
}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QDateEdit:hover {
    border-color: #42485e;
    background-color: #212431;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {
    border: 1px solid #4b7bec;
    background-color: #232736;
}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {
    background-color: #181922;
    border-color: #262835;
    color: #798096;
}

/* Dropdown ComboBoxes */
QComboBox {
    min-height: 28px;
    padding: 4px 28px 4px 10px;
    selection-background-color: #3b69d8;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #2d3142;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
}

QComboBox::down-arrow {
    image: url("resources/icons/chevron_down_dark.svg");
    width: 12px;
    height: 12px;
}

QComboBox::down-arrow:hover {
    image: url("resources/icons/chevron_down_dark_hover.svg");
}

QComboBox::down-arrow:disabled {
    image: url("resources/icons/chevron_down_disabled.svg");
}

QComboBox QAbstractItemView {
    background-color: #1b1c25;
    border: 1px solid #363b4e;
    color: #dcdfe8;
    selection-background-color: #3b69d8;
    selection-color: #ffffff;
    padding: 4px;
}

/* Group Boxes & Container Panels */
QGroupBox {
    background-color: #191b24;
    border: 1px solid #2e3346;
    border-radius: 8px;
    margin-top: 18px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
    color: #cfd4e8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 2px 8px;
    background-color: #191b24;
    border: 1px solid #2e3346;
    border-radius: 4px;
    color: #e4e7f4;
}

/* Frames & Viewport Panels */
QFrame#panelFrame, QFrame#cardFrame {
    background-color: #191b24;
    border: 1px solid #2e3346;
    border-radius: 8px;
}

QLabel#previewArea, QLabel#viewportPlaceholder {
    background-color: #14151b;
    color: #8c93a8;
    border: 1px solid #252836;
    border-radius: 4px;
}

/* Sliders */
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background: #2b2f3e;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #4b7bec;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #e4e7f2;
    border: 1px solid #3b69d8;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: #ffffff;
    border: 1px solid #4b7bec;
}

/* Progress Bars */
QProgressBar {
    border: 1px solid #2c303e;
    background-color: #1a1b22;
    border-radius: 4px;
    text-align: center;
    color: #ffffff;
    font-weight: 600;
    font-size: 8.5pt;
    height: 16px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b69d8, stop:1 #45aaf2);
    border-radius: 3px;
}

/* Sleek Modern Scrollbars Across the Entire Application */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QScrollBar:vertical {
    border: none;
    background-color: transparent;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #2e3346;
    min-height: 28px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background-color: #4b526d;
}

QScrollBar::handle:vertical:pressed {
    background-color: #3b69d8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: transparent;
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    border: none;
    background-color: transparent;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background-color: #2e3346;
    min-width: 28px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #4b526d;
}

QScrollBar::handle:horizontal:pressed {
    background-color: #3b69d8;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: transparent;
    width: 0px;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

QScrollBar::corner {
    background: transparent;
}

/* Trees, Tables and Lists */
QTreeWidget, QTableWidget, QListWidget {
    background-color: #181920;
    border: 1px solid #282b38;
    border-radius: 4px;
    color: #dcdfe8;
    alternate-background-color: #1c1e26;
    gridline-color: #262936;
}

QTreeWidget::item, QTableWidget::item, QListWidget::item {
    padding: 4px 6px;
    border-radius: 2px;
}

QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #2e4479;
    color: #ffffff;
}

QTreeWidget::item:hover:!selected, QTableWidget::item:hover:!selected, QListWidget::item:hover:!selected {
    background-color: #222531;
}

QHeaderView::section {
    background-color: #1e202a;
    color: #a0a6bd;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #282b38;
    border-bottom: 1px solid #282b38;
    font-weight: 600;
}

/* Menu Bar & Menus */
QMenuBar {
    background-color: #15161c;
    color: #b0b6cc;
    border-bottom: 1px solid #232530;
    padding: 2px;
}

QMenuBar::item {
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #252836;
    color: #ffffff;
}

QMenu {
    background-color: #1c1e27;
    color: #dcdfe8;
    border: 1px solid #2f3345;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #3b69d8;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #2b2e3d;
    margin: 4px 6px;
}

/* Status Bar */
QStatusBar {
    background-color: #121318;
    color: #8c93a8;
    border-top: 1px solid #20222b;
    font-size: 9pt;
}

QStatusBar::item {
    border: none;
}

/* Toolbars */
QToolBar {
    background-color: #181920;
    border-bottom: 1px solid #252836;
    padding: 2px;
    spacing: 4px;
}

/* Tooltips */
QToolTip {
    background-color: #1c1e27;
    color: #f0f2f8;
    border: 1px solid #3b69d8;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 9pt;
}

/* Splitters */
QSplitter::handle {
    background-color: #20222b;
}

QSplitter::handle:hover {
    background-color: #4b7bec;
}
"""

MODERN_LIGHT_THEME = """
/* Global Window & Fonts */
QMainWindow, QDialog {
    background-color: #eef1f6;
    color: #191c24;
}

QWidget {
    background-color: transparent;
    color: #191c24;
    font-family: 'Segoe UI', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 9.5pt;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}

/* Central Workspace Background */
QMainWindow > QWidget {
    background-color: #eef1f6;
}

/* Top-Level Tab Widget & Navigation */
QTabWidget::pane {
    border: 1px solid #d5dbe7;
    background-color: #ffffff;
    border-radius: 4px;
    top: -1px;
}

QTabWidget::tab-bar {
    left: 4px;
}

QTabBar::tab {
    background-color: #e2e7f0;
    color: #555f76;
    padding: 7px 14px;
    border: 1px solid #d0d6e2;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #d5dbe7;
    border-bottom: 2px solid #ffffff;
    border-top: 2px solid #2563eb;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background-color: #edf1f7;
    color: #1e293b;
}

/* Nested / Sub-Tabs Styling (Pill / Flat DCC style) */
QTabWidget QTabWidget::pane {
    border: 1px solid #d5dbe7;
    background-color: #f8fafc;
    border-radius: 4px;
    padding: 2px;
}

QTabWidget QTabBar::tab {
    background-color: #e2e8f0;
    color: #475569;
    padding: 5px 12px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    margin: 2px;
    font-size: 9pt;
}

QTabWidget QTabBar::tab:selected {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
    border-top: 1px solid #1d4ed8;
    font-weight: 600;
}

QTabWidget QTabBar::tab:hover:!selected {
    background-color: #cbd5e1;
    color: #0f172a;
}

/* Buttons */
QPushButton {
    background-color: #ffffff;
    color: #1e293b;
    border: 1px solid #cbd5e1;
    padding: 5px 12px;
    border-radius: 4px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
}

QPushButton:pressed {
    background-color: #e2e8f0;
    border-color: #64748b;
}

QPushButton:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}

/* Primary Highlight Action Buttons */
QPushButton[primary="true"], QPushButton#primaryBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
}

QPushButton[primary="true"]:hover, QPushButton#primaryBtn:hover {
    background-color: #1d4ed8;
    border-color: #1e40af;
}

QPushButton[primary="true"]:pressed, QPushButton#primaryBtn:pressed {
    background-color: #1e40af;
}

/* Input Fields & Spinners */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #1e293b;
    padding: 5px 10px;
    border-radius: 5px;
    min-height: 28px;
}

QTextEdit, QPlainTextEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #1e293b;
    padding: 8px 10px;
    border-radius: 5px;
    font-family: 'Consolas', 'Segoe UI', sans-serif;
    font-size: 12px;
}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QDateEdit:hover {
    border-color: #94a3b8;
    background-color: #ffffff;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {
    border: 1px solid #2563eb;
    background-color: #ffffff;
}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {
    background-color: #f1f5f9;
    border-color: #e2e8f0;
    color: #94a3b8;
}

/* Dropdown ComboBoxes */
QComboBox {
    min-height: 28px;
    padding: 4px 28px 4px 10px;
    selection-background-color: #2563eb;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #cbd5e1;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
}

QComboBox::down-arrow {
    image: url("resources/icons/chevron_down_light.svg");
    width: 12px;
    height: 12px;
}

QComboBox::down-arrow:hover {
    image: url("resources/icons/chevron_down_light_hover.svg");
}

QComboBox::down-arrow:disabled {
    image: url("resources/icons/chevron_down_disabled.svg");
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #1e293b;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    padding: 4px;
}

/* Group Boxes & Container Panels */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #d5dbe7;
    border-radius: 8px;
    margin-top: 18px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
    color: #1e293b;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 2px 8px;
    background-color: #ffffff;
    border: 1px solid #d5dbe7;
    border-radius: 4px;
    color: #1e293b;
}

/* Frames & Viewport Panels */
QFrame#panelFrame, QFrame#cardFrame {
    background-color: #ffffff;
    border: 1px solid #d5dbe7;
    border-radius: 8px;
}

QLabel#previewArea, QLabel#viewportPlaceholder {
    background-color: #f1f5f9;
    color: #64748b;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
}

/* Sliders */
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background: #e2e8f0;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #2563eb;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #ffffff;
    border: 1px solid #2563eb;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: #dbeafe;
    border: 1px solid #1d4ed8;
}

/* Progress Bars */
QProgressBar {
    border: 1px solid #cbd5e1;
    background-color: #f1f5f9;
    border-radius: 4px;
    text-align: center;
    color: #1e293b;
    font-weight: 600;
    font-size: 8.5pt;
    height: 16px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #38bdf8);
    border-radius: 3px;
}

/* Sleek Modern Scrollbars for Light Theme */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QScrollBar:vertical {
    border: none;
    background-color: transparent;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #cbd5e1;
    min-height: 28px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background-color: #94a3b8;
}

QScrollBar::handle:vertical:pressed {
    background-color: #2563eb;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: transparent;
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    border: none;
    background-color: transparent;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background-color: #cbd5e1;
    min-width: 28px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #94a3b8;
}

QScrollBar::handle:horizontal:pressed {
    background-color: #2563eb;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: transparent;
    width: 0px;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

QScrollBar::corner {
    background: transparent;
}

/* Trees, Tables and Lists */
QTreeWidget, QTableWidget, QListWidget {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    color: #1e293b;
    alternate-background-color: #f8fafc;
    gridline-color: #f1f5f9;
}

QTreeWidget::item, QTableWidget::item, QListWidget::item {
    padding: 4px 6px;
    border-radius: 2px;
}

QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #dbeafe;
    color: #1e3a8a;
}

QTreeWidget::item:hover:!selected, QTableWidget::item:hover:!selected, QListWidget::item:hover:!selected {
    background-color: #f1f5f9;
}

QHeaderView::section {
    background-color: #f1f5f9;
    color: #475569;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
}

/* Menu Bar & Menus */
QMenuBar {
    background-color: #ffffff;
    color: #334155;
    border-bottom: 1px solid #e2e8f0;
    padding: 2px;
}

QMenuBar::item {
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #f1f5f9;
    color: #0f172a;
}

QMenu {
    background-color: #ffffff;
    color: #1e293b;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #2563eb;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #e2e8f0;
    margin: 4px 6px;
}

/* Status Bar */
QStatusBar {
    background-color: #f8fafc;
    color: #64748b;
    border-top: 1px solid #e2e8f0;
    font-size: 9pt;
}

QStatusBar::item {
    border: none;
}

/* Toolbars */
QToolBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    padding: 2px;
    spacing: 4px;
}

/* Tooltips */
QToolTip {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #0f172a;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 9pt;
}

/* Splitters */
QSplitter::handle {
    background-color: #e2e8f0;
}

QSplitter::handle:hover {
    background-color: #2563eb;
}
"""

MODERN_MIDNIGHT_THEME = """
/* Global Window & Fonts */
QMainWindow, QDialog {
    background-color: #090d16;
    color: #e2e8f0;
}

QWidget {
    background-color: transparent;
    color: #e2e8f0;
    font-family: 'Segoe UI', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 9.5pt;
    selection-background-color: #4f46e5;
    selection-color: #ffffff;
}

/* Central Workspace Background */
QMainWindow > QWidget {
    background-color: #090d16;
}

/* Top-Level Tab Widget & Navigation */
QTabWidget::pane {
    border: 1px solid #1e293b;
    background-color: #0f172a;
    border-radius: 4px;
    top: -1px;
}

QTabWidget::tab-bar {
    left: 4px;
}

QTabBar::tab {
    background-color: #0b1120;
    color: #94a3b8;
    padding: 7px 14px;
    border: 1px solid #172033;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #0f172a;
    color: #ffffff;
    border: 1px solid #1e293b;
    border-bottom: 2px solid #0f172a;
    border-top: 2px solid #6366f1;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background-color: #162035;
    color: #c7d2fe;
}

/* Nested / Sub-Tabs Styling (Pill / Flat DCC style) */
QTabWidget QTabWidget::pane {
    border: 1px solid #1e293b;
    background-color: #0c1222;
    border-radius: 4px;
    padding: 2px;
}

QTabWidget QTabBar::tab {
    background-color: #131c31;
    color: #94a3b8;
    padding: 5px 12px;
    border: 1px solid #1e2c4f;
    border-radius: 4px;
    margin: 2px;
    font-size: 9pt;
}

QTabWidget QTabBar::tab:selected {
    background-color: #4f46e5;
    color: #ffffff;
    border: 1px solid #6366f1;
    border-top: 1px solid #6366f1;
    font-weight: 600;
}

QTabWidget QTabBar::tab:hover:!selected {
    background-color: #1e2a4a;
    color: #ffffff;
}

/* Buttons */
QPushButton {
    background-color: #151d30;
    color: #e2e8f0;
    border: 1px solid #243152;
    padding: 5px 12px;
    border-radius: 4px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #1e2b47;
    border-color: #3b4d7c;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #0f1626;
    border-color: #1a243d;
}

QPushButton:disabled {
    background-color: #0e1320;
    border-color: #171f33;
    color: #475569;
}

/* Primary Highlight Action Buttons */
QPushButton[primary="true"], QPushButton#primaryBtn {
    background-color: #4f46e5;
    color: #ffffff;
    border: 1px solid #6366f1;
}

QPushButton[primary="true"]:hover, QPushButton#primaryBtn:hover {
    background-color: #6366f1;
    border-color: #818cf8;
}

QPushButton[primary="true"]:pressed, QPushButton#primaryBtn:pressed {
    background-color: #3730a3;
}

/* Input Fields & Spinners */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    color: #f8fafc;
    padding: 5px 10px;
    border-radius: 5px;
    min-height: 28px;
}

QTextEdit, QPlainTextEdit {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    color: #f8fafc;
    padding: 8px 10px;
    border-radius: 5px;
    font-family: 'Consolas', 'Segoe UI', sans-serif;
    font-size: 12px;
}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QDateEdit:hover {
    border-color: #334155;
    background-color: #131d33;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {
    border: 1px solid #6366f1;
    background-color: #141f38;
}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {
    background-color: #090e1a;
    border-color: #162035;
    color: #64748b;
}

/* Dropdown ComboBoxes */
QComboBox {
    min-height: 28px;
    padding: 4px 28px 4px 10px;
    selection-background-color: #4f46e5;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #1e293b;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
}

QComboBox::down-arrow {
    image: url("resources/icons/chevron_down_midnight.svg");
    width: 12px;
    height: 12px;
}

QComboBox::down-arrow:hover {
    image: url("resources/icons/chevron_down_dark_hover.svg");
}

QComboBox::down-arrow:disabled {
    image: url("resources/icons/chevron_down_disabled.svg");
}

QComboBox QAbstractItemView {
    background-color: #0f172a;
    border: 1px solid #243152;
    color: #f8fafc;
    selection-background-color: #4f46e5;
    selection-color: #ffffff;
    padding: 4px;
}

/* Group Boxes & Container Panels */
QGroupBox {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 8px;
    margin-top: 18px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
    color: #c7d2fe;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 2px 8px;
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 4px;
    color: #e0e7ff;
}

/* Frames & Viewport Panels */
QFrame#panelFrame, QFrame#cardFrame {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 8px;
}

QLabel#previewArea, QLabel#viewportPlaceholder {
    background-color: #090e1a;
    color: #818cf8;
    border: 1px solid #1e293b;
    border-radius: 4px;
}

/* Sliders */
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background: #1e293b;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #6366f1;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #e2e8f0;
    border: 1px solid #4f46e5;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: #ffffff;
    border: 1px solid #6366f1;
}

/* Progress Bars */
QProgressBar {
    border: 1px solid #1e293b;
    background-color: #0c1222;
    border-radius: 4px;
    text-align: center;
    color: #ffffff;
    font-weight: 600;
    font-size: 8.5pt;
    height: 16px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #818cf8);
    border-radius: 3px;
}

/* Sleek Modern Scrollbars for Midnight Theme */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QScrollBar:vertical {
    border: none;
    background-color: transparent;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #1e293b;
    min-height: 28px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background-color: #334155;
}

QScrollBar::handle:vertical:pressed {
    background-color: #6366f1;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: transparent;
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    border: none;
    background-color: transparent;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background-color: #1e293b;
    min-width: 28px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #334155;
}

QScrollBar::handle:horizontal:pressed {
    background-color: #6366f1;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: transparent;
    width: 0px;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

QScrollBar::corner {
    background: transparent;
}

/* Trees, Tables and Lists */
QTreeWidget, QTableWidget, QListWidget {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 4px;
    color: #e2e8f0;
    alternate-background-color: #131d33;
    gridline-color: #1e293b;
}

QTreeWidget::item, QTableWidget::item, QListWidget::item {
    padding: 4px 6px;
    border-radius: 2px;
}

QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #312e81;
    color: #ffffff;
}

QTreeWidget::item:hover:!selected, QTableWidget::item:hover:!selected, QListWidget::item:hover:!selected {
    background-color: #17233f;
}

QHeaderView::section {
    background-color: #131c31;
    color: #a5b4fc;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #1e293b;
    border-bottom: 1px solid #1e293b;
    font-weight: 600;
}

/* Menu Bar & Menus */
QMenuBar {
    background-color: #090d16;
    color: #cbd5e1;
    border-bottom: 1px solid #1e293b;
    padding: 2px;
}

QMenuBar::item {
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #1e293b;
    color: #ffffff;
}

QMenu {
    background-color: #0f172a;
    color: #e2e8f0;
    border: 1px solid #243152;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #4f46e5;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #1e293b;
    margin: 4px 6px;
}

/* Status Bar */
QStatusBar {
    background-color: #070a12;
    color: #94a3b8;
    border-top: 1px solid #172033;
    font-size: 9pt;
}

QStatusBar::item {
    border: none;
}

/* Toolbars */
QToolBar {
    background-color: #0c1222;
    border-bottom: 1px solid #1e293b;
    padding: 2px;
    spacing: 4px;
}

/* Tooltips */
QToolTip {
    background-color: #0f172a;
    color: #f8fafc;
    border: 1px solid #6366f1;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 9pt;
}

/* Splitters */
QSplitter::handle {
    background-color: #172033;
}

QSplitter::handle:hover {
    background-color: #6366f1;
}
"""

AVAILABLE_THEMES = ["Dark", "Light", "Midnight", "Auto"]


def get_system_theme() -> str:
    """Detect whether Windows system is set to dark or light theme."""
    import platform
    if platform.system() == "Windows":
        try:
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(registry, r"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            if value == 1:
                return "Light"
        except Exception:
            pass
    return "Dark"


def get_theme_stylesheet(theme_name: str) -> str:
    """Return the complete, high-fidelity QSS stylesheet for the given theme name."""
    normalized = (theme_name or "Dark").strip().title()
    if normalized == "Auto":
        normalized = get_system_theme()
        
    if normalized == "Light":
        raw = MODERN_LIGHT_THEME
    elif normalized == "Midnight":
        raw = MODERN_MIDNIGHT_THEME
    else:
        raw = MODERN_DARK_THEME
        
    if os.path.exists(_ICONS_DIR):
        raw = raw.replace("resources/icons/", f"{_ICONS_DIR}/")
    return raw

