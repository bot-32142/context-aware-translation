"""Unit tests for SleepInhibitor and BaseWorker integration."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")

_MODULE = "context_aware_translation.ui.sleep_inhibitor"


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reset_inhibitor():
    """Reset SleepInhibitor class state between tests."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    SleepInhibitor._count = 0
    SleepInhibitor._process = None
    yield
    SleepInhibitor._count = 0
    SleepInhibitor._process = None


# --- macOS (Darwin) tests ---


@patch(f"{_MODULE}.subprocess")
@patch(f"{_MODULE}._SYSTEM", "Darwin")
def test_acquire_release_lifecycle_on_darwin(mock_subprocess):
    """Acquire starts caffeinate, release stops it."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = MagicMock()
    mock_subprocess.Popen.return_value = mock_proc
    mock_subprocess.DEVNULL = -1
    mock_subprocess.PIPE = -2

    SleepInhibitor.acquire()

    mock_subprocess.Popen.assert_called_once_with(["caffeinate", "-i"], stdin=-2, stdout=-1, stderr=-1)
    assert SleepInhibitor._count == 1

    SleepInhibitor.release()

    mock_proc.stdin.close.assert_called_once()
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()
    assert SleepInhibitor._count == 0


@patch(f"{_MODULE}.subprocess")
@patch(f"{_MODULE}._SYSTEM", "Darwin")
def test_reference_counting(mock_subprocess):
    """Multiple acquires share one process; last release stops it."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_subprocess.Popen.return_value = mock_proc
    mock_subprocess.DEVNULL = -1
    mock_subprocess.PIPE = -2

    SleepInhibitor.acquire()
    SleepInhibitor.acquire()
    SleepInhibitor.acquire()

    assert mock_subprocess.Popen.call_count == 1
    assert SleepInhibitor._count == 3

    SleepInhibitor.release()
    SleepInhibitor.release()
    assert SleepInhibitor._count == 1
    mock_proc.terminate.assert_not_called()

    SleepInhibitor.release()
    assert SleepInhibitor._count == 0
    mock_proc.terminate.assert_called_once()


@patch(f"{_MODULE}._SYSTEM", "Darwin")
def test_release_without_acquire_is_noop(caplog):
    """Release without prior acquire is a silent no-op."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    with caplog.at_level("WARNING"):
        SleepInhibitor.release()

    assert "without matching acquire" not in caplog.text
    assert SleepInhibitor._count == 0


@patch(f"{_MODULE}.subprocess")
@patch(f"{_MODULE}._SYSTEM", "Darwin")
def test_is_active_reflects_state(mock_subprocess):
    """is_active() returns correct state through lifecycle."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = MagicMock()
    mock_subprocess.Popen.return_value = mock_proc
    mock_subprocess.DEVNULL = -1
    mock_subprocess.PIPE = -2

    assert not SleepInhibitor.is_active()

    SleepInhibitor.acquire()
    assert SleepInhibitor.is_active()

    SleepInhibitor.release()
    assert not SleepInhibitor.is_active()


@patch(f"{_MODULE}.subprocess")
@patch(f"{_MODULE}._SYSTEM", "Darwin")
def test_subprocess_unexpected_death_restarts(mock_subprocess):
    """If the inhibitor process dies, next acquire restarts it."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    mock_proc_1 = MagicMock()
    mock_proc_1.poll.return_value = None
    mock_proc_2 = MagicMock()
    mock_proc_2.poll.return_value = None
    mock_subprocess.Popen.side_effect = [mock_proc_1, mock_proc_2]
    mock_subprocess.DEVNULL = -1
    mock_subprocess.PIPE = -2

    SleepInhibitor.acquire()
    assert mock_subprocess.Popen.call_count == 1

    # Simulate process dying
    mock_proc_1.poll.return_value = 1

    SleepInhibitor.acquire()
    assert mock_subprocess.Popen.call_count == 2
    assert SleepInhibitor._count == 2


@patch(f"{_MODULE}.subprocess")
@patch(f"{_MODULE}._SYSTEM", "Darwin")
def test_thread_safety(mock_subprocess):
    """Concurrent acquire/release from 20 threads leaves count at 0."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_subprocess.Popen.return_value = mock_proc
    mock_subprocess.DEVNULL = -1
    mock_subprocess.PIPE = -2

    errors = []
    barrier = threading.Barrier(20)

    def worker():
        try:
            barrier.wait()
            SleepInhibitor.acquire()
            SleepInhibitor.release()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert SleepInhibitor._count == 0


# --- Linux tests ---


@patch(f"{_MODULE}.subprocess")
@patch(f"{_MODULE}._SYSTEM", "Linux")
def test_linux_uses_systemd_inhibit(mock_subprocess):
    """On Linux, spawns systemd-inhibit."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = MagicMock()
    mock_subprocess.Popen.return_value = mock_proc
    mock_subprocess.DEVNULL = -1
    mock_subprocess.PIPE = -2

    SleepInhibitor.acquire()

    mock_subprocess.Popen.assert_called_once_with(
        [
            "systemd-inhibit",
            "--what=idle",
            "--who=context-aware-translation",
            "--why=Background operation in progress",
            "cat",
        ],
        stdin=-2,
        stdout=-1,
        stderr=-1,
    )
    assert SleepInhibitor._count == 1

    SleepInhibitor.release()

    mock_proc.stdin.close.assert_called_once()
    mock_proc.terminate.assert_called_once()
    assert SleepInhibitor._count == 0


@patch(f"{_MODULE}.subprocess")
@patch(f"{_MODULE}._SYSTEM", "Linux")
def test_linux_graceful_when_systemd_inhibit_missing(mock_subprocess, caplog):
    """If systemd-inhibit is not found, logs warning and continues."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    mock_subprocess.Popen.side_effect = FileNotFoundError
    mock_subprocess.DEVNULL = -1
    mock_subprocess.PIPE = -2

    with caplog.at_level("WARNING"):
        SleepInhibitor.acquire()

    assert "not found" in caplog.text
    assert SleepInhibitor._count == 1
    assert SleepInhibitor._process is None


# --- Windows tests ---


@patch(f"{_MODULE}.ctypes")
@patch(f"{_MODULE}._SYSTEM", "Windows")
def test_windows_uses_set_thread_execution_state(mock_ctypes):
    """On Windows, calls SetThreadExecutionState."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    SleepInhibitor.acquire()

    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    mock_ctypes.windll.kernel32.SetThreadExecutionState.assert_called_with(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    assert SleepInhibitor._count == 1

    SleepInhibitor.release()

    mock_ctypes.windll.kernel32.SetThreadExecutionState.assert_called_with(ES_CONTINUOUS)
    assert SleepInhibitor._count == 0


@patch(f"{_MODULE}.ctypes")
@patch(f"{_MODULE}._SYSTEM", "Windows")
def test_windows_is_active_uses_count(mock_ctypes):  # noqa: ARG001
    """On Windows, is_active() is based on count, not subprocess."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    assert not SleepInhibitor.is_active()

    SleepInhibitor.acquire()
    assert SleepInhibitor.is_active()

    SleepInhibitor.release()
    assert not SleepInhibitor.is_active()


@patch(f"{_MODULE}.ctypes")
@patch(f"{_MODULE}._SYSTEM", "Windows")
def test_windows_reference_counting(mock_ctypes):
    """Windows: multiple acquires, SetThreadExecutionState called on first and last."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    ES_CONTINUOUS = 0x80000000

    SleepInhibitor.acquire()
    SleepInhibitor.acquire()
    SleepInhibitor.acquire()

    # Only called once on first acquire
    assert mock_ctypes.windll.kernel32.SetThreadExecutionState.call_count == 1
    assert SleepInhibitor._count == 3

    SleepInhibitor.release()
    SleepInhibitor.release()
    # Still only the initial call
    assert mock_ctypes.windll.kernel32.SetThreadExecutionState.call_count == 1

    SleepInhibitor.release()
    # Now reset call added
    assert mock_ctypes.windll.kernel32.SetThreadExecutionState.call_count == 2
    mock_ctypes.windll.kernel32.SetThreadExecutionState.assert_called_with(ES_CONTINUOUS)


# --- Unsupported platform test ---


@patch(f"{_MODULE}.subprocess")
@patch(f"{_MODULE}._SYSTEM", "FreeBSD")
def test_noop_on_unsupported_platform(mock_subprocess):
    """No action on unsupported platforms."""
    from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor

    SleepInhibitor.acquire()
    SleepInhibitor.release()

    mock_subprocess.Popen.assert_not_called()
    assert SleepInhibitor._count == 0


# --- BaseWorker integration tests ---


@patch("context_aware_translation.ui.sleep_inhibitor.SleepInhibitor")
def test_base_worker_acquires_and_releases(mock_inhibitor):
    """BaseWorker.run() calls acquire before work and release after."""
    from context_aware_translation.ui.workers.base_worker import BaseWorker

    class _TestWorker(BaseWorker):
        def _execute(self):
            self.finished_success.emit(None)

    worker = _TestWorker()
    worker.run()

    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_called_once()


@patch("context_aware_translation.ui.sleep_inhibitor.SleepInhibitor")
def test_base_worker_releases_on_exception(mock_inhibitor):
    """BaseWorker.run() releases even when _execute() raises."""
    from context_aware_translation.ui.workers.base_worker import BaseWorker

    class _ErrorWorker(BaseWorker):
        def _execute(self):
            raise RuntimeError("boom")

    worker = _ErrorWorker()
    worker.run()

    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_called_once()


@patch("context_aware_translation.ui.sleep_inhibitor.SleepInhibitor")
def test_base_worker_releases_on_cancellation(mock_inhibitor):
    """BaseWorker.run() releases even on cancellation."""
    from context_aware_translation.core.cancellation import OperationCancelledError
    from context_aware_translation.ui.workers.base_worker import BaseWorker

    class _CancelWorker(BaseWorker):
        def _execute(self):
            raise OperationCancelledError("cancelled")

    worker = _CancelWorker()
    worker.run()

    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_called_once()


# --- MainWindow _update_sleep_inhibitor integration tests ---


def test_update_sleep_inhibitor_acquires_when_global_batch_workers_active():
    from context_aware_translation.ui.main_window import MainWindow

    mock_inhibitor = MagicMock()
    fake_window = SimpleNamespace(
        _global_batch_workers={"book-1": MagicMock()},
        _view_registry={},
        _sleep_inhibitor=mock_inhibitor,
    )

    MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_not_called()


def test_update_sleep_inhibitor_acquires_when_workspace_has_running_ops():
    from context_aware_translation.ui.main_window import MainWindow

    mock_inhibitor = MagicMock()
    workspace = SimpleNamespace(get_running_operations=MagicMock(return_value=["Translation"]))
    fake_window = SimpleNamespace(
        _global_batch_workers={},
        _view_registry={"book_abc": workspace},
        _sleep_inhibitor=mock_inhibitor,
    )

    MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_not_called()


def test_update_sleep_inhibitor_acquires_when_translation_batch_worker_running():
    from context_aware_translation.ui.main_window import MainWindow
    from context_aware_translation.ui.views.book_workspace import BookWorkspace

    mock_inhibitor = MagicMock()
    translation_view = SimpleNamespace(batch_task_worker=SimpleNamespace(isRunning=MagicMock(return_value=True)))
    workspace = MagicMock(spec=BookWorkspace)
    workspace.get_translation_view.return_value = translation_view
    workspace.get_running_operations.return_value = []
    fake_window = SimpleNamespace(
        _global_batch_workers={},
        _view_registry={"book_abc": workspace},
        _sleep_inhibitor=mock_inhibitor,
    )

    with patch(
        "context_aware_translation.ui.views.translation_view.TranslationView._DETACHED_BATCH_RUN_WORKERS",
        set(),
    ):
        MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_not_called()


def test_update_sleep_inhibitor_acquires_when_detached_batch_run_worker_active():
    from context_aware_translation.ui.main_window import MainWindow

    mock_inhibitor = MagicMock()
    detached_worker = MagicMock()
    detached_worker.isRunning.return_value = True
    fake_window = SimpleNamespace(
        _global_batch_workers={},
        _view_registry={},
        _sleep_inhibitor=mock_inhibitor,
    )

    with patch(
        "context_aware_translation.ui.views.translation_view.TranslationView._DETACHED_BATCH_RUN_WORKERS",
        {detached_worker},
    ):
        MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.acquire.assert_called_once()
    mock_inhibitor.release.assert_not_called()


def test_update_sleep_inhibitor_releases_when_nothing_running():
    from context_aware_translation.ui.main_window import MainWindow

    mock_inhibitor = MagicMock()
    workspace = SimpleNamespace(get_running_operations=MagicMock(return_value=[]))
    fake_window = SimpleNamespace(
        _global_batch_workers={},
        _view_registry={"book_abc": workspace, "library": SimpleNamespace()},
        _sleep_inhibitor=mock_inhibitor,
    )

    MainWindow._update_sleep_inhibitor(fake_window)
    mock_inhibitor.release.assert_called_once()
    mock_inhibitor.acquire.assert_not_called()
