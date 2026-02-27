"""Book workspace view for working with an open book."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from context_aware_translation.ui.tasks.qt_task_engine import TaskEngine

from context_aware_translation.storage.book_manager import BookManager

from ..i18n import qarg
from ..utils import create_tip_label
from .export_view import ExportView
from .glossary_view import GlossaryView
from .import_view import ImportView
from .ocr_review_view import OCRReviewView
from .reembedding_view import ReembeddingView
from .translation_view import TranslationView

logger = logging.getLogger(__name__)


class BookWorkspace(QWidget):
    """Container view for working with an open book."""

    _TOKEN_REFRESH_INTERVAL_MS = 1500
    TRANSLATION_TAB_INDEX = 3

    close_requested = Signal()

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        book_name: str,
        task_engine: "TaskEngine",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self.book_id = book_id
        self.book_name = book_name
        self._task_engine = task_engine
        self._cleaned_up = False

        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        self._activity_panel_min_width = 260
        self._activity_panel_default_width = 460
        self._activity_panel_last_width = self._activity_panel_default_width

        # Header with book name and close button
        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"<h2>{self.book_name}</h2>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.close_btn = QPushButton("\u2190 " + self.tr("Back to Library"))
        self.close_btn.setToolTip(self.tr("Close this book and return to library"))
        self.close_btn.clicked.connect(self._on_close_requested)
        header_layout.addWidget(self.close_btn)

        self.activity_btn = QPushButton(self.tr("Activity"))
        self.activity_btn.setToolTip(self.tr("Show/hide task activity panel"))
        self.activity_btn.setCheckable(True)
        self.activity_btn.clicked.connect(self._on_activity_toggled)
        header_layout.addWidget(self.activity_btn)

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
        # Let splitter negotiation own horizontal sizing; prevents tabs from
        # pinning the activity panel in narrow windows.
        self.tab_widget.setMinimumWidth(0)
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Add tabs (before connecting signal to avoid premature triggers)
        self._add_tab(self.tr("Import"), self._create_import_view)
        self._add_tab(self.tr("OCR Review"), self._create_ocr_review_view)
        self._add_tab(self.tr("Glossary"), self._create_glossary_view)
        self._add_tab(self.tr("Translate"), self._create_translation_view)
        self._add_tab(self.tr("Reembedding"), self._create_reembedding_view)
        self._add_tab(self.tr("Export"), self._create_export_view)

        # Connect signal after tabs are added
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # Activity panel (right-side collapsible, hidden by default)
        from ..widgets.task_activity_panel import TaskActivityPanel

        self._activity_panel = TaskActivityPanel(self._task_engine, self.book_id)
        self._activity_panel.close_requested.connect(self._on_activity_panel_close)
        self._activity_panel.setMinimumWidth(self._activity_panel_min_width)
        self._activity_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._activity_panel.setVisible(False)

        # Splitter holds tab widget + activity panel
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.addWidget(self.tab_widget)
        self._main_splitter.addWidget(self._activity_panel)
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 1)
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.setCollapsible(0, False)
        self._main_splitter.setCollapsible(1, False)
        self._main_splitter.splitterMoved.connect(self._on_splitter_moved)
        self._main_splitter.setSizes([1, 0])
        self._main_splitter.setHandleWidth(6)
        # Style the handle widget directly to avoid stylesheet cascading to children
        handle = self._main_splitter.handle(1)
        if handle is not None:
            handle.setStyleSheet("""
                background-color: #d0d0d0;
                border-radius: 2px;
                margin: 4px 0;
            """)

        layout.addWidget(self._main_splitter)

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
        return ImportView(self.book_manager, self.book_id, task_engine=self._task_engine)

    def _create_ocr_review_view(self) -> QWidget:
        """Create the OCR review view."""
        view = OCRReviewView(self.book_manager, self.book_id, task_engine=self._task_engine)
        view.open_activity_requested.connect(self.show_activity_panel)
        return view

    def _create_glossary_view(self) -> QWidget:
        """Create the glossary view."""
        view = GlossaryView(self.book_manager, self.book_id, self._task_engine)
        view.open_activity_requested.connect(self.show_activity_panel)
        return view

    def _create_translation_view(self) -> QWidget:
        """Create the translation view."""
        view = TranslationView(self.book_manager, self.book_id, task_engine=self._task_engine)
        view.open_activity_requested.connect(self.show_activity_panel)
        return view

    def _create_reembedding_view(self) -> QWidget:
        """Create the reembedding review view."""
        view = ReembeddingView(self.book_manager, self.book_id, task_engine=self._task_engine)
        view.open_activity_requested.connect(self.show_activity_panel)
        return view

    def _create_export_view(self) -> QWidget:
        """Create the export view."""
        return ExportView(self.book_manager, self.book_id, task_engine=self._task_engine)

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

    # ------------------------------------------------------------------
    # Activity panel public API
    # ------------------------------------------------------------------

    def show_activity_panel(self) -> None:
        """Show the activity panel (callable by child views)."""
        self._activity_panel.setMinimumWidth(self._activity_panel_min_width)
        self._activity_panel.setVisible(True)
        self.activity_btn.setChecked(True)
        self._activity_panel.refresh()
        self._restore_activity_panel_width()
        # Re-apply once after layout settles to avoid first-open zero-size races.
        QTimer.singleShot(0, self._restore_activity_panel_width)
        QTimer.singleShot(50, self._restore_activity_panel_width)

    def hide_activity_panel(self) -> None:
        """Hide the activity panel."""
        sizes = self._main_splitter.sizes()
        if len(sizes) >= 2 and sizes[1] > 0:
            self._activity_panel_last_width = max(self._activity_panel_min_width, sizes[1])
        # Allow full collapse while hidden even though splitter children are non-collapsible.
        self._activity_panel.setMinimumWidth(0)
        self._activity_panel.setVisible(False)
        if len(sizes) >= 2:
            self._main_splitter.setSizes([sizes[0] + sizes[1], 0])
        self.activity_btn.setChecked(False)

    # ------------------------------------------------------------------
    # Activity panel slots
    # ------------------------------------------------------------------

    def _on_activity_toggled(self, checked: bool) -> None:
        if checked:
            self.show_activity_panel()
        else:
            self.hide_activity_panel()

    def _on_activity_panel_close(self) -> None:
        self.hide_activity_panel()

    def _restore_activity_panel_width(self) -> None:
        """Restore panel to a usable non-zero width when opening."""
        sizes = self._main_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            total = self._main_splitter.width()
        if total <= 0:
            total = self.width()
        if total <= 0:
            return

        min_main_width = 200
        min_panel_floor = 120
        min_panel_width = min(self._activity_panel_min_width, max(min_panel_floor, total - min_main_width))
        self._activity_panel.setMinimumWidth(min_panel_width)

        max_panel_width = max(min_panel_width, total - min_main_width)
        panel_width = max(min_panel_width, min(self._activity_panel_last_width, max_panel_width))
        main_width = max(1, total - panel_width)

        self._main_splitter.setSizes([main_width, panel_width])

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """Persist panel width while user drags the splitter handle."""
        if self._activity_panel.isVisible():
            sizes = self._main_splitter.sizes()
            if len(sizes) >= 2 and sizes[1] > 0:
                self._activity_panel_last_width = max(self._activity_panel_min_width, sizes[1])

    def get_translation_view(self) -> TranslationView | None:
        """Return the translation view if it has been created, else None."""
        view = self._view_cache.get(self.TRANSLATION_TAB_INDEX)
        return view if isinstance(view, TranslationView) else None

    def get_running_operations(self) -> list[str]:
        """Return human-readable names of running operations in this workspace."""
        running: list[str] = []

        # Import tab (index 0)
        import_view = self._view_cache.get(0)
        if import_view is not None and self._is_worker_running(getattr(import_view, "worker", None)):
            running.append(self.tr("Import"))

        from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES

        # OCR Review tab (index 1) — now engine-managed
        ocr_tasks = self._task_engine.get_tasks(self.book_id, task_type="ocr")
        if any(t.status not in TERMINAL_TASK_STATUSES for t in ocr_tasks):
            running.append(self.tr("OCR"))

        # Glossary tab (index 2) — engine-managed tasks
        glossary_running = False

        for task_type in ("glossary_extraction", "glossary_translation", "glossary_review", "glossary_export"):
            for rec in self._task_engine.get_tasks(self.book_id, task_type=task_type):
                if rec.status not in TERMINAL_TASK_STATUSES:
                    glossary_running = True
                    break
            if glossary_running:
                break
        if glossary_running:
            running.append(self.tr("Glossary"))

        # Translation tab (index 3) — engine-managed translation tasks are background-capable.
        # Intentionally exclude them from leave-book warnings.

        # Reembedding tab (index 4) — engine-managed
        reembed_tasks = self._task_engine.get_tasks(self.book_id, task_type="image_reembedding")
        if any(t.status not in TERMINAL_TASK_STATUSES for t in reembed_tasks):
            running.append(self.tr("Reembedding"))

        # Export tab (index 5)
        export_view = self._view_cache.get(5)
        if export_view is not None and self._is_worker_running(getattr(export_view, "worker", None)):
            running.append(self.tr("Export"))

        return running

    def is_translation_running(self) -> bool:
        """Backward-compatible helper for legacy translation-only checks."""
        running = self.get_running_operations()
        return self.tr("Translation") in running

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = True) -> None:
        """Request cancellation for currently running workers in this workspace.

        Args:
            include_engine_tasks: When True, also request cancellation for engine-managed
                task workers. Leave-book flow passes False so background tasks continue.
        """
        if include_engine_tasks:
            self._task_engine.cancel_running_tasks(self.book_id)

        # Import tab (index 0)
        import_view = self._view_cache.get(0)
        if import_view is not None:
            self._request_worker_interruption(getattr(import_view, "worker", None))

        # OCR Review tab (index 1) — engine-managed, covered by cancel_running_tasks above

        # Translation tab (index 3) — sync/chunk tasks are cancelled via engine above

        # Reembedding tab (index 4) — engine-managed, covered by cancel_running_tasks above

        # Export tab (index 5)
        export_view = self._view_cache.get(5)
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
                        "Returning to the library will stop local processing.\n\n"
                        "Submitted async batch tasks will continue at the provider and can be resumed later.\n\n"
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
        if hasattr(self, "_activity_panel"):
            self._activity_panel.cleanup()
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
        self.activity_btn.setText(self.tr("Activity"))
        self.activity_btn.setToolTip(self.tr("Show/hide task activity panel"))
        self.tip_label.setText(self._workflow_tip_text())
        self.token_usage_label.setToolTip(self._token_usage_tooltip())
        self.tab_widget.setTabText(0, self.tr("Import"))
        self.tab_widget.setTabText(1, self.tr("OCR Review"))
        self.tab_widget.setTabText(2, self.tr("Glossary"))
        self.tab_widget.setTabText(3, self.tr("Translate"))
        self.tab_widget.setTabText(4, self.tr("Reembedding"))
        self.tab_widget.setTabText(5, self.tr("Export"))
        self._refresh_token_usage()

    def _workflow_tip_text(self) -> str:
        return self.tr(
            "Suggested flow: Import \u2192 OCR Review (if needed) \u2192 Glossary (optional) \u2192 Translate \u2192 Reembedding (if needed) \u2192 Export."
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
