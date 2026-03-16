from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QWidget

_HYBRID_CONTROL_STYLESHEET = """
QPushButton {
    min-height: 38px;
    padding: 0 16px;
    border-radius: 14px;
    border: 1px solid #d9d0c4;
    background: #f8f3ea;
    color: #2f251d;
    font-weight: 600;
}
QPushButton:hover:enabled {
    background: #efe7da;
}
QPushButton:pressed:enabled {
    background: #e7ddd0;
}
QPushButton:disabled {
    background: #efe7da;
    color: #8b8174;
    border-color: #e5dccf;
}
QPushButton[catTone="primary"] {
    border: none;
    background: #2f251d;
    color: #fcfaf6;
}
QPushButton[catTone="primary"]:hover:enabled {
    background: #43362b;
}
QPushButton[catTone="danger"] {
    background: #fff2f0;
    color: #b42318;
    border: 1px solid #f7b3ad;
}
QPushButton[catTone="danger"]:hover:enabled {
    background: #ffe4e1;
}
QPushButton[catTone="ghost"] {
    background: transparent;
    border: 1px solid #ddd4c8;
}
QPushButton[catSize="compact"] {
    min-height: 32px;
    padding: 0 12px;
    border-radius: 12px;
}
QPushButton[catSize="wide"] {
    min-width: 150px;
}
QLineEdit,
QComboBox,
QSpinBox,
QTextEdit,
QPlainTextEdit {
    border: 1px solid #d9d0c4;
    border-radius: 12px;
    background: #fffdf9;
    color: #2f251d;
    selection-background-color: #e7ddd0;
    selection-color: #2f251d;
}
QLineEdit,
QComboBox,
QSpinBox {
    min-height: 38px;
    padding: 0 12px;
}
QComboBox {
    combobox-popup: 0;
    padding-right: 34px;
}
QTextEdit,
QPlainTextEdit {
    padding: 10px 12px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    border: none;
    width: 28px;
}
QComboBox::down-arrow {
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #6e6154;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    border: 1px solid #d9d0c4;
    border-radius: 12px;
    background: #fffdf9;
    color: #2f251d;
    padding: 6px 0;
    selection-background-color: #efe7da;
    selection-color: #2f251d;
    outline: none;
}
QCheckBox {
    color: #2f251d;
    spacing: 8px;
}
QListWidget {
    border: 1px solid #d9d0c4;
    border-radius: 14px;
    background: #fcfaf6;
    alternate-background-color: #f7f1e8;
    padding: 6px;
    outline: none;
}
QListWidget::item {
    padding: 10px 12px;
    border-radius: 10px;
    color: #2f251d;
}
QListWidget::item:hover:!selected {
    background: #f4ecdf;
}
QListWidget::item:selected {
    background: #efe7da;
    color: #2f251d;
}
QListWidget::item:selected:active,
QListWidget::item:selected:!active {
    background: #efe7da;
    color: #2f251d;
}
"""


def apply_hybrid_control_theme(widget: QWidget, *, extra_stylesheet: str | None = None) -> None:
    parts: list[str] = []
    existing = widget.styleSheet().strip()
    if existing:
        parts.append(existing)
    parts.append(_HYBRID_CONTROL_STYLESHEET)
    if extra_stylesheet:
        parts.append(extra_stylesheet)
    widget.setStyleSheet("\n".join(parts))


def set_button_tone(button: QAbstractButton, tone: str | None = None, *, size: str | None = None) -> None:
    button.setProperty("catTone", tone)
    button.setProperty("catSize", size)
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()
