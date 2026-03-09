from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.utils import create_tip_label


class _PlaceholderTab(QWidget):
    def __init__(self, title: str, description: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        heading = QLabel(f"<h3>{title}</h3>")
        heading.setTextFormat(heading.textFormat())
        body = QLabel(description)
        body.setWordWrap(True)
        body.setStyleSheet("color: #666666;")
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch()


class ProjectShellView(QWidget):
    """Top-level project shell for Work, Terms, and Setup.

    Task 10 only establishes the shell and navigation targets. Individual tabs
    can host placeholders until later feature tasks attach real content.
    """

    close_requested = Signal()
    queue_requested = Signal()

    def __init__(
        self,
        project_id: str,
        project_name: str,
        *,
        work_widget: QWidget | None = None,
        terms_widget: QWidget | None = None,
        setup_widget: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.project_name = project_name
        self._work_widget = work_widget
        self._terms_widget = terms_widget
        self._setup_widget = setup_widget
        self._init_ui()

    @property
    def work_widget(self) -> QWidget | None:
        return self._work_widget

    @property
    def terms_widget(self) -> QWidget | None:
        return self._terms_widget

    @property
    def setup_widget(self) -> QWidget | None:
        return self._setup_widget

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"<h2>{self.project_name}</h2>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.queue_button = QPushButton(self.tr("Queue"))
        self.queue_button.setToolTip(self.tr("Open the queue drawer."))
        self.queue_button.clicked.connect(self.queue_requested.emit)
        header_layout.addWidget(self.queue_button)

        self.back_button = QPushButton("\u2190 " + self.tr("Back to Projects"))
        self.back_button.setToolTip(self.tr("Close this project and return to Projects."))
        self.back_button.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(self.back_button)
        layout.addLayout(header_layout)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        self.tab_widget = QTabWidget()
        self.work_tab = self._work_widget or _PlaceholderTab(
            self.tr("Work"),
            self.tr("The new Work home will replace the legacy workspace in a later migration task."),
        )
        self.terms_tab = self._terms_widget or _PlaceholderTab(
            self.tr("Terms"),
            self.tr("The shared Terms surface will be attached here by the Terms migration task."),
        )
        self.setup_tab = self._setup_widget or _PlaceholderTab(
            self.tr("Setup"),
            self.tr("Project-specific setup will be attached here by the Setup migration task."),
        )
        self.tab_widget.addTab(self.work_tab, self.tr("Work"))
        self.tab_widget.addTab(self.terms_tab, self.tr("Terms"))
        self.tab_widget.addTab(self.setup_tab, self.tr("Setup"))
        layout.addWidget(self.tab_widget)

    def get_running_operations(self) -> list[str]:
        if self._work_widget is not None and hasattr(self._work_widget, "get_running_operations"):
            running = self._work_widget.get_running_operations()
            if isinstance(running, list):
                return running
        return []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        if self._work_widget is not None and hasattr(self._work_widget, "request_cancel_running_operations"):
            self._work_widget.request_cancel_running_operations(include_engine_tasks=include_engine_tasks)

    def cleanup(self) -> None:
        for child in (self._work_widget, self._terms_widget, self._setup_widget):
            if child is not None and hasattr(child, "cleanup"):
                child.cleanup()

    def show_work(self) -> None:
        self.tab_widget.setCurrentIndex(0)

    def show_terms(self) -> None:
        self.tab_widget.setCurrentIndex(1)

    def show_setup(self) -> None:
        self.tab_widget.setCurrentIndex(2)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.title_label.setText(f"<h2>{self.project_name}</h2>")
        self.queue_button.setText(self.tr("Queue"))
        self.queue_button.setToolTip(self.tr("Open the queue drawer."))
        self.back_button.setText("\u2190 " + self.tr("Back to Projects"))
        self.back_button.setToolTip(self.tr("Close this project and return to Projects."))
        self.tip_label.setText(self._tip_text())
        self.tab_widget.setTabText(0, self.tr("Work"))
        self.tab_widget.setTabText(1, self.tr("Terms"))
        self.tab_widget.setTabText(2, self.tr("Setup"))

    def _tip_text(self) -> str:
        terms_attached = self._terms_widget is not None
        setup_attached = self._setup_widget is not None
        if terms_attached and setup_attached:
            return qarg(self.tr("Project shell for %1."), self.project_name)
        if setup_attached:
            return qarg(
                self.tr("Project shell for %1. Work and Setup are available now; Terms will attach in a later migration task."),
                self.project_name,
            )
        if terms_attached:
            return qarg(
                self.tr("Project shell for %1. Work and Terms are available now; Setup will attach in a later migration task."),
                self.project_name,
            )
        return qarg(
            self.tr("Project shell for %1. Work is available now; Terms and Setup will attach in later migration tasks."),
            self.project_name,
        )
