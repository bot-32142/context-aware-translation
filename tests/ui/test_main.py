from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.ui.startup import bounds_fit_available_geometries, preferred_style_name

try:
    from PySide6.QtWidgets import QApplication  # noqa: F401

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_PYSIDE6 = False

if HAS_PYSIDE6:
    import context_aware_translation.ui.main as ui_main

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


def _make_app() -> MagicMock:
    app = MagicMock()
    app.exec.return_value = 0
    return app


def _raise_system_exit(code: int = 0) -> None:
    raise SystemExit(code)


def test_preferred_style_name_prefers_native_mac_style() -> None:
    assert preferred_style_name("darwin", ["Fusion", "macOS", "Windows"]) == "macOS"


def test_preferred_style_name_prefers_windows_style() -> None:
    assert preferred_style_name("win32", ["Fusion", "Windows"]) == "Windows"


def test_preferred_style_name_leaves_linux_default_style_alone() -> None:
    assert preferred_style_name("linux", ["Fusion", "Windows"]) is None


def test_configure_qt_environment_pins_rounding_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QT_ENABLE_HIGHDPI_SCALING", raising=False)
    monkeypatch.delenv("QT_SCALE_FACTOR_ROUNDING_POLICY", raising=False)
    monkeypatch.delenv("QT_AUTO_SCREEN_SCALE_FACTOR", raising=False)

    ui_main._configure_qt_environment()

    assert ui_main.os.environ["QT_ENABLE_HIGHDPI_SCALING"] == "1"
    assert ui_main.os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] == "PassThrough"
    assert "QT_AUTO_SCREEN_SCALE_FACTOR" not in ui_main.os.environ


def test_bounds_fit_available_geometries_accepts_secondary_screen() -> None:
    assert bounds_fit_available_geometries(
        (1600, 120, 1120, 760),
        [(0, 0, 1440, 900), (1440, 0, 1920, 1080)],
    )


def test_bounds_fit_available_geometries_rejects_offscreen_bounds() -> None:
    assert not bounds_fit_available_geometries(
        (3600, 120, 1120, 760),
        [(0, 0, 1440, 900), (1440, 0, 1920, 1080)],
    )


def test_bounds_fit_available_geometries_rejects_barely_visible_window() -> None:
    assert not bounds_fit_available_geometries(
        (3300, 120, 1120, 760),
        [(0, 0, 1440, 900), (1440, 0, 1920, 1080)],
    )


def test_main_schedules_quick_exit_in_startup_smoke_test(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app()
    window = MagicMock()
    monkeypatch.setenv(ui_main.STARTUP_SMOKE_TEST_ENV, "1")

    with (
        patch.object(ui_main, "QApplication", return_value=app),
        patch.object(ui_main, "MainWindow", return_value=window),
        patch.object(ui_main, "load_stylesheet", return_value=""),
        patch.object(ui_main.i18n, "resolve_startup_language", return_value="en"),
        patch.object(ui_main.i18n, "load_translation"),
        patch.object(ui_main.QStyleFactory, "keys", return_value=[]),
        patch.object(ui_main.QTimer, "singleShot") as mock_single_shot,
        patch.object(ui_main.QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"),
        patch.object(ui_main.sys, "exit", side_effect=_raise_system_exit) as mock_exit,
    ):
        with pytest.raises(SystemExit, match="0"):
            ui_main.main()

    mock_single_shot.assert_called_once_with(1000, app.quit)
    window.show.assert_called_once_with()
    mock_exit.assert_called_once_with(0)


def test_main_skips_startup_dialog_in_startup_smoke_test(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app()
    monkeypatch.setenv(ui_main.STARTUP_SMOKE_TEST_ENV, "1")

    with (
        patch.object(ui_main, "QApplication", return_value=app),
        patch.object(ui_main, "MainWindow", side_effect=RuntimeError("boom")),
        patch.object(ui_main, "load_stylesheet", return_value=""),
        patch.object(ui_main.i18n, "resolve_startup_language", return_value="en"),
        patch.object(ui_main.i18n, "load_translation"),
        patch.object(ui_main.QStyleFactory, "keys", return_value=[]),
        patch.object(ui_main.QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"),
        patch.object(ui_main, "_show_startup_error") as mock_show_startup_error,
        patch.object(ui_main.sys, "exit", side_effect=_raise_system_exit) as mock_exit,
    ):
        with pytest.raises(SystemExit, match="1"):
            ui_main.main()

    mock_show_startup_error.assert_not_called()
    mock_exit.assert_called_once_with(1)


def test_show_startup_error_requires_existing_qapplication() -> None:
    with (
        patch.object(ui_main.QApplication, "instance", return_value=None),
        patch.object(ui_main, "_show_native_startup_error") as mock_native_error,
        patch.object(ui_main.QMessageBox, "critical") as mock_critical,
    ):
        ui_main._show_startup_error("boom")

    mock_native_error.assert_called_once()
    mock_critical.assert_not_called()
