"""Utilities for the UI module."""

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication
from PySide6.QtWidgets import QLabel

TIP_LABEL_STYLESHEET = "QLabel {color: #6b7280; font-size: 12px;}"

DOCUMENT_TYPE_LABELS = {
    "text": QT_TRANSLATE_NOOP("ExportView", "Text"),
    "pdf": QT_TRANSLATE_NOOP("ExportView", "PDF"),
    "epub": QT_TRANSLATE_NOOP("ExportView", "EPUB"),
    "manga": QT_TRANSLATE_NOOP("ExportView", "Manga"),
    "scanned_book": QT_TRANSLATE_NOOP("ExportView", "Scanned Book"),
}


def create_tip_label(text: str) -> QLabel:
    """Create a subtle hint label with wrapped text."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(TIP_LABEL_STYLESHEET)
    return label


def translate_document_type(doc_type: str) -> str:
    """Return localized document type label using ExportView translation context."""
    source = DOCUMENT_TYPE_LABELS.get(doc_type)
    if source is None:
        return doc_type
    return QCoreApplication.translate("ExportView", source)


__all__ = ["create_tip_label", "translate_document_type"]
