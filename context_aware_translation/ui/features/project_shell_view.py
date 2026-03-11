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


class ProjectShellView(QWidget):
    """Top-level project shell for Work, Terms, and Setup."""

    close_requested = Signal()
    queue_requested = Signal()

    def __init__(
        self,
        project_id: str,
        project_name: str,
        *,
        work_widget: QWidget,
        terms_widget: QWidget,
        setup_widget: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.project_name = project_name
        self.work_tab = work_widget
        self.terms_tab = terms_widget
        self.setup_tab = setup_widget
        self._init_ui()

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
        self.tab_widget.addTab(self.work_tab, self.tr("Work"))
        self.tab_widget.addTab(self.terms_tab, self.tr("Terms"))
        self.tab_widget.addTab(self.setup_tab, self.tr("Setup"))
        layout.addWidget(self.tab_widget)

    def get_running_operations(self) -> list[str]:
        running = self.work_tab.get_running_operations()
        return running if isinstance(running, list) else []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        self.work_tab.request_cancel_running_operations(include_engine_tasks=include_engine_tasks)

    def cleanup(self) -> None:
        self.work_tab.cleanup()
        self.terms_tab.cleanup()
        self.setup_tab.cleanup()

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
        return qarg(self.tr("Project shell for %1."), self.project_name)
