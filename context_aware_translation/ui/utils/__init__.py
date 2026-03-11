"""Utilities for the UI module."""

from PySide6.QtWidgets import QLabel

TIP_LABEL_STYLESHEET = "QLabel {color: #6b7280; font-size: 12px;}"


def create_tip_label(text: str) -> QLabel:
    """Create a subtle hint label with wrapped text."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(TIP_LABEL_STYLESHEET)
    return label


__all__ = ["create_tip_label"]
