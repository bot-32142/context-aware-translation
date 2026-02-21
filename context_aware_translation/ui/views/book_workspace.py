"""Book workspace view for working with an open book."""

import logging
from collections.abc import Callable

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.storage.book_manager import BookManager

from ..i18n import qarg
from ..utils import create_tip_label
from .export_view import ExportView
from .glossary_view import GlossaryView
from .import_view import ImportView
from .ocr_review_view import OCRReviewView
from .translation_view import TranslationView

logger = logging.getLogger(__name__)


class BookWorkspace(QWidget):
    """Container view for working with an open book."""

    _TOKEN_REFRESH_INTERVAL_MS = 1500

    close_requested = Signal()

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        book_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self.book_id = book_id
        self.book_name = book_name
        self._cleaned_up = False

        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the user interface."""
        layout = QVBoxLayout(self)

        # Header with book name and close button
        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"<h2>{self.book_name}</h2>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.close_btn = QPushButton("\u2190 " + self.tr("Back to Library"))
        self.close_btn.setToolTip(self.tr("Close this book and return to library"))
        self.close_btn.clicked.connect(self._on_close_requested)
        header_layout.addWidget(self.close_btn)

        layout.addLayout(header_layout)

        # Workflow guidance
        self.tip_label = create_tip_label(self._workflow_tip_text())
        layout.addWidget(self.tip_label)

        # Live token usage summary (aggregated across endpoint profiles)
        self.token_usage_label = QLabel()
        self.token_usage_label.setStyleSheet("color: #666666;")
        self.token_usage_label.setWordWrap(True)
        self.token_usage_label.setToolTip(self._token_usage_tooltip())
        layout.addWidget(self.token_usage_label)

        # Cache for created views (must be initialized before adding tabs)
        self._view_cache: dict[int, QWidget] = {}

        # Factory mapping: tab index -> factory callable
        self._tab_factories: dict[int, Callable[[], QWidget]] = {}

        # Tab widget for different views
        self.tab_widget = QTabWidget()

        # Add tabs (before connecting signal to avoid premature triggers)
        self._add_tab(self.tr("Import"), self._create_import_view)
        self._add_tab(self.tr("OCR Review"), self._create_ocr_review_view)
        self._add_tab(self.tr("Glossary"), self._create_glossary_view)
        self._add_tab(self.tr("Translate"), self._create_translation_view)
        self._add_tab(self.tr("Export"), self._create_export_view)

        # Connect signal after tabs are added
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.tab_widget)

        # Initialize the first tab immediately
        self._on_tab_changed(0)

        # Refresh token usage periodically so active jobs are visible in-place.
        self._token_timer = QTimer(self)
        self._token_timer.setInterval(self._TOKEN_REFRESH_INTERVAL_MS)
        self._token_timer.timeout.connect(self._refresh_token_usage)
        self._token_timer.start()
        self._refresh_token_usage()

    def _add_tab(self, title: str, factory: Callable[..., QWidget]) -> None:
        """Add a tab with lazy initialization."""
        # Add placeholder initially
        placeholder = QWidget()
        tab_index = self.tab_widget.addTab(placeholder, title)
        # Store factory in our own dict
        self._tab_factories[tab_index] = factory

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change - create view if not yet created, or refresh if cached."""
        if index in self._view_cache:
            # Refresh cached view to ensure data is up-to-date
            view = self._view_cache[index]
            if hasattr(view, "refresh"):
                view.refresh()
            return

        factory = self._tab_factories.get(index)

        if factory:
            # Save tab text before removing
            tab_text = self.tab_widget.tabText(index)
            # Block signals to prevent recursion during tab swap
            self.tab_widget.blockSignals(True)
            try:
                # Create the actual view
                view = factory()
                self._view_cache[index] = view
                # Replace the placeholder
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, view, tab_text)
                self.tab_widget.setCurrentIndex(index)
            finally:
                self.tab_widget.blockSignals(False)

    def _create_import_view(self) -> QWidget:
        """Create the import view."""
        return ImportView(self.book_manager, self.book_id)

    def _create_ocr_review_view(self) -> QWidget:
        """Create the OCR review view."""
        return OCRReviewView(self.book_manager, self.book_id)

    def _create_glossary_view(self) -> QWidget:
        """Create the glossary view."""
        return GlossaryView(self.book_manager, self.book_id)

    def _create_translation_view(self) -> QWidget:
        """Create the translation view."""
        return TranslationView(self.book_manager, self.book_id)

    def _create_export_view(self) -> QWidget:
        """Create the export view."""
        return ExportView(self.book_manager, self.book_id)

    @staticmethod
    def _is_worker_running(worker: object | None) -> bool:
        """Return True if worker exists and is currently running."""
        return bool(worker is not None and hasattr(worker, "isRunning") and worker.isRunning())

    @staticmethod
    def _request_worker_interruption(worker: object | None) -> None:
        """Request interruption for a running worker, if supported."""
        if (
            worker is not None
            and hasattr(worker, "isRunning")
            and worker.isRunning()
            and hasattr(worker, "requestInterruption")
        ):
            worker.requestInterruption()

    def get_running_operations(self) -> list[str]:
        """Return human-readable names of running operations in this workspace."""
        running: list[str] = []

        # Import tab (index 0)
        import_view = self._view_cache.get(0)
        if import_view is not None and self._is_worker_running(getattr(import_view, "worker", None)):
            running.append(self.tr("Import"))

        # OCR Review tab (index 1)
        ocr_view = self._view_cache.get(1)
        if ocr_view is not None and self._is_worker_running(getattr(ocr_view, "ocr_worker", None)):
            running.append(self.tr("OCR"))

        # Glossary tab (index 2)
        glossary_view = self._view_cache.get(2)
        if glossary_view is not None and (
            self._is_worker_running(getattr(glossary_view, "_build_worker", None))
            or self._is_worker_running(getattr(glossary_view, "_translate_worker", None))
            or self._is_worker_running(getattr(glossary_view, "_review_worker", None))
        ):
            running.append(self.tr("Glossary"))

        # Translation tab (index 3)
        translation_view = self._view_cache.get(3)
        if translation_view is not None and self._is_worker_running(getattr(translation_view, "worker", None)):
            running.append(self.tr("Translation"))

        # Export tab (index 4)
        export_view = self._view_cache.get(4)
        if export_view is not None and self._is_worker_running(getattr(export_view, "worker", None)):
            running.append(self.tr("Export"))

        return running

    def is_translation_running(self) -> bool:
        """Backward-compatible helper for legacy translation-only checks."""
        running = self.get_running_operations()
        return self.tr("Translation") in running

    def request_cancel_running_operations(self) -> None:
        """Request cancellation for all currently running background workers."""
        # Import tab (index 0)
        import_view = self._view_cache.get(0)
        if import_view is not None:
            self._request_worker_interruption(getattr(import_view, "worker", None))

        # OCR Review tab (index 1)
        ocr_view = self._view_cache.get(1)
        if ocr_view is not None:
            self._request_worker_interruption(getattr(ocr_view, "ocr_worker", None))

        # Glossary tab (index 2)
        glossary_view = self._view_cache.get(2)
        if glossary_view is not None:
            self._request_worker_interruption(getattr(glossary_view, "_build_worker", None))
            self._request_worker_interruption(getattr(glossary_view, "_translate_worker", None))
            self._request_worker_interruption(getattr(glossary_view, "_review_worker", None))
            self._request_worker_interruption(getattr(glossary_view, "_export_worker", None))

        # Translation tab (index 3)
        translation_view = self._view_cache.get(3)
        if translation_view is not None:
            self._request_worker_interruption(getattr(translation_view, "worker", None))

        # Export tab (index 4)
        export_view = self._view_cache.get(4)
        if export_view is not None:
            self._request_worker_interruption(getattr(export_view, "worker", None))

    def _on_close_requested(self) -> None:
        """Handle close button click, warning if any operation is in progress."""
        running_operations = self.get_running_operations()
        if running_operations:
            operations_text = ", ".join(running_operations)
            result = QMessageBox.warning(
                self,
                self.tr("Operation in Progress"),
                qarg(
                    self.tr(
                        "The following operations are currently running: %1.\n\n"
                        "Returning to the library will cancel them.\n\n"
                        "All completed results are already saved and won't be lost."
                    ),
                    operations_text,
                ),
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if result != QMessageBox.StandardButton.Ok:
                return
        self.close_requested.emit()

    def refresh(self) -> None:
        """Refresh the current tab's view."""
        current_index = self.tab_widget.currentIndex()
        if current_index in self._view_cache:
            view = self._view_cache[current_index]
            if hasattr(view, "refresh"):
                view.refresh()
        self._refresh_token_usage()

    def cleanup(self) -> None:
        """Clean up cached tab views and their resources."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        if hasattr(self, "_token_timer"):
            self._token_timer.stop()
        for view in self._view_cache.values():
            if hasattr(view, "cleanup"):
                view.cleanup()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        """Handle widget close to release resources."""
        self.cleanup()
        super().closeEvent(event)

    def retranslateUi(self) -> None:
        self.title_label.setText(f"<h2>{self.book_name}</h2>")
        self.close_btn.setText("\u2190 " + self.tr("Back to Library"))
        self.close_btn.setToolTip(self.tr("Close this book and return to library"))
        self.tip_label.setText(self._workflow_tip_text())
        self.token_usage_label.setToolTip(self._token_usage_tooltip())
        self.tab_widget.setTabText(0, self.tr("Import"))
        self.tab_widget.setTabText(1, self.tr("OCR Review"))
        self.tab_widget.setTabText(2, self.tr("Glossary"))
        self.tab_widget.setTabText(3, self.tr("Translate"))
        self.tab_widget.setTabText(4, self.tr("Export"))
        self._refresh_token_usage()

    def _workflow_tip_text(self) -> str:
        return self.tr(
            "Suggested flow: Import \u2192 OCR Review (if needed) \u2192 Glossary (optional) \u2192 Translate \u2192 Export."
        )

    def _token_usage_tooltip(self) -> str:
        return self.tr("Live aggregate token usage across all endpoint profiles.")

    def _build_token_usage_summary(self, profiles: list[object]) -> str:
        """Format aggregate token usage text for the workspace header."""
        total_tokens = 0
        input_tokens = 0
        cached_input_tokens = 0
        uncached_input_tokens = 0
        output_tokens = 0
        active_endpoints = 0

        for profile in profiles:
            tokens_used = int(getattr(profile, "tokens_used", 0) or 0)
            input_used = int(getattr(profile, "input_tokens_used", 0) or 0)
            cached_used = int(getattr(profile, "cached_input_tokens_used", 0) or 0)
            uncached_used = int(getattr(profile, "uncached_input_tokens_used", 0) or 0)
            output_used = int(getattr(profile, "output_tokens_used", 0) or 0)

            total_tokens += max(tokens_used, 0)
            input_tokens += max(input_used, 0)
            cached_input_tokens += max(cached_used, 0)
            uncached_input_tokens += max(uncached_used, 0)
            output_tokens += max(output_used, 0)
            if tokens_used > 0:
                active_endpoints += 1

        return qarg(
            self.tr("Token usage: Total %1 | Input %2 (cached %3 / uncached %4) | Output %5 | Active endpoints %6"),
            f"{total_tokens:,}",
            f"{input_tokens:,}",
            f"{cached_input_tokens:,}",
            f"{uncached_input_tokens:,}",
            f"{output_tokens:,}",
            active_endpoints,
        )

    def _refresh_token_usage(self) -> None:
        """Refresh live token usage summary from registry."""
        if not hasattr(self, "token_usage_label"):
            return
        try:
            profiles = self.book_manager.list_endpoint_profiles()
            self.token_usage_label.setText(self._build_token_usage_summary(list(profiles)))
        except Exception:
            logger.exception("Failed to refresh token usage summary")
            self.token_usage_label.setText(self.tr("Token usage unavailable"))
