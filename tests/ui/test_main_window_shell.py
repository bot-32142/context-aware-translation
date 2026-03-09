"""Tests for the Task 10 app shell migration."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.application.events import (
    InMemoryApplicationEventBus,
    ProjectsInvalidatedEvent,
    SetupInvalidatedEvent,
)
from tests.application.fakes import FakeAppSetupService

try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication, QWidget

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _FakeTaskEngine(QObject):
    tasks_changed = Signal(str)
    error_occurred = Signal(str)
    running_work_changed = Signal(bool)
    enqueue_task_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._has_running_work = False
        self.start_autorun_calls = 0
        self.close_calls = 0

    def has_running_work(self) -> bool:
        return self._has_running_work

    def start_autorun(self, interval_ms: int = 3000) -> None:  # noqa: ARG002
        self.start_autorun_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _FakeProjectsView(QWidget):
    book_opened = Signal(str, str)

    def __init__(self, _book_manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.refresh_calls = 0

    def refresh(self) -> None:
        self.refresh_calls += 1


class _FakeAppSetupView(QWidget):
    def __init__(self, _service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.refresh_calls = 0

    def refresh(self) -> None:
        self.refresh_calls += 1


class _FakeBookWorkspace(QWidget):
    close_requested = Signal()

    def __init__(
        self,
        _book_manager,
        book_id: str,
        book_name: str,
        task_engine,
        *,
        embedded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.book_id = book_id
        self.book_name = book_name
        self.task_engine = task_engine
        self.embedded = embedded
        self.running_operations: list[str] = []
        self.cancel_requests: list[bool] = []
        self.cleanup_calls = 0

    def get_running_operations(self) -> list[str]:
        return list(self.running_operations)

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        self.cancel_requests.append(include_engine_tasks)

    def cleanup(self) -> None:
        self.cleanup_calls += 1


class _FakeProjectSetupView(QWidget):
    open_app_setup_requested = Signal()
    save_completed = Signal(str)

    def __init__(self, project_id, service, events, parent: QWidget | None = None):  # noqa: ANN001
        super().__init__(parent)
        self.project_id = project_id
        self.service = service
        self.events = events
        self.cleanup_calls = 0

    def cleanup(self) -> None:
        self.cleanup_calls += 1


def _make_context():
    book_manager = MagicMock()
    book_manager.library_root = Path("/tmp/context-aware-translation-tests")
    task_store = MagicMock()
    task_engine = _FakeTaskEngine()
    app_setup_service = FakeAppSetupService(state=MagicMock())
    return SimpleNamespace(
        runtime=SimpleNamespace(
            book_manager=book_manager,
            task_store=task_store,
            task_engine=task_engine,
            worker_deps=object(),
        ),
        services=SimpleNamespace(app_setup=app_setup_service, project_setup=MagicMock()),
        events=InMemoryApplicationEventBus(),
    )


def _make_window():
    from context_aware_translation.ui.main_window import MainWindow

    context = _make_context()
    patch_stack = ExitStack()
    patch_stack.enter_context(
        patch("context_aware_translation.ui.main_window.build_application_context", return_value=context)
    )
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.LibraryView", _FakeProjectsView))
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.AppSetupView", _FakeAppSetupView))
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.BookWorkspace", _FakeBookWorkspace))
    patch_stack.enter_context(
        patch("context_aware_translation.ui.main_window.ProjectSetupView", _FakeProjectSetupView)
    )
    try:
        window = MainWindow()
    except Exception:
        patch_stack.close()
        raise
    return window, context, patch_stack


def test_project_shell_view_delegates_to_work_widget():
    from context_aware_translation.ui.features.project_shell_view import ProjectShellView

    work_widget = _FakeBookWorkspace(None, "project-1", "One Piece", task_engine=None, embedded=True)
    work_widget.running_operations = ["Translation"]

    queue_calls: list[bool] = []
    close_calls: list[bool] = []
    shell = ProjectShellView("project-1", "One Piece", work_widget=work_widget)
    shell.queue_requested.connect(lambda: queue_calls.append(True))
    shell.close_requested.connect(lambda: close_calls.append(True))

    assert shell.tab_widget.tabText(0) == shell.tr("Work")
    assert shell.tab_widget.tabText(1) == shell.tr("Terms")
    assert shell.tab_widget.tabText(2) == shell.tr("Setup")
    assert shell.get_running_operations() == ["Translation"]

    shell.queue_button.click()
    shell.back_button.click()
    shell.request_cancel_running_operations(include_engine_tasks=True)
    shell.cleanup()

    assert queue_calls == [True]
    assert close_calls == [True]
    assert work_widget.cancel_requests == [True]
    assert work_widget.cleanup_calls == 1


def test_main_window_routes_projects_into_project_shell():
    window, context, patch_stack = _make_window()
    try:
        assert window._library_nav_item.text() == window.tr("Projects")
        assert window._profiles_nav_item.text() == window.tr("App Setup")
        assert context.runtime.task_engine.start_autorun_calls == 1

        window.open_project("project-1", "One Piece")

        shell = window._view_registry["project_project-1"]
        assert shell is window._stack.currentWidget()
        assert shell.tab_widget.tabText(0) == shell.tr("Work")
        assert shell.tab_widget.tabText(1) == shell.tr("Terms")
        assert shell.tab_widget.tabText(2) == shell.tr("Setup")
        assert shell.work_tab.embedded is True
        assert isinstance(shell.setup_tab, _FakeProjectSetupView)
        assert window._book_nav_item.text() == window.tr("Project: One Piece")

        shell.queue_button.click()
        assert "Queue drawer" in window.statusBar().currentMessage()

        shell.setup_tab.open_app_setup_requested.emit()
        assert window._stack.currentWidget() is window.app_setup_view

        shell.setup_tab.save_completed.emit("project-1")
        assert shell.tab_widget.currentWidget() is shell.work_tab
        assert "Project setup saved" in window.statusBar().currentMessage()
    finally:
        window.close()
        QApplication.processEvents()
        patch_stack.close()


def test_main_window_refreshes_shell_roots_from_application_events():
    window, context, patch_stack = _make_window()
    try:
        context.events.publish(ProjectsInvalidatedEvent())
        context.events.publish(SetupInvalidatedEvent())
        QApplication.processEvents()

        assert window.projects_view.refresh_calls == 1
        assert window.app_setup_view.refresh_calls == 1
    finally:
        window.close()
        QApplication.processEvents()
        patch_stack.close()


def test_update_sleep_inhibitor_acquires_when_project_shell_has_running_ops():
    from context_aware_translation.ui.main_window import MainWindow

    mock_inhibitor = MagicMock()
    workspace = SimpleNamespace(get_running_operations=MagicMock(return_value=["OCR"]))
    fake_window = SimpleNamespace(
        _task_engine=SimpleNamespace(has_running_work=MagicMock(return_value=False)),
        _view_registry={"project_abc": workspace},
        _sleep_inhibitor=mock_inhibitor,
    )

    MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_not_called()
