"""Tests for the QML-backed app shell migration."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    NavigationTarget,
    NavigationTargetKind,
    ProjectRef,
    QueueActionKind,
    QueueStatus,
)
from context_aware_translation.application.contracts.projects import ProjectsScreenState, ProjectSummary
from context_aware_translation.application.contracts.queue import QueueItem, QueueState
from context_aware_translation.application.events import (
    InMemoryApplicationEventBus,
    ProjectsInvalidatedEvent,
    QueueChangedEvent,
    SetupInvalidatedEvent,
)
from context_aware_translation.ui.startup import preferred_startup_window_size
from tests.application.fakes import (
    FakeAppSetupService,
    FakeDocumentService,
    FakeProjectsService,
    FakeQueueService,
    FakeTermsService,
    FakeWorkService,
)

try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtTest import QTest
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


def _wait_until(predicate, *, timeout_ms: int = 1000) -> None:  # noqa: ANN001
    elapsed = 0
    while elapsed < timeout_ms:
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(10)
        elapsed += 10
    assert predicate()


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

    def __init__(self, _service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.refresh_calls = 0

    def refresh(self) -> None:
        self.refresh_calls += 1


class _FakeAppSettingsPane(QWidget):
    def __init__(self, _service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.refresh_calls = 0

    def refresh(self) -> None:
        self.refresh_calls += 1


class _FakeAppSettingsDialogHost(QWidget):
    finished = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body_widget: QWidget | None = None
        self.present_calls = 0
        self.retranslate_calls = 0

    def set_app_settings_widget(self, widget: QWidget) -> QWidget:
        self.body_widget = widget
        return widget

    def set_app_setup_widget(self, widget: QWidget) -> QWidget:
        return self.set_app_settings_widget(widget)

    def present(self) -> None:
        self.present_calls += 1
        self.show()

    def retranslate(self) -> None:
        self.retranslate_calls += 1

    def close(self) -> bool:
        result = super().close()
        self.finished.emit(0)
        return result


class _FakeProjectSettingsDialogHost(QWidget):
    finished = Signal(int)
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body_widget: QWidget | None = None
        self.present_calls = 0
        self.retranslate_calls = 0
        self.setWindowTitle("Project Settings")

    def set_project_settings_widget(self, widget: QWidget) -> QWidget:
        self.body_widget = widget
        return widget

    def set_project_setup_widget(self, widget: QWidget) -> QWidget:
        return self.set_project_settings_widget(widget)

    def present(self) -> None:
        self.present_calls += 1
        self.show()

    def dismiss(self) -> None:
        self.close()

    def retranslate(self) -> None:
        self.retranslate_calls += 1
        self.setWindowTitle("Project Settings")

    def close(self) -> bool:
        result = super().close()
        self.finished.emit(0)
        return result


class _FakeQueueShellHost(QWidget):
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.queue_widget: QWidget | None = None
        self.scope: tuple[str | None, str | None] = (None, None)
        self.retranslate_calls = 0
        self.cleanup_calls = 0

    def set_queue_widget(self, widget: QWidget) -> QWidget:
        self.queue_widget = widget
        return widget

    def set_scope(self, project_id: str | None, *, project_name: str | None = None) -> None:
        self.scope = (project_id, project_name)
        if self.queue_widget is not None:
            set_scope = getattr(self.queue_widget, "set_scope", None)
            if callable(set_scope):
                set_scope(project_id, project_name=project_name)

    def clear_scope(self) -> None:
        self.scope = (None, None)
        if self.queue_widget is not None:
            set_scope = getattr(self.queue_widget, "set_scope", None)
            if callable(set_scope):
                set_scope(None)

    def retranslate(self) -> None:
        self.retranslate_calls += 1

    def cleanup(self) -> None:
        self.cleanup_calls += 1


class _FakeAppShellHost(QWidget):
    projects_requested = Signal()
    app_settings_requested = Signal()
    queue_requested = Signal()
    close_project_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.views: dict[str, QWidget] = {}
        self.current_view_key = ""
        self.current_project_id = ""
        self.current_project_name = ""
        self.modal_route = ""

    def set_projects_widget(self, widget: QWidget) -> QWidget:
        self.views["projects"] = widget
        return widget

    def set_project_widget(self, key: str, widget: QWidget) -> QWidget:
        self.views[key] = widget
        return widget

    def show_projects_view(self) -> None:
        self.current_view_key = "projects"
        self.current_project_id = ""
        self.current_project_name = ""

    def show_project_view(self, key: str, project_id: str, project_name: str) -> None:
        self.current_view_key = key
        self.current_project_id = project_id
        self.current_project_name = project_name

    def remove_project_widget(self, key: str) -> QWidget | None:
        removed = self.views.pop(key, None)
        if self.current_view_key == key:
            self.show_projects_view()
        return removed

    def present_app_settings(self) -> None:
        self.modal_route = "app_settings"

    def present_queue(self, *, project_id: str | None = None) -> None:
        self.modal_route = "queue"

    def dismiss_modal(self) -> None:
        self.modal_route = ""


class _FakeSettings:
    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self._values = dict(initial or {})

    def value(self, key: str):  # noqa: ANN201
        return self._values.get(key)

    def setValue(self, key: str, value: object) -> None:
        self._values[key] = value

    def remove(self, key: str) -> None:
        self._values.pop(key, None)


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
        self.navigation_blocking_operations: list[str] | None = None
        self.cancel_requests: list[bool] = []
        self.cleanup_calls = 0
        self.routed_targets: list[NavigationTarget] = []

    def get_running_operations(self) -> list[str]:
        return list(self.running_operations)

    def get_navigation_blocking_operations(self) -> list[str]:
        if self.navigation_blocking_operations is None:
            return list(self.running_operations)
        return list(self.navigation_blocking_operations)

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        self.cancel_requests.append(include_engine_tasks)

    def cleanup(self) -> None:
        self.cleanup_calls += 1

    def open_navigation_target(self, target: NavigationTarget) -> None:
        self.routed_targets.append(target)


class _FakeProjectSettingsPane(QWidget):
    open_app_setup_requested = Signal()
    save_completed = Signal(str)

    def __init__(self, project_id, service, events, *, auto_refresh: bool = True, parent: QWidget | None = None):  # noqa: ANN001
        super().__init__(parent)
        self.project_id = project_id
        self.service = service
        self.events = events
        self.cleanup_calls = 0
        self.refresh_calls = 0
        if auto_refresh:
            self.refresh()

    def refresh(self) -> None:
        self.refresh_calls += 1

    def cleanup(self) -> None:
        self.cleanup_calls += 1


class _FakeTermsView(QWidget):
    def __init__(self, project_id, service, events, *, auto_refresh: bool = True, parent: QWidget | None = None):  # noqa: ANN001
        super().__init__(parent)
        self.project_id = project_id
        self.service = service
        self.events = events
        self.cleanup_calls = 0
        self.refresh_calls = 0
        if auto_refresh:
            self.refresh()

    def refresh(self) -> None:
        self.refresh_calls += 1

    def ensure_loaded(self) -> None:
        if self.refresh_calls == 0:
            self.refresh()

    def cleanup(self) -> None:
        self.cleanup_calls += 1


class _FakeProjectShellHost(QWidget):
    queue_requested = Signal()
    project_settings_requested = Signal()
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._work_widget: QWidget | None = None
        self._terms_widget: QWidget | None = None
        self._project_settings_widget: QWidget | None = None
        self.current_surface = ""
        self.project_id = ""
        self.project_name = ""
        self.retranslate_calls = 0

    def set_work_widget(self, widget: QWidget) -> QWidget:
        self._work_widget = widget
        return widget

    def set_terms_widget(self, widget: QWidget) -> QWidget:
        self._terms_widget = widget
        return widget

    def set_project_settings_widget(self, widget: QWidget) -> QWidget:
        self._project_settings_widget = widget
        return widget

    @property
    def work_widget(self) -> QWidget | None:
        return self._work_widget

    @property
    def terms_widget(self) -> QWidget | None:
        return self._terms_widget

    @property
    def project_settings_widget(self) -> QWidget | None:
        return self._project_settings_widget

    def set_project_context(self, project_id: str, project_name: str, *, primary="work") -> None:  # noqa: ANN001
        self.project_id = project_id
        self.project_name = project_name
        self.current_surface = "terms" if str(primary) == "terms" else "work"

    def show_work_view(self) -> None:
        self.current_surface = "work"

    def show_terms_view(self) -> None:
        if self._terms_widget is not None:
            ensure_loaded = getattr(self._terms_widget, "ensure_loaded", None)
            if callable(ensure_loaded):
                ensure_loaded()
        self.current_surface = "terms"

    def present_project_settings(self) -> None:
        self.current_surface = "project_settings"

    def present_queue(self) -> None:
        self.current_surface = "queue"

    def dismiss_modal(self) -> None:
        if self.current_surface in {"project_settings", "queue"}:
            self.current_surface = "work"

    def retranslate(self) -> None:
        self.retranslate_calls += 1

    def get_running_operations(self) -> list[str]:
        work_widget = self._work_widget
        if work_widget is None:
            return []
        get_running_operations = getattr(work_widget, "get_running_operations", None)
        if not callable(get_running_operations):
            return []
        return get_running_operations()

    def get_navigation_blocking_operations(self) -> list[str]:
        work_widget = self._work_widget
        if work_widget is None:
            return []
        get_navigation_blockers = getattr(work_widget, "get_navigation_blocking_operations", None)
        if not callable(get_navigation_blockers):
            return self.get_running_operations()
        return get_navigation_blockers()

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        work_widget = self._work_widget
        if work_widget is None:
            return
        request_cancel = getattr(work_widget, "request_cancel_running_operations", None)
        if callable(request_cancel):
            request_cancel(include_engine_tasks=include_engine_tasks)

    def cleanup(self) -> None:
        for widget in (self._work_widget, self._terms_widget, self._project_settings_widget):
            if widget is None:
                continue
            cleanup = getattr(widget, "cleanup", None)
            if callable(cleanup):
                cleanup()


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
            projects=FakeProjectsService(
                list_state=ProjectsScreenState(
                    items=[
                        ProjectSummary(
                            project=ProjectRef(project_id="project-1", name="One Piece"),
                            target_language="English",
                            progress_summary="0.0% (0/0)",
                        )
                    ]
                )
            ),
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
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.AppSettingsPane", _FakeAppSettingsPane))
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.AppShellHost", _FakeAppShellHost))
    patch_stack.enter_context(
        patch("context_aware_translation.ui.main_window.AppSettingsDialogHost", _FakeAppSettingsDialogHost)
    )
    patch_stack.enter_context(
        patch("context_aware_translation.ui.main_window.ProjectSettingsDialogHost", _FakeProjectSettingsDialogHost)
    )
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.QueueShellHost", _FakeQueueShellHost))
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.ProjectShellHost", _FakeProjectShellHost))
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.WorkView", _FakeWorkView))
    patch_stack.enter_context(
        patch("context_aware_translation.ui.main_window.ProjectSettingsPane", _FakeProjectSettingsPane)
    )
    patch_stack.enter_context(patch("context_aware_translation.ui.main_window.TermsView", _FakeTermsView))
    try:
        window = MainWindow()
    except Exception:
        patch_stack.close()
        raise
    return window, context, patch_stack


def test_main_window_routes_projects_into_project_shell():
    window, context, patch_stack = _make_window()
    try:
        assert isinstance(window.centralWidget(), _FakeAppShellHost)
        assert window._app_shell.current_view_key == "projects"
        assert context.runtime.task_engine.start_autorun_calls == 1

        window.open_project("project-1", "One Piece")

        shell = window._view_registry["project_project-1"]
        assert window._app_shell.current_view_key == "project_project-1"
        assert shell is window._app_shell.views["project_project-1"]
        assert isinstance(shell, _FakeProjectShellHost)
        assert isinstance(shell.work_widget, _FakeWorkView)
        assert isinstance(shell.terms_widget, _FakeTermsView)
        assert isinstance(shell.project_settings_widget, _FakeProjectSettingsPane)
        assert isinstance(window._project_settings_dialog, _FakeProjectSettingsDialogHost)
        assert window._project_settings_dialog.body_widget is shell.project_settings_widget
        assert window._app_shell.current_project_name == "One Piece"
        assert shell.current_surface == "work"

        shell.queue_requested.emit()
        assert not window._queue_dock.isHidden()
        assert window._queue_drawer._scope_project_id == "project-1"
        assert window._app_shell.modal_route == "queue"

        shell.work_widget.open_project_setup_requested.emit()
        assert not window._project_settings_dialog.isHidden()
        assert window._project_settings_dialog.windowTitle() == window.tr("Project Settings")

        shell.project_settings_widget.open_app_setup_requested.emit()
        assert not window._app_settings_dialog.isHidden()
        assert window._app_shell.modal_route == "app_settings"

        shell.project_settings_widget.save_completed.emit("project-1")
        assert shell.current_surface == "work"
        assert "Project setup saved" in window.statusBar().currentMessage()
    finally:
        window.close()
        patch_stack.close()


def test_main_window_uses_centered_compact_default_size():
    settings = _FakeSettings()
    settings_patch = patch("context_aware_translation.ui.main_window.QSettings", return_value=settings)
    settings_patch.start()
    window, _context, patch_stack = _make_window()
    try:
        available = QApplication.primaryScreen().availableGeometry()
        expected_width, expected_height = preferred_startup_window_size(available.width(), available.height())

        assert (window.width(), window.height()) == (expected_width, expected_height)
        assert not window.isMaximized()
        assert not window.isFullScreen()
    finally:
        window.close()
        patch_stack.close()
        settings_patch.stop()


def test_main_window_ignores_legacy_maximized_geometry_on_startup():
    legacy_window = QWidget()
    legacy_window.showMaximized()
    QApplication.processEvents()
    legacy_geometry = legacy_window.saveGeometry()
    legacy_window.close()

    settings = _FakeSettings({"geometry": legacy_geometry})
    settings_patch = patch("context_aware_translation.ui.main_window.QSettings", return_value=settings)
    settings_patch.start()
    window, _context, patch_stack = _make_window()
    try:
        available = QApplication.primaryScreen().availableGeometry()
        expected_width, expected_height = preferred_startup_window_size(available.width(), available.height())

        assert (window.width(), window.height()) == (expected_width, expected_height)
        assert not window.isMaximized()
        assert not window.isFullScreen()
    finally:
        window.close()
        patch_stack.close()
        settings_patch.stop()

    assert "geometry" not in settings._values
    assert "window_bounds_v2" in settings._values


def test_main_window_open_project_lazy_loads_hidden_terms_and_project_settings():
    window, context, patch_stack = _make_window()
    try:
        project_setup_service = MagicMock()
        context.services.project_setup = project_setup_service

        window.open_project("project-1", "One Piece")

        shell = window._view_registry["project_project-1"]
        assert isinstance(shell, _FakeProjectShellHost)
        assert isinstance(shell.terms_widget, _FakeTermsView)
        assert isinstance(shell.project_settings_widget, _FakeProjectSettingsPane)
        assert shell.terms_widget.refresh_calls == 0
        assert shell.project_settings_widget.refresh_calls == 0

        shell.show_terms_view()
        assert shell.terms_widget.refresh_calls == 1

        window._open_project_settings(shell)
        assert shell.project_settings_widget.refresh_calls == 1
        assert project_setup_service.get_state.call_count == 0
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


def test_main_window_routes_navigation_targets_through_route_bridge():
    window, _context, patch_stack = _make_window()
    try:
        window.open_project("project-1", "One Piece")
        shell = window._view_registry["project_project-1"]
        work_tab = shell.work_widget
        assert isinstance(work_tab, _FakeWorkView)

        window._open_navigation_target(
            NavigationTarget(
                kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
                project_id="project-1",
                document_id=4,
            )
        )
        assert shell.current_surface == "work"
        assert work_tab.routed_targets[-1].kind is NavigationTargetKind.DOCUMENT_TRANSLATION

        window._open_navigation_target(
            NavigationTarget(
                kind=NavigationTargetKind.PROJECT_SETUP,
                project_id="project-1",
            )
        )
        assert not window._project_settings_dialog.isHidden()

        window._open_navigation_target(
            NavigationTarget(
                kind=NavigationTargetKind.QUEUE,
                project_id="project-1",
            )
        )
        assert not window._queue_dock.isHidden()
        assert window._queue_shell.scope == ("project-1", "One Piece")

        window._open_navigation_target(
            NavigationTarget(
                kind=NavigationTargetKind.TERMS,
                project_id="project-1",
            )
        )
        assert shell.current_surface == "terms"
    finally:
        window.close()
        patch_stack.close()


def test_main_window_projects_navigation_ignores_background_engine_tasks():
    window, _context, patch_stack = _make_window()
    try:
        window.open_project("project-1", "One Piece")
        current_shell = window._view_registry["project_project-1"]
        assert isinstance(current_shell, _FakeProjectShellHost)
        assert isinstance(current_shell.work_widget, _FakeWorkView)
        current_shell.work_widget.running_operations = ["OCR"]
        current_shell.work_widget.navigation_blocking_operations = []

        with patch.object(window, "_warn_running_operations") as warn:
            window._show_projects_surface()

        warn.assert_not_called()
        assert current_shell.work_widget.cancel_requests == []
        assert window._current_book_id is None
        assert window._app_shell.current_view_key == "projects"
    finally:
        window.close()
        patch_stack.close()


def test_main_window_cross_project_navigation_uses_running_operation_warning_flow():
    window, context, patch_stack = _make_window()
    try:
        window.open_project("project-1", "One Piece")
        current_shell = window._view_registry["project_project-1"]
        assert isinstance(current_shell, _FakeProjectShellHost)
        assert isinstance(current_shell.work_widget, _FakeWorkView)
        current_shell.work_widget.running_operations = ["OCR"]
        context.runtime.book_manager.get_book.return_value = SimpleNamespace(book_id="project-2", name="Bleach")

        with patch.object(window, "_warn_running_operations", return_value=False) as warn:
            window._open_navigation_target(NavigationTarget(kind=NavigationTargetKind.WORK, project_id="project-2"))

        warn.assert_called_once_with(["OCR"])
        assert current_shell.work_widget.cancel_requests == []
        assert window._current_book_id == "project-1"

        with patch.object(window, "_warn_running_operations", return_value=True) as warn:
            window._open_navigation_target(NavigationTarget(kind=NavigationTargetKind.WORK, project_id="project-2"))

        warn.assert_called_once_with(["OCR"])
        assert current_shell.work_widget.cancel_requests == [False]
        assert window._current_book_id == "project-2"
        assert window._app_shell.current_view_key == "project_project-2"
    finally:
        window.close()
        patch_stack.close()


def test_main_window_routes_global_queue_target_without_open_project():
    window, _context, patch_stack = _make_window()
    try:
        window._open_navigation_target(NavigationTarget(kind=NavigationTargetKind.QUEUE))

        assert not window._queue_dock.isHidden()
        assert window._queue_shell.scope == (None, None)
        assert window._app_shell.modal_route == "queue"
    finally:
        window.close()
        patch_stack.close()


def test_main_window_app_shell_projects_request_closes_current_project():
    window, _context, patch_stack = _make_window()
    try:
        window.open_project("project-1", "One Piece")

        window._app_shell.projects_requested.emit()

        assert window._current_book_id is None
        assert window._app_shell.current_view_key == "projects"
        assert "project_project-1" not in window._view_registry
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


def test_main_window_queue_can_close_after_delete_empties_list():
    window, context, patch_stack = _make_window()
    try:
        context.services.queue.state = QueueState(
            items=[
                QueueItem(
                    queue_item_id="task-1",
                    title="Read text from images",
                    project_id="project-1",
                    document_id=4,
                    status=QueueStatus.FAILED,
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_OCR,
                        project_id="project-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.DELETE],
                )
            ]
        )

        def _apply_action(request):  # noqa: ANN001
            context.services.queue.calls.append(("apply_action", request))
            context.services.queue.state = QueueState(items=[])
            return AcceptedCommand(command_name="delete")

        context.services.queue.apply_action = _apply_action  # type: ignore[method-assign]

        window.open_project("project-1", "One Piece")
        shell = window._view_registry["project_project-1"]
        assert isinstance(shell, _FakeProjectShellHost)

        window._on_queue_requested()
        shell.present_queue()

        row = window._queue_drawer._rows["task-1"]
        row._buttons[QueueActionKind.DELETE].click()
        _wait_until(lambda: window._queue_drawer._rows == {})

        window._queue_shell.close_requested.emit()
        QApplication.processEvents()

        assert window._queue_dock.isHidden()
        assert window._app_shell.modal_route == ""
        assert window._queue_shell.scope == (None, None)
        assert shell.current_surface == "work"
    finally:
        window.close()
        patch_stack.close()


def test_main_window_close_keeps_store_open_while_task_engine_still_running():
    window, context, patch_stack = _make_window()
    try:
        context.runtime.task_engine._has_running_work = True

        window.close()

        assert context.runtime.task_engine.close_calls == 1
        context.runtime.task_store.close.assert_not_called()
        context.runtime.book_manager.close.assert_not_called()
    finally:
        patch_stack.close()


def test_main_window_queue_close_after_multiple_deletes_clears_project_modal_state():
    window, context, patch_stack = _make_window()
    try:
        context.services.queue.state = QueueState(
            items=[
                QueueItem(
                    queue_item_id="task-1",
                    title="Read text from images",
                    project_id="project-1",
                    document_id=4,
                    status=QueueStatus.DONE,
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_OCR,
                        project_id="project-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.DELETE],
                ),
                QueueItem(
                    queue_item_id="task-2",
                    title="Export terms",
                    project_id="project-1",
                    document_id=4,
                    status=QueueStatus.DONE,
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_TERMS,
                        project_id="project-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.DELETE],
                ),
            ]
        )

        def _apply_action(request):  # noqa: ANN001
            context.services.queue.calls.append(("apply_action", request))
            context.services.queue.state = QueueState(
                items=[
                    item for item in context.services.queue.state.items if item.queue_item_id != request.queue_item_id
                ]
            )
            return AcceptedCommand(command_name="delete")

        context.services.queue.apply_action = _apply_action  # type: ignore[method-assign]

        window.open_project("project-1", "One Piece")
        shell = window._view_registry["project_project-1"]
        assert isinstance(shell, _FakeProjectShellHost)

        shell.present_queue()
        shell.queue_requested.emit()
        assert shell.current_surface == "queue"

        window._queue_drawer._rows["task-1"]._buttons[QueueActionKind.DELETE].click()
        _wait_until(lambda: "task-1" not in window._queue_drawer._rows)
        window._queue_drawer._rows["task-2"]._buttons[QueueActionKind.DELETE].click()
        _wait_until(lambda: window._queue_drawer._rows == {})

        window._queue_shell.close_requested.emit()
        QApplication.processEvents()

        assert window._queue_dock.isHidden()
        assert window._app_shell.modal_route == ""
        assert window._queue_shell.scope == (None, None)
        assert shell.current_surface == "work"
    finally:
        window.close()
        patch_stack.close()


def test_main_window_closing_queue_does_not_dismiss_project_settings_modal():
    window, _context, patch_stack = _make_window()
    try:
        window.open_project("project-1", "One Piece")
        shell = window._view_registry["project_project-1"]
        assert isinstance(shell, _FakeProjectShellHost)

        shell.present_project_settings()
        window._open_queue_drawer(project_id="project-1", project_name="One Piece")

        window._queue_shell.close_requested.emit()
        QApplication.processEvents()

        assert window._queue_dock.isHidden()
        assert window._app_shell.modal_route == ""
        assert shell.current_surface == "project_settings"
    finally:
        window.close()
        patch_stack.close()


def test_update_sleep_inhibitor_acquires_when_project_shell_has_running_ops():
    from context_aware_translation.ui.main_window import MainWindow

    mock_inhibitor = MagicMock()
    workspace = SimpleNamespace(get_running_operations=MagicMock(return_value=["OCR"]))
    fake_window = SimpleNamespace()
    fake_window._task_engine = SimpleNamespace(has_running_work=MagicMock(return_value=False))
    fake_window._view_registry = {"project_abc": workspace}
    fake_window._sleep_inhibitor = mock_inhibitor
    fake_window._sleep_inhibitor_acquired = False
    fake_window._set_sleep_inhibitor_active = lambda active: MainWindow._set_sleep_inhibitor_active(fake_window, active)

    MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_not_called()

    MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.acquire.assert_called_once()

    workspace.get_running_operations.return_value = []
    MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.release.assert_called_once()
