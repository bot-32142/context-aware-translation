"""Tests for the Task 10 app shell migration."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.application.contracts.common import (
    NavigationTarget,
    NavigationTargetKind,
    QueueActionKind,
    QueueStatus,
)
from context_aware_translation.application.contracts.queue import QueueItem, QueueState
from context_aware_translation.application.events import (
    InMemoryApplicationEventBus,
    ProjectsInvalidatedEvent,
    QueueChangedEvent,
    SetupInvalidatedEvent,
)
from tests.application.fakes import (
    FakeAppSetupService,
    FakeDocumentService,
    FakeQueueService,
    FakeTermsService,
    FakeWorkService,
)

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


class _FakeWorkView(QWidget):
    open_app_setup_requested = Signal()
    open_project_setup_requested = Signal()

    def __init__(
        self,
        project_id: str,
        work_service,
        document_service,
        terms_service,
        events,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.work_service = work_service
        self.document_service = document_service
        self.terms_service = terms_service
        self.events = events
        self.running_operations: list[str] = []
        self.cancel_requests: list[bool] = []
        self.cleanup_calls = 0
        self.routed_targets: list[NavigationTarget] = []

    def get_running_operations(self) -> list[str]:
        return list(self.running_operations)

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        self.cancel_requests.append(include_engine_tasks)

    def cleanup(self) -> None:
        self.cleanup_calls += 1

    def open_navigation_target(self, target: NavigationTarget) -> None:
        self.routed_targets.append(target)


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


class _FakeTermsView(QWidget):
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
    work_service = FakeWorkService(state_by_project={"project-1": MagicMock()})
    document_service = FakeDocumentService(workspace=MagicMock())
    terms_service = FakeTermsService(project_state=MagicMock())
    queue_service = FakeQueueService(
        state=QueueState(
            items=[
                QueueItem(
                    queue_item_id="task-1",
                    title="Read text from images",
                    project_id="project-1",
                    document_id=4,
                    status=QueueStatus.RUNNING,
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_OCR,
                        project_id="project-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.CANCEL],
                )
            ]
        )
    )
    return SimpleNamespace(
        runtime=SimpleNamespace(
            book_manager=book_manager,
            task_store=task_store,
            task_engine=task_engine,
            worker_deps=object(),
        ),
        services=SimpleNamespace(
            app_setup=app_setup_service,
            project_setup=MagicMock(),
            work=work_service,
            document=document_service,
            terms=terms_service,
            queue=queue_service,
        ),
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
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.WorkView", _FakeWorkView))
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.ProjectSetupView", _FakeProjectSetupView))
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.TermsView", _FakeTermsView))
    try:
        window = MainWindow()
    except Exception:
        patch_stack.close()
        raise
    return window, context, patch_stack


def test_project_shell_view_delegates_to_work_widget():
    from context_aware_translation.ui.features.project_shell_view import ProjectShellView

    work_widget = _FakeWorkView("project-1", None, None, None, None)
    terms_widget = _FakeTermsView("project-1", None, None)
    setup_widget = _FakeProjectSetupView("project-1", None, None)
    work_widget.running_operations = ["Translation"]

    queue_calls: list[bool] = []
    close_calls: list[bool] = []
    shell = ProjectShellView(
        "project-1",
        "One Piece",
        work_widget=work_widget,
        terms_widget=terms_widget,
        setup_widget=setup_widget,
    )
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
    assert terms_widget.cleanup_calls == 1
    assert setup_widget.cleanup_calls == 1


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
        assert isinstance(shell.work_tab, _FakeWorkView)
        assert isinstance(shell.terms_tab, _FakeTermsView)
        assert isinstance(shell.setup_tab, _FakeProjectSetupView)
        assert window._book_nav_item.text() == window.tr("Project: One Piece")

        shell.queue_button.click()
        assert not window._queue_dock.isHidden()
        assert "One Piece" in window._queue_drawer.tip_label.text()

        shell.work_tab.open_project_setup_requested.emit()
        assert shell.tab_widget.currentWidget() is shell.setup_tab

        shell.setup_tab.open_app_setup_requested.emit()
        assert window._stack.currentWidget() is window.app_setup_view

        shell.setup_tab.save_completed.emit("project-1")
        assert shell.tab_widget.currentWidget() is shell.work_tab
        assert "Project setup saved" in window.statusBar().currentMessage()
    finally:
        window.close()
        patch_stack.close()


def test_main_window_refreshes_shell_roots_from_application_events():
    window, context, patch_stack = _make_window()
    try:
        context.events.publish(ProjectsInvalidatedEvent())
        context.events.publish(SetupInvalidatedEvent())

        assert window.projects_view.refresh_calls == 1
        assert window.app_setup_view.refresh_calls == 1
    finally:
        window.close()
        patch_stack.close()


def test_main_window_routes_queue_targets_into_current_shell():
    window, context, patch_stack = _make_window()
    try:
        window.open_project("project-1", "One Piece")
        shell = window._view_registry["project_project-1"]
        work_tab = shell.work_tab

        window._open_navigation_target(
            NavigationTarget(
                kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
                project_id="project-1",
                document_id=4,
            )
        )
        assert shell.tab_widget.currentWidget() is shell.work_tab
        assert work_tab.routed_targets[-1].kind is NavigationTargetKind.DOCUMENT_TRANSLATION

        window._open_navigation_target(
            NavigationTarget(
                kind=NavigationTargetKind.PROJECT_SETUP,
                project_id="project-1",
            )
        )
        assert shell.tab_widget.currentWidget() is shell.setup_tab

        window._open_navigation_target(
            NavigationTarget(
                kind=NavigationTargetKind.TERMS,
                project_id="project-1",
            )
        )
        assert shell.tab_widget.currentWidget() is shell.terms_tab
    finally:
        window.close()
        patch_stack.close()


def test_main_window_queue_drawer_refreshes_from_queue_events():
    window, context, patch_stack = _make_window()
    try:
        window.open_project("project-1", "One Piece")
        window._open_queue_drawer(project_id="project-1", project_name="One Piece")
        context.events.publish(QueueChangedEvent(project_id="project-1"))

        assert ("get_queue", "project-1") in context.services.queue.calls
    finally:
        window.close()
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
