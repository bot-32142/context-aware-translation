"""Entry point for the PySide6 desktop application."""

import importlib.resources as importlib_resources
import json
import os
import subprocess
import sys
import traceback
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QStyleFactory

from context_aware_translation.ui import i18n
from context_aware_translation.ui.main_window import MainWindow
from context_aware_translation.ui.qml_resources import create_qml_engine, load_qml_component, qml_root_path, qml_source
from context_aware_translation.ui.startup import preferred_style_name

__all__ = [
    "create_qml_engine",
    "load_qml_component",
    "load_stylesheet",
    "main",
    "qml_root_path",
    "qml_source",
]

STARTUP_SMOKE_TEST_ENV = "CAT_SMOKE_TEST_STARTUP"


def _configure_qt_environment() -> None:
    # Qt 6 already enables high-DPI support. Keep the rounding policy explicit so
    # local runs and packaged apps react the same way to fractional scaling.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")


def load_stylesheet() -> str:
    """Load the application stylesheet.

    Use package-resource loading first so frozen builds (PyInstaller) can
    still resolve the stylesheet consistently across platforms.
    """
    try:
        resource = importlib_resources.files("context_aware_translation.ui.resources").joinpath("styles.qss")
        return resource.read_text(encoding="utf-8")
    except Exception:
        # Fallback for editable/local runs.
        pass

    style_path = Path(__file__).parent / "resources" / "styles.qss"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return ""


def _show_startup_error(detail: str) -> None:
    """Surface startup failures in packaged GUI runs where stderr is hidden."""
    message = f"Context-Aware Translation failed to start.\n\nPlease send this traceback to support:\n\n{detail}"
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        _show_native_startup_error("Startup Error", message)
        return
    with suppress(Exception):
        QMessageBox.critical(
            None,
            "Startup Error",
            message,
        )


def _show_native_startup_error(title: str, message: str) -> None:
    """Best-effort native fallback when Qt cannot create a message box."""
    truncated_message = message[:4000]

    with suppress(Exception):
        if sys.platform == "darwin":
            script = f"display alert {json.dumps(title)} message {json.dumps(truncated_message)} as critical"
            subprocess.run(["osascript", "-e", script], check=False)
            return

        if sys.platform.startswith("win"):
            env = os.environ.copy()
            env["CAT_STARTUP_ERROR_TITLE"] = title
            env["CAT_STARTUP_ERROR_MESSAGE"] = truncated_message
            script = (
                "Add-Type -AssemblyName PresentationFramework; "
                "[System.Windows.MessageBox]::Show($env:CAT_STARTUP_ERROR_MESSAGE, "
                "$env:CAT_STARTUP_ERROR_TITLE, 'OK', 'Error')"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False, env=env)


def _startup_smoke_test_enabled() -> bool:
    return os.environ.get(STARTUP_SMOKE_TEST_ENV) == "1"


def _apply_preferred_style(app: QApplication) -> None:
    style_name = preferred_style_name(sys.platform, QStyleFactory.keys())
    if style_name:
        app.setStyle(style_name)


def main() -> None:
    """Launch the application."""
    # Keep packaged and local runs consistent on high-DPI displays.
    _configure_qt_environment()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("Context-Aware Translation")
        app.setOrganizationName("CAT")
        app.setOrganizationDomain("context-aware-translation")
        _apply_preferred_style(app)

        stylesheet = load_stylesheet()
        if stylesheet:
            app.setStyleSheet(stylesheet)

        i18n.load_translation(app, i18n.resolve_startup_language())

        window = MainWindow()
        window.show()
        if _startup_smoke_test_enabled():
            QTimer.singleShot(1000, app.quit)
        sys.exit(app.exec())
    except Exception:
        if _startup_smoke_test_enabled():
            traceback.print_exc()
            sys.exit(1)
        _show_startup_error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
