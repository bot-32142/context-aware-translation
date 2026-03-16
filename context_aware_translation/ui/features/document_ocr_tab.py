from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import SurfaceStatus
from context_aware_translation.application.contracts.document import (
    CancelOCRRequest,
    DocumentOCRState,
    OCRBoundingBox,
    OCRPageState,
    OCRTextElement,
    RunOCRRequest,
    SaveOCRPageRequest,
)
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.ui.chrome_sizing import sync_qml_host_height
from context_aware_translation.ui.i18n import translate_backend_text, translate_progress_label
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.document_ocr_pane import DocumentOcrPaneViewModel
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone
from context_aware_translation.ui.widgets.image_viewer import ImageViewer
from context_aware_translation.ui.widgets.progress_widget import ProgressWidget


class _SelectableTextEdit(QTextEdit):
    focused = Signal()

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self.focused.emit()
        super().focusInEvent(event)


@dataclass(frozen=True)
class _ElementPalette:
    accent: str
    background: str
    background_selected: str
    border: str
    editor_background: str
    editor_border: str
    badge_background: str
    badge_border: str
    muted_text: str


@dataclass(slots=True)
class _PageDraft:
    extracted_text: str | None = None
    element_texts: list[str] | None = None


_DEFAULT_ELEMENT_PALETTE = _ElementPalette(
    accent="#5f5447",
    background="#f7f1e8",
    background_selected="#efe7da",
    border="#d8cbbc",
    editor_background="#fffdfa",
    editor_border="#dfd2c4",
    badge_background="#efe3d3",
    badge_border="#dccab7",
    muted_text="#7a7063",
)

_ELEMENT_PALETTES = {
    "chapter": _ElementPalette(
        accent="#1a237e",
        background="#eef1ff",
        background_selected="#e4e8ff",
        border="#c6cffd",
        editor_background="#f9faff",
        editor_border="#c2caf7",
        badge_background="#dfe5ff",
        badge_border="#b7c4ff",
        muted_text="#5a6794",
    ),
    "section": _ElementPalette(
        accent="#1565c0",
        background="#ecf5ff",
        background_selected="#e2f0ff",
        border="#b8d8f7",
        editor_background="#f9fcff",
        editor_border="#bbd8f2",
        badge_background="#dcedff",
        badge_border="#b6d7f8",
        muted_text="#58789a",
    ),
    "subsection": _ElementPalette(
        accent="#42a5f5",
        background="#eef8ff",
        background_selected="#e4f3ff",
        border="#bfe3fb",
        editor_background="#fbfdff",
        editor_border="#c4e0f4",
        badge_background="#dcf0ff",
        badge_border="#b8dcf4",
        muted_text="#5b8096",
    ),
    "paragraph": _ElementPalette(
        accent="#5f5447",
        background="#f7f1e8",
        background_selected="#efe7da",
        border="#d8cbbc",
        editor_background="#fffdfa",
        editor_border="#dfd2c4",
        badge_background="#efe3d3",
        badge_border="#dccab7",
        muted_text="#7a7063",
    ),
    "image": _ElementPalette(
        accent="#2e7d32",
        background="#edf8ef",
        background_selected="#e1f2e4",
        border="#b8dcba",
        editor_background="#fbfffb",
        editor_border="#bfdabd",
        badge_background="#dcf1de",
        badge_border="#b7d7b9",
        muted_text="#5d7c60",
    ),
    "table": _ElementPalette(
        accent="#6a1b9a",
        background="#f7eefc",
        background_selected="#f0e4fa",
        border="#dac0ea",
        editor_background="#fefbff",
        editor_border="#dcc7ea",
        badge_background="#eddcf7",
        badge_border="#d0b4e4",
        muted_text="#7f6990",
    ),
    "list": _ElementPalette(
        accent="#e65100",
        background="#fff2e8",
        background_selected="#ffe8d7",
        border="#f0c7ab",
        editor_background="#fffdfa",
        editor_border="#efd0b6",
        badge_background="#ffe1ce",
        badge_border="#efc2a3",
        muted_text="#8d705e",
    ),
    "quote": _ElementPalette(
        accent="#00695c",
        background="#eaf8f5",
        background_selected="#dff2ee",
        border="#b5ddd5",
        editor_background="#fbfffe",
        editor_border="#badfd8",
        badge_background="#d8f0eb",
        badge_border="#add5cf",
        muted_text="#5a8079",
    ),
}

_ELEMENT_KIND_ALIASES = {
    "text": "paragraph",
    "heading": "section",
    "subheading": "subsection",
    "sub_section": "subsection",
    "bullet_list": "list",
    "ordered_list": "list",
    "unordered_list": "list",
}


class _StructuredElementCard(QFrame):
    selected = Signal(int)

    def __init__(self, index: int, element: OCRTextElement, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._selected = False
        self._palette = self._palette_for_kind(element.kind)
        self.setObjectName("ocrStructuredElementCard")
        self._editor = _SelectableTextEdit(self)
        self._editor.setObjectName("ocrStructuredElementEditor")
        self._editor.setPlainText(element.text)
        self._editor.setMinimumHeight(64)
        self._editor.focused.connect(lambda: self.selected.emit(self._index))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        self._title = QLabel(self._title_text(element), self)
        self._title.setStyleSheet(
            f"color: {self._palette.accent};"
            "font-weight: 700;"
            "font-size: 11px;"
            f"background-color: {self._palette.badge_background};"
            f"border: 1px solid {self._palette.badge_border};"
            "border-radius: 9px;"
            "padding: 2px 8px;"
        )
        layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignLeft)
        if element.bbox is not None:
            self._bbox_label = QLabel(self._bbox_text(element.bbox), self)
            self._bbox_label.setStyleSheet(
                f"color: {self._palette.muted_text};"
                "font-size: 11px;"
                f"background-color: {self._palette.editor_background};"
                f"border: 1px solid {self._palette.editor_border};"
                "border-radius: 8px;"
                "padding: 2px 8px;"
            )
            layout.addWidget(self._bbox_label, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            self._bbox_label = None
        layout.addWidget(self._editor)
        self._apply_style()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.selected.emit(self._index)
        super().mousePressEvent(event)

    def text(self) -> str:
        return self._editor.toPlainText()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        border_width = 2 if self._selected else 1
        border = self._palette.accent if self._selected else self._palette.border
        background = self._palette.background_selected if self._selected else self._palette.background
        self.setStyleSheet(
            f"QFrame#ocrStructuredElementCard {{"
            f" border: {border_width}px solid {border};"
            " border-radius: 10px;"
            f" background-color: {background};"
            "}"
        )
        self._editor.setStyleSheet(
            f"QTextEdit#ocrStructuredElementEditor {{"
            f" background-color: {self._palette.editor_background};"
            f" border: 1px solid {self._palette.accent if self._selected else self._palette.editor_border};"
            " border-radius: 8px;"
            " padding: 6px 8px;"
            f" selection-background-color: {self._palette.badge_background};"
            "}"
        )

    @staticmethod
    def _title_text(element: OCRTextElement) -> str:
        kind = (element.kind or "Text").replace("_", " ").title()
        return f"{kind}"

    @staticmethod
    def _bbox_text(bbox: OCRBoundingBox) -> str:
        return f"x={bbox.x:.3f}, y={bbox.y:.3f}, w={bbox.width:.3f}, h={bbox.height:.3f}"

    @classmethod
    def _palette_for_kind(cls, kind: str | None) -> _ElementPalette:
        if not kind:
            return _DEFAULT_ELEMENT_PALETTE
        normalized = kind.strip().lower().replace("-", "_").replace(" ", "_")
        mapped = _ELEMENT_KIND_ALIASES.get(normalized, normalized)
        return _ELEMENT_PALETTES.get(mapped, _DEFAULT_ELEMENT_PALETTE)


class _StructuredElementList(QScrollArea):
    element_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[_StructuredElementCard] = []
        self._selected_index = -1
        self._container = QWidget(self)
        self._container.setObjectName("ocrStructuredElementContainer")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(8)
        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QScrollArea { background-color: #f6f1e8; border: none; }"
            "QWidget#ocrStructuredElementContainer { background-color: transparent; }"
        )

    def set_elements(self, elements: list[OCRTextElement]) -> None:
        self.clear()
        for index, element in enumerate(elements):
            card = _StructuredElementCard(index, element, parent=self._container)
            card.selected.connect(self._on_selected)
            self._cards.append(card)
            self._layout.addWidget(card)
        self._layout.addStretch()

    def clear(self) -> None:
        self._selected_index = -1
        self._cards.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def texts(self) -> list[str]:
        return [card.text() for card in self._cards]

    def select_element(self, index: int) -> None:
        if 0 <= self._selected_index < len(self._cards):
            self._cards[self._selected_index].set_selected(False)
        self._selected_index = index
        if 0 <= index < len(self._cards):
            self._cards[index].set_selected(True)
            self.ensureWidgetVisible(self._cards[index])

    def _on_selected(self, index: int) -> None:
        self.select_element(index)
        self.element_selected.emit(index)


class DocumentOCRTab(QWidget):
    def __init__(
        self,
        service: DocumentService,
        project_id: str,
        document_id: int,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._project_id = project_id
        self._document_id = document_id
        self.viewmodel = DocumentOcrPaneViewModel(self)
        self._state: DocumentOCRState | None = None
        self._current_page_index: int | None = None
        self._page_drafts: dict[int, _PageDraft] = {}
        self._element_to_bbox: dict[int, int] = {}
        self._bbox_to_element: dict[int, int] = {}
        self._chrome_resize_timer = QTimer(self)
        self._chrome_resize_timer.setSingleShot(True)
        self._chrome_resize_timer.timeout.connect(self._sync_chrome_height)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._init_compatibility_controls()

        self._content_widget = QWidget(self)
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.image_viewer = ImageViewer(self)
        self.image_viewer.bbox_clicked.connect(self._on_bbox_clicked)
        splitter.addWidget(self.image_viewer)

        self._right_stack = QStackedWidget(self)
        self.text_edit = QTextEdit(self)
        self.text_edit.setPlaceholderText(self.tr("OCR text will appear here."))
        self.structured_list = _StructuredElementList(self)
        self.structured_list.element_selected.connect(self._on_element_selected)
        self._right_stack.addWidget(self.text_edit)
        self._right_stack.addWidget(self.structured_list)
        splitter.addWidget(self._right_stack)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([480, 480])
        content_layout.addWidget(splitter, 1)
        layout.addWidget(self._content_widget, 1)
        layout.addWidget(self.empty_label)

        self.chrome_host = QmlChromeHost(
            "document/ocr/DocumentOCRPaneChrome.qml",
            context_objects={"ocrPane": self.viewmodel},
            parent=self,
        )
        layout.addWidget(self.chrome_host)
        apply_hybrid_control_theme(self)
        for button in (
            self.first_button,
            self.prev_button,
            self.next_button,
            self.last_button,
            self.go_button,
            self.run_current_button,
            self.run_pending_button,
            self.save_button,
        ):
            set_button_tone(button, "primary" if button is self.save_button else None, size="compact")

        self._connect_qml_signals()
        self._sync_chrome_state()
        self._schedule_chrome_resize()

    def _init_compatibility_controls(self) -> None:
        self.tip_label = create_tip_label(
            self.tr("OCR applies only to the current document. Saving OCR does not rerun later steps.")
        )
        self.tip_label.setParent(self)
        self.tip_label.hide()

        self.first_button = QPushButton(self.tr("|<"), self)
        self.first_button.setToolTip(self.tr("First page"))
        self.first_button.clicked.connect(self._go_first)
        self.first_button.hide()

        self.prev_button = QPushButton(self.tr("<"), self)
        self.prev_button.setToolTip(self.tr("Previous page"))
        self.prev_button.clicked.connect(self._go_previous)
        self.prev_button.hide()

        self.page_label = QLabel(self.tr("Page 0 of 0"), self)
        self.page_label.hide()

        self.page_status_label = QLabel(self)
        self.page_status_label.hide()

        self.next_button = QPushButton(self.tr(">"), self)
        self.next_button.setToolTip(self.tr("Next page"))
        self.next_button.clicked.connect(self._go_next)
        self.next_button.hide()

        self.last_button = QPushButton(self.tr(">|"), self)
        self.last_button.setToolTip(self.tr("Last page"))
        self.last_button.clicked.connect(self._go_last)
        self.last_button.hide()

        self.go_to_label = QLabel(self.tr("Go to:"), self)
        self.go_to_label.hide()

        self.page_spinbox = QSpinBox(self)
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.setFixedWidth(64)
        self.page_spinbox.setToolTip(self.tr("Enter page number"))
        self.page_spinbox.hide()

        self.go_button = QPushButton(self.tr("Go"), self)
        self.go_button.setToolTip(self.tr("Jump to page"))
        self.go_button.clicked.connect(self._go_to_entered_page)
        self.go_button.hide()

        self.run_current_button = QPushButton(self.tr("(Re)run OCR (Current Page)"), self)
        self.run_current_button.setToolTip(self.tr("Run or re-run OCR on the current page"))
        self.run_current_button.clicked.connect(self._run_current)
        self.run_current_button.hide()

        self.run_pending_button = QPushButton(self.tr("Run OCR for Pending Pages"), self)
        self.run_pending_button.setToolTip(self.tr("Run OCR on all pending pages in this document"))
        self.run_pending_button.clicked.connect(self._run_pending)
        self.run_pending_button.hide()

        self.save_button = QPushButton(self.tr("Save"), self)
        self.save_button.setToolTip(self.tr("Save edited OCR text"))
        self.save_button.clicked.connect(self._save_current)
        self.save_button.hide()

        self.message_label = QLabel(self)
        self.message_label.hide()

        self.progress_widget = ProgressWidget(self)
        self.progress_widget.setVisible(False)
        self.progress_widget.cancelled.connect(self._cancel_ocr)
        self.progress_widget.hide()

        self.empty_label = create_tip_label(self.tr("No image pages are available for OCR in this document."))
        self.empty_label.setParent(self)
        self.empty_label.hide()

    def refresh(self) -> None:
        self._refresh_with_draft_exclusions(set())

    def _refresh_with_draft_exclusions(self, excluded_source_ids: set[int]) -> None:
        current_source_id = self._current_page.source_id if self._current_page is not None else None
        self._remember_current_draft(excluded_source_ids=excluded_source_ids)
        try:
            self._state = self._service.get_ocr(self._project_id, self._document_id)
        except ApplicationError as exc:
            self._set_message(exc.payload.message)
            return
        self._sync_pages(current_source_id=current_source_id)
        self._apply_actions()
        self._apply_progress()
        self._sync_chrome_state()

    def get_running_operations(self) -> list[str]:
        if self._state is not None and self._state.active_task_id is not None:
            return ["ocr"]
        return []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        if include_engine_tasks and self._state is not None and self._state.active_task_id is not None:
            self._cancel_ocr()

    @property
    def _current_page(self) -> OCRPageState | None:
        if self._state is None or self._current_page_index is None:
            return None
        if self._current_page_index < 0 or self._current_page_index >= len(self._state.pages):
            return None
        return self._state.pages[self._current_page_index]

    def _sync_pages(self, *, current_source_id: int | None) -> None:
        assert self._state is not None
        pages = self._state.pages
        if not pages:
            self._apply_empty_state()
            return

        self.empty_label.hide()
        self._content_widget.show()
        self.image_viewer.setEnabled(True)
        self.text_edit.setEnabled(True)
        self.structured_list.setEnabled(True)
        self.go_to_label.setEnabled(True)
        self.page_spinbox.setEnabled(True)
        self.go_button.setEnabled(True)
        selected_index = 0
        if current_source_id is not None:
            for index, page in enumerate(pages):
                if page.source_id == current_source_id:
                    selected_index = index
                    break
        elif self._state.current_page_index is not None and 0 <= self._state.current_page_index < len(pages):
            selected_index = self._state.current_page_index

        self._set_current_page(selected_index)

    def _apply_empty_state(self) -> None:
        self._current_page_index = None
        self.image_viewer.clear_image()
        self.image_viewer.clear_bboxes()
        self.image_viewer.setEnabled(False)
        self.text_edit.clear()
        self.text_edit.setEnabled(False)
        self.structured_list.clear()
        self.structured_list.setEnabled(False)
        self._right_stack.setCurrentWidget(self.text_edit)
        self.page_label.setText(self.tr("Page 0 of 0"))
        self.page_status_label.clear()
        self.page_status_label.setStyleSheet("")
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.setValue(1)
        self.go_to_label.setEnabled(False)
        self.page_spinbox.setEnabled(False)
        self.go_button.setEnabled(False)
        self.first_button.setEnabled(False)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.last_button.setEnabled(False)
        self.empty_label.show()
        self._content_widget.hide()
        self._apply_actions()
        self._apply_progress()
        self._sync_chrome_state()

    def _set_current_page(self, index: int) -> None:
        if self._state is None or not self._state.pages:
            self._current_page_index = None
            return
        if index < 0 or index >= len(self._state.pages):
            index = 0
        previous_page = self._current_page
        next_page = self._state.pages[index]
        if previous_page is not None and previous_page.source_id != next_page.source_id:
            self._remember_current_draft()
        self._current_page_index = index

        page = next_page
        total_pages = len(self._state.pages)
        self.page_label.setText(self.tr("Page %1 of %2").replace("%1", str(index + 1)).replace("%2", str(total_pages)))
        self.page_spinbox.setMaximum(total_pages)
        self.page_spinbox.setValue(index + 1)
        self.first_button.setEnabled(index > 0)
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self._state.pages) - 1)
        self.last_button.setEnabled(index < len(self._state.pages) - 1)
        self._apply_page_status(page)

        try:
            image_bytes = self._service.get_ocr_page_image(self._project_id, self._document_id, page.source_id)
        except ApplicationError:
            image_bytes = None
        if image_bytes:
            self.image_viewer.set_image(image_bytes)
        else:
            self.image_viewer.clear_image()

        if page.elements:
            self._set_structured_page(page)
        else:
            self.image_viewer.clear_bboxes()
            self.structured_list.clear()
            self.text_edit.setPlainText(page.extracted_text or "")
            self._right_stack.setCurrentWidget(self.text_edit)
        self._restore_page_draft(page)
        self._apply_actions()
        self._sync_chrome_state()

    def _apply_page_status(self, page: OCRPageState) -> None:
        if page.status is SurfaceStatus.DONE:
            self.page_status_label.setText(self.tr("OCR Done"))
            self.page_status_label.setStyleSheet("color: green; font-weight: bold;")
        elif page.status is SurfaceStatus.RUNNING:
            self.page_status_label.setText(self.tr("OCR Running"))
            self.page_status_label.setStyleSheet("color: #2563eb; font-weight: bold;")
        elif page.status is SurfaceStatus.FAILED:
            self.page_status_label.setText(self.tr("OCR Failed"))
            self.page_status_label.setStyleSheet("color: #d92d20; font-weight: bold;")
        else:
            self.page_status_label.setText(self.tr("Pending OCR"))
            self.page_status_label.setStyleSheet("color: orange; font-weight: bold;")

    def _set_structured_page(self, page: OCRPageState) -> None:
        self.structured_list.set_elements(page.elements)
        self._right_stack.setCurrentWidget(self.structured_list)
        self._element_to_bbox = {}
        self._bbox_to_element = {}
        bboxes: list[object] = []
        for index, element in enumerate(page.elements):
            if element.bbox is None:
                continue
            bbox_index = len(bboxes)
            bboxes.append(cast(object, element.bbox))
            self._element_to_bbox[index] = bbox_index
            self._bbox_to_element.setdefault(bbox_index, index)
        if bboxes:
            self.image_viewer.set_bboxes(bboxes)
        else:
            self.image_viewer.clear_bboxes()

    def _on_bbox_clicked(self, bbox_index: int) -> None:
        element_index = self._bbox_to_element.get(bbox_index)
        if element_index is None:
            return
        self.structured_list.select_element(element_index)
        self.image_viewer.highlight_bbox(bbox_index)

    def _on_element_selected(self, element_index: int) -> None:
        bbox_index = self._element_to_bbox.get(element_index, -1)
        self.image_viewer.highlight_bbox(bbox_index)

    def _apply_actions(self) -> None:
        page = self._current_page
        has_pages = self._state is not None and bool(self._state.pages)
        if self._state is None or not has_pages:
            self.save_button.setEnabled(False)
            self.run_current_button.setEnabled(False)
            self.run_pending_button.setEnabled(False)
            self._sync_chrome_state()
            return

        self.save_button.setEnabled(page is not None and self._state.actions.save.enabled)
        self.save_button.setToolTip(
            translate_backend_text(self._state.actions.save.blocker.message)
            if self._state.actions.save.blocker is not None
            else self.tr("Save edited OCR text")
        )

        self.run_current_button.setEnabled(page is not None and self._state.actions.run_current.enabled)
        self.run_current_button.setToolTip(
            translate_backend_text(self._state.actions.run_current.blocker.message)
            if self._state.actions.run_current.blocker is not None
            else self.tr("Run or re-run OCR on the current page")
        )

        self.run_pending_button.setEnabled(self._state.actions.run_pending.enabled)
        self.run_pending_button.setToolTip(
            translate_backend_text(self._state.actions.run_pending.blocker.message)
            if self._state.actions.run_pending.blocker is not None
            else self.tr("Run OCR on all pending pages in this document")
        )
        self._sync_chrome_state()

    def _apply_progress(self) -> None:
        if self._state is None or self._state.active_task_id is None:
            self.progress_widget.reset()
            self.progress_widget.setVisible(False)
            self._sync_chrome_state()
            return

        self.progress_widget.setVisible(True)
        self.progress_widget.set_cancellable(True)
        progress = self._state.progress
        if progress is not None and progress.current is not None and progress.total is not None and progress.total > 0:
            self.progress_widget.progress_bar.setRange(0, 100)
            self.progress_widget.set_progress(
                progress.current, progress.total, progress.label or self.tr("OCR running...")
            )
            if progress.label:
                self.progress_widget.message_label.setText(translate_progress_label(progress.label))
            self._sync_chrome_state()
            return

        self.progress_widget.progress_bar.setRange(0, 0)
        self.progress_widget.message_label.setText(self.tr("OCR running..."))
        self.progress_widget.eta_label.clear()
        self._sync_chrome_state()

    def _go_previous(self) -> None:
        if self._current_page_index is None:
            return
        self._set_current_page(self._current_page_index - 1)

    def _go_first(self) -> None:
        if self._state is None or not self._state.pages:
            return
        self._set_current_page(0)

    def _go_next(self) -> None:
        if self._current_page_index is None:
            return
        self._set_current_page(self._current_page_index + 1)

    def _go_last(self) -> None:
        if self._state is None or not self._state.pages:
            return
        self._set_current_page(len(self._state.pages) - 1)

    def _go_to_entered_page(self) -> None:
        if self._state is None or not self._state.pages:
            return
        self._set_current_page(self.page_spinbox.value() - 1)

    def _go_to_page_number(self, page_number: int) -> None:
        if self._state is None or not self._state.pages:
            return
        clamped = min(max(page_number, 1), len(self._state.pages))
        self.page_spinbox.setValue(clamped)
        self._go_to_entered_page()

    def _save_current(self) -> None:
        page = self._current_page
        if page is None:
            return

        if page.elements:
            edited_lines = self.structured_list.texts()
            if len(edited_lines) != len(page.elements):
                QMessageBox.warning(
                    self,
                    self.tr("Line Count Mismatch"),
                    self.tr("Structured OCR text must keep the same number of lines as the original OCR result."),
                )
                return
            elements = [
                OCRTextElement(
                    element_id=original.element_id,
                    bbox_id=original.bbox_id,
                    text=text,
                )
                for original, text in zip(page.elements, edited_lines, strict=True)
            ]
            request = SaveOCRPageRequest(
                project_id=self._project_id,
                document_id=self._document_id,
                source_id=page.source_id,
                extracted_text="\n".join(edited_lines),
                elements=elements,
            )
        else:
            edited_text = self.text_edit.toPlainText()
            if not ((page.extracted_text or "").strip() or edited_text.strip()):
                QMessageBox.information(self, self.tr("OCR"), self.tr("No OCR data is available for this page yet."))
                return
            request = SaveOCRPageRequest(
                project_id=self._project_id,
                document_id=self._document_id,
                source_id=page.source_id,
                extracted_text=edited_text,
            )

        try:
            self._state = self._service.save_ocr(request)
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("OCR"), translate_backend_text(exc.payload.message))
            self.refresh()
            return

        self._set_message(self.tr("OCR text saved."))
        self._page_drafts.pop(page.source_id, None)
        self._sync_pages(current_source_id=page.source_id)
        self._apply_actions()
        self._apply_progress()

    def _run_current(self) -> None:
        page = self._current_page
        if page is None:
            return
        try:
            result = self._service.run_ocr(
                RunOCRRequest(project_id=self._project_id, document_id=self._document_id, source_id=page.source_id)
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("OCR"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        self._set_message(result.message.text if result.message is not None else self.tr("OCR queued."))
        self._clear_page_drafts({page.source_id})
        self._refresh_with_draft_exclusions({page.source_id})

    def _run_pending(self) -> None:
        affected_source_ids = self._pending_page_source_ids()
        try:
            result = self._service.run_ocr(
                RunOCRRequest(project_id=self._project_id, document_id=self._document_id, pending_only=True)
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("OCR"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        self._set_message(result.message.text if result.message is not None else self.tr("OCR queued."))
        self._clear_page_drafts(affected_source_ids)
        self._refresh_with_draft_exclusions(affected_source_ids)

    def _cancel_ocr(self) -> None:
        if self._state is None or self._state.active_task_id is None:
            return
        try:
            result = self._service.cancel_ocr(
                CancelOCRRequest(project_id=self._project_id, task_id=self._state.active_task_id)
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("OCR"), translate_backend_text(exc.payload.message))
            self.refresh()
            return
        self._set_message(result.message.text if result.message is not None else self.tr("OCR cancellation requested."))
        self.refresh()

    def _remember_current_draft(self, *, excluded_source_ids: set[int] | None = None) -> None:
        page = self._current_page
        if page is None:
            return
        if excluded_source_ids is not None and page.source_id in excluded_source_ids:
            self._page_drafts.pop(page.source_id, None)
            return
        draft = self._collect_page_draft(page)
        if draft is None:
            self._page_drafts.pop(page.source_id, None)
            return
        self._page_drafts[page.source_id] = draft

    def _clear_page_drafts(self, source_ids: set[int]) -> None:
        for source_id in source_ids:
            self._page_drafts.pop(source_id, None)

    def _pending_page_source_ids(self) -> set[int]:
        if self._state is None:
            return set()
        return {page.source_id for page in self._state.pages if page.status is SurfaceStatus.READY}

    def _collect_page_draft(self, page: OCRPageState) -> _PageDraft | None:
        if page.elements:
            texts = self.structured_list.texts()
            original_texts = [element.text for element in page.elements]
            if texts and texts != original_texts:
                return _PageDraft(element_texts=texts)
            return None
        edited_text = self.text_edit.toPlainText()
        if edited_text != (page.extracted_text or ""):
            return _PageDraft(extracted_text=edited_text)
        return None

    def _restore_page_draft(self, page: OCRPageState) -> None:
        draft = self._page_drafts.get(page.source_id)
        if draft is None:
            return
        if page.elements:
            if draft.element_texts is None or len(draft.element_texts) != len(page.elements):
                return
            for card, text in zip(self.structured_list._cards, draft.element_texts, strict=True):
                card._editor.setPlainText(text)
            return
        if draft.extracted_text is not None:
            self.text_edit.setPlainText(draft.extracted_text)

    def _set_message(self, text: str) -> None:
        if not text:
            self.message_label.hide()
            self.message_label.clear()
            self._sync_chrome_state()
            return
        self.message_label.setText(translate_backend_text(text))
        self.message_label.show()
        self._sync_chrome_state()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_chrome_resize()

    def retranslateUi(self) -> None:
        self.tip_label.setText(
            self.tr(
                "OCR applies only to the current document. Saving OCR clears later glossary, translation, and export results so they can be rebuilt from the updated OCR."
            )
        )
        self.text_edit.setPlaceholderText(self.tr("OCR text will appear here."))
        self.first_button.setText(self.tr("|<"))
        self.first_button.setToolTip(self.tr("First page"))
        self.prev_button.setText(self.tr("<"))
        self.prev_button.setToolTip(self.tr("Previous page"))
        self.next_button.setText(self.tr(">"))
        self.next_button.setToolTip(self.tr("Next page"))
        self.last_button.setText(self.tr(">|"))
        self.last_button.setToolTip(self.tr("Last page"))
        self.go_to_label.setText(self.tr("Go to:"))
        self.page_spinbox.setToolTip(self.tr("Enter page number"))
        self.go_button.setText(self.tr("Go"))
        self.go_button.setToolTip(self.tr("Jump to page"))
        self.run_current_button.setText(self.tr("(Re)run OCR (Current Page)"))
        self.run_current_button.setToolTip(self.tr("Run or re-run OCR on the current page"))
        self.run_pending_button.setText(self.tr("Run OCR for Pending Pages"))
        self.run_pending_button.setToolTip(self.tr("Run OCR on all pending pages in this document"))
        self.save_button.setText(self.tr("Save"))
        self.empty_label.setText(self.tr("No image pages are available for OCR in this document."))
        page = self._current_page
        if page is not None:
            self._apply_page_status(page)
        self.viewmodel.retranslate()
        self._sync_chrome_state()

    def _connect_qml_signals(self) -> None:
        root = cast(Any, self.chrome_host.rootObject())
        if root is None:
            return
        root.firstRequested.connect(self._go_first)
        root.previousRequested.connect(self._go_previous)
        root.nextRequested.connect(self._go_next)
        root.lastRequested.connect(self._go_last)
        root.goRequested.connect(self._go_to_page_number)
        root.runCurrentRequested.connect(self._run_current)
        root.runPendingRequested.connect(self._run_pending)
        root.saveRequested.connect(self._save_current)
        root.cancelRequested.connect(self._cancel_ocr)

    def _sync_chrome_state(self) -> None:
        page = self._current_page
        page_count = len(self._state.pages) if self._state is not None else 0
        page_number = (self._current_page_index + 1) if self._current_page_index is not None else 0
        self.viewmodel.apply_values(
            has_pages=page_count > 0,
            page_number=page_number,
            page_count=page_count,
            page_status=page.status if page is not None else None,
            page_input_value=self.page_spinbox.value(),
            first_enabled=self.first_button.isEnabled(),
            previous_enabled=self.prev_button.isEnabled(),
            next_enabled=self.next_button.isEnabled(),
            last_enabled=self.last_button.isEnabled(),
            go_enabled=self.go_button.isEnabled(),
            run_current_enabled=self.run_current_button.isEnabled(),
            run_pending_enabled=self.run_pending_button.isEnabled(),
            save_enabled=self.save_button.isEnabled(),
            run_current_tooltip=self.run_current_button.toolTip(),
            run_pending_tooltip=self.run_pending_button.toolTip(),
            save_tooltip=self.save_button.toolTip(),
            message_text=self.message_label.text() if not self.message_label.isHidden() else "",
            progress_visible=not self.progress_widget.isHidden(),
            progress_text=translate_progress_label(self.progress_widget.message_label.text()),
            progress_can_cancel=not self.progress_widget.cancel_button.isHidden(),
            empty_visible=not self.empty_label.isHidden(),
        )
        self._schedule_chrome_resize()

    def _schedule_chrome_resize(self) -> None:
        self._sync_chrome_height()
        self._chrome_resize_timer.start(0)

    def _sync_chrome_height(self) -> None:
        sync_qml_host_height(self.chrome_host)
