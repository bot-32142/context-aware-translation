from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import ProjectRef
from context_aware_translation.application.contracts.projects import (
    CreateProjectRequest,
    ProjectsScreenState,
    ProjectSummary,
    UpdateProjectRequest,
)
from tests.application.fakes import FakeProjectsService

try:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from context_aware_translation.ui.features.library_view import LibraryView, _ProjectDialog

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _projects_service() -> FakeProjectsService:
    summary = ProjectSummary(
        project=ProjectRef(project_id="project-1", name="One Piece"),
        target_language="English",
        progress_summary="25.0% (5/20)",
        modified_at=1_700_000_000.0,
    )
    return FakeProjectsService(
        list_state=ProjectsScreenState(items=[summary]),
        project_summary=summary,
        create_result=summary,
        update_result=summary,
    )


def test_library_view_renders_projects_from_service() -> None:
    service = _projects_service()
    view = LibraryView(service)
    try:
        assert service.calls[0][0] == "list_projects"
        assert view.model.rowCount() == 1
        assert view.model.item(0, 0).text() == "One Piece"
        assert not view.open_button.isEnabled()
        view.table_view.selectRow(0)
        QApplication.processEvents()
        assert view.open_button.isEnabled()
    finally:
        view.close()
        view.deleteLater()
        QApplication.processEvents()


def test_library_view_runs_create_edit_and_delete_through_service() -> None:
    service = _projects_service()
    view = LibraryView(service)
    try:

        class _FakeCreateDialog:
            def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
                pass

            def exec(self) -> int:
                return 1

            @property
            def project_name(self) -> str:
                return "New Project"

            @property
            def target_language(self) -> str:
                return "Chinese"

        with patch("context_aware_translation.ui.features.library_view._ProjectDialog", _FakeCreateDialog):
            emitted: list[tuple[str, str]] = []
            view.book_opened.connect(lambda project_id, name: emitted.append((project_id, name)))
            view._on_new_project()
        assert any(
            name == "create_project" and payload == CreateProjectRequest(name="New Project", target_language="Chinese")
            for name, payload in service.calls
        )
        assert emitted == [("project-1", "One Piece")]

        view.table_view.selectRow(0)
        QApplication.processEvents()

        class _FakeEditDialog:
            def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
                pass

            def exec(self) -> int:
                return 1

            @property
            def project_name(self) -> str:
                return "Edited Project"

            @property
            def target_language(self) -> str:
                return "Japanese"

        with patch("context_aware_translation.ui.features.library_view._ProjectDialog", _FakeEditDialog):
            view._on_edit_project()
        assert any(
            name == "update_project"
            and payload
            == UpdateProjectRequest(project_id="project-1", name="Edited Project", target_language="Japanese")
            for name, payload in service.calls
        )

        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(QMessageBox, "information"),
        ):
            view.table_view.selectRow(0)
            QApplication.processEvents()
            view._on_delete_project()
        assert ("delete_project", ("project-1", True)) in service.calls
    finally:
        view.close()
        view.deleteLater()
        QApplication.processEvents()


def test_library_view_context_menu_selects_clicked_row() -> None:
    service = _projects_service()
    service.list_state = ProjectsScreenState(
        items=[
            ProjectSummary(project=ProjectRef(project_id="p1", name="row-0")),
            ProjectSummary(project=ProjectRef(project_id="p2", name="row-1")),
            ProjectSummary(project=ProjectRef(project_id="p3", name="row-2")),
        ]
    )
    view = LibraryView(service)
    try:
        view.table_view.selectRow(0)
        QApplication.processEvents()
        target_index = view.model.index(2, 0)
        assert target_index.isValid()
        target_position = view.table_view.visualRect(target_index).center()
        with patch("context_aware_translation.ui.features.library_view.QMenu.popup", return_value=None):
            view._show_context_menu(target_position)
        assert view.table_view.selectionModel().selectedRows()[0].row() == 2
    finally:
        view.close()
        view.deleteLater()
        QApplication.processEvents()


def test_project_dialog_uses_dropdown_for_target_language() -> None:
    dialog = _ProjectDialog(title="New Project", target_language="English")
    try:
        assert dialog.target_language_combo.objectName() == "projectTargetLanguageCombo"
        assert dialog.target_language_combo.currentText() == "English"
        dialog.target_language_combo.setCurrentIndex(0)
        assert dialog.target_language is None
    finally:
        dialog.close()
        dialog.deleteLater()
        QApplication.processEvents()
