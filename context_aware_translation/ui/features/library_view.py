from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QEvent, QPoint, Qt, Signal, Slot
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.projects import (
    CreateProjectRequest,
    ProjectSummary,
    UpdateProjectRequest,
)
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.services.projects import ProjectsService
from context_aware_translation.ui.constants import LANGUAGES
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone

_ROLE_PROJECT = Qt.ItemDataRole.UserRole + 1


class _ProjectDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        name: str = "",
        target_language: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText(self.tr("Enter project name"))
        form.addRow(self.tr("Name*:"), self.name_edit)

        self.target_language_combo = QComboBox(self)
        self.target_language_combo.setObjectName("projectTargetLanguageCombo")
        self.target_language_combo.setMinimumWidth(260)
        self.target_language_combo.addItem("")
        seen_languages: set[str] = set()
        for display_name, _internal_name in LANGUAGES:
            if display_name in seen_languages:
                continue
            seen_languages.add(display_name)
            self.target_language_combo.addItem(display_name)
        if target_language:
            index = self.target_language_combo.findText(target_language, Qt.MatchFlag.MatchFixedString)
            if index < 0:
                self.target_language_combo.addItem(target_language)
                index = self.target_language_combo.count() - 1
            self.target_language_combo.setCurrentIndex(index)
        else:
            self.target_language_combo.setCurrentIndex(0)
        form.addRow(self.tr("Target language:"), self.target_language_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_hybrid_control_theme(self)
        set_button_tone(buttons.button(QDialogButtonBox.StandardButton.Save), "primary")
        set_button_tone(buttons.button(QDialogButtonBox.StandardButton.Cancel), "ghost")

    @property
    def project_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def target_language(self) -> str | None:
        value = self.target_language_combo.currentText().strip()
        return value or None

    def _on_accept(self) -> None:
        if not self.project_name:
            QMessageBox.warning(self, self.tr("Validation Error"), self.tr("Project name is required."))
            return
        self.accept()


class LibraryView(QWidget):
    """Main projects view backed by the application service boundary."""

    book_opened = Signal(str, str)

    def __init__(self, service: ProjectsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._state: list[ProjectSummary] = []
        self._context_menu: QMenu | None = None
        self._setup_ui()
        self._connect_signals()
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        toolbar = QVBoxLayout()
        buttons_row = QDialogButtonBox(Qt.Orientation.Horizontal, self)
        self.new_button = buttons_row.addButton(self.tr("New Project"), QDialogButtonBox.ButtonRole.ActionRole)
        self.open_button = buttons_row.addButton(self.tr("Open"), QDialogButtonBox.ButtonRole.ActionRole)
        self.edit_button = buttons_row.addButton(self.tr("Edit"), QDialogButtonBox.ButtonRole.ActionRole)
        self.delete_button = buttons_row.addButton(self.tr("Delete"), QDialogButtonBox.ButtonRole.ActionRole)
        toolbar.addWidget(buttons_row)
        layout.addLayout(toolbar)

        self.table_view = QTableView()
        self.model = QStandardItemModel(0, 4, self)
        self.table_view.setModel(self.model)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(True)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.verticalHeader().setVisible(False)

        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.table_view)
        apply_hybrid_control_theme(self)
        set_button_tone(self.new_button, "primary")
        set_button_tone(self.open_button)
        set_button_tone(self.edit_button)
        set_button_tone(self.delete_button, "danger")
        self.retranslateUi()

    def _connect_signals(self) -> None:
        self.new_button.clicked.connect(self._on_new_project)
        self.open_button.clicked.connect(self._on_open_project)
        self.edit_button.clicked.connect(self._on_edit_project)
        self.delete_button.clicked.connect(self._on_delete_project)
        self.table_view.doubleClicked.connect(self._on_row_double_clicked)
        self.table_view.customContextMenuRequested.connect(self._show_context_menu)
        self.table_view.selectionModel().selectionChanged.connect(lambda *_args: self._update_button_state())

    def refresh(self) -> None:
        self._apply_state(self._service.list_projects().items)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.new_button.setText(self.tr("New Project"))
        self.open_button.setText(self.tr("Open"))
        self.edit_button.setText(self.tr("Edit"))
        self.delete_button.setText(self.tr("Delete"))
        self.model.setHorizontalHeaderLabels(
            [
                self.tr("Name"),
                self.tr("Target Language"),
                self.tr("Progress"),
                self.tr("Modified"),
            ]
        )

    def _apply_state(self, items: list[ProjectSummary]) -> None:
        self._state = list(items)
        self.model.setRowCount(0)
        for summary in items:
            row = [
                QStandardItem(summary.project.name),
                QStandardItem(summary.target_language or ""),
                QStandardItem(summary.progress_summary or ""),
                QStandardItem(self._format_timestamp(summary.modified_at)),
            ]
            for item in row:
                item.setEditable(False)
                item.setData(summary, _ROLE_PROJECT)
            self.model.appendRow(row)
        self._update_button_state()

    def _selected_project(self) -> ProjectSummary | None:
        selection = self.table_view.selectionModel()
        if selection is None or not selection.hasSelection():
            return None
        index = selection.selectedRows()[0]
        value = self.model.data(self.model.index(index.row(), 0), _ROLE_PROJECT)
        return value if isinstance(value, ProjectSummary) else None

    def _update_button_state(self) -> None:
        selected = self._selected_project() is not None
        self.open_button.setEnabled(selected)
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    @Slot()
    def _on_new_project(self) -> None:
        dialog = _ProjectDialog(title=self.tr("New Project"), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            created = self._service.create_project(
                CreateProjectRequest(name=dialog.project_name, target_language=dialog.target_language)
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("New Project"), exc.payload.message)
            return
        self.refresh()
        self.book_opened.emit(created.project.project_id, created.project.name)

    @Slot()
    def _on_open_project(self) -> None:
        summary = self._selected_project()
        if summary is None:
            QMessageBox.information(self, self.tr("No Selection"), self.tr("Please select a project to open."))
            return
        self.book_opened.emit(summary.project.project_id, summary.project.name)

    @Slot()
    def _on_edit_project(self) -> None:
        summary = self._selected_project()
        if summary is None:
            QMessageBox.information(self, self.tr("No Selection"), self.tr("Please select a project to edit."))
            return
        dialog = _ProjectDialog(
            title=self.tr("Edit Project"),
            name=summary.project.name,
            target_language=summary.target_language,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._service.update_project(
                UpdateProjectRequest(
                    project_id=summary.project.project_id,
                    name=dialog.project_name,
                    target_language=dialog.target_language,
                )
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Edit Project"), exc.payload.message)
            return
        self.refresh()

    @Slot()
    def _on_delete_project(self) -> None:
        summary = self._selected_project()
        if summary is None:
            QMessageBox.information(self, self.tr("No Selection"), self.tr("Please select a project to delete."))
            return
        reply = QMessageBox.question(
            self,
            self.tr("Confirm Deletion"),
            qarg(
                self.tr(
                    "Are you sure you want to delete project '%1'?\n\n"
                    "This will permanently remove all project data including documents, "
                    "translations, and glossary entries."
                ),
                summary.project.name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_project(summary.project.project_id, permanent=True)
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Delete Project"), exc.payload.message)
            return
        self.refresh()
        QMessageBox.information(
            self,
            self.tr("Success"),
            qarg(self.tr("Project '%1' has been deleted."), summary.project.name),
        )

    @Slot()
    def _on_row_double_clicked(self) -> None:
        self._on_open_project()

    @Slot()
    def _show_context_menu(self, position: QPoint) -> None:
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return
        self.table_view.selectRow(index.row())
        self._update_button_state()
        if self._selected_project() is None:
            return
        menu = QMenu(self)
        open_action = menu.addAction(self.tr("Open"))
        edit_action = menu.addAction(self.tr("Edit"))
        menu.addSeparator()
        delete_action = menu.addAction(self.tr("Delete"))
        open_action.triggered.connect(self._on_open_project)
        edit_action.triggered.connect(self._on_edit_project)
        delete_action.triggered.connect(self._on_delete_project)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.aboutToHide.connect(lambda: setattr(self, "_context_menu", None))
        self._context_menu = menu
        menu.popup(self.table_view.viewport().mapToGlobal(position))

    @staticmethod
    def _format_timestamp(timestamp: float | None) -> str:
        if timestamp is None:
            return ""
        dt = datetime.fromtimestamp(timestamp, tz=UTC)
        now = datetime.now(tz=UTC)
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        if dt.year == now.year:
            return dt.strftime("%m-%d")
        return dt.strftime("%Y-%m-%d")

    def _tip_text(self) -> str:
        return self.tr("Create a project, finish setup, then open it to work through the document pipeline.")
