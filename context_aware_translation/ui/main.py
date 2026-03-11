"""Entry point for the PySide6 desktop application."""

import atexit
import importlib.resources as importlib_resources
import os
import sys
import traceback
from contextlib import ExitStack
from functools import cache
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QStyleFactory

_RESOURCE_STACK = ExitStack()
_QML_DIR_NAME = "qml"


@atexit.register
def _close_resource_stack() -> None:
    _RESOURCE_STACK.close()


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


@cache
def _resource_path(package: str, resource_name: str) -> Path:
    resource = importlib_resources.files(package).joinpath(resource_name)
    return _RESOURCE_STACK.enter_context(importlib_resources.as_file(resource))


def qml_root_path() -> Path:
    """Return a stable filesystem path to bundled QML resources."""
    try:
        return _resource_path("context_aware_translation.ui", _QML_DIR_NAME)
    except Exception:
        qml_path = Path(__file__).parent / _QML_DIR_NAME
        if qml_path.exists():
            return qml_path
        raise


def qml_source(relative_path: str) -> QUrl:
    """Resolve a QML file under the bundled QML root into a local-file URL."""
    qml_path = qml_root_path() / relative_path
    if not qml_path.exists():
        raise FileNotFoundError(f"QML resource not found: {qml_path}")
    return QUrl.fromLocalFile(str(qml_path))


def create_qml_engine(*, parent: QObject | None = None):
    """Create a QQmlEngine with the packaged QML root on its import path."""
    from PySide6.QtQml import QQmlEngine

    engine = QQmlEngine(parent)
    engine.addImportPath(str(qml_root_path()))
    return engine


def load_qml_component(engine, relative_path: str):
    """Create a QQmlComponent for a bundled QML file."""
    from PySide6.QtQml import QQmlComponent

    return QQmlComponent(engine, qml_source(relative_path))


def _show_startup_error(detail: str) -> None:
    """Surface startup failures in packaged GUI runs where stderr is hidden."""
    try:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(
            None,
            "Startup Error",
            f"Context-Aware Translation failed to start.\n\nPlease send this traceback to support:\n\n{detail}",
        )
    except Exception:
        # If the message box path also fails, preserve the original exception.
        pass


def main() -> None:
    """Launch the application."""
    # Keep packaged and local runs consistent on high-DPI displays.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("Context-Aware Translation")
    app.setOrganizationName("CAT")
    app.setOrganizationDomain("context-aware-translation")
    if sys.platform == "darwin":
        # Prefer native macOS style when available (can be missing in mis-packaged builds).
        available_styles = QStyleFactory.keys()
        available = {name.lower(): name for name in available_styles}
        mac_style = available.get("macos") or available.get("macintosh")
        if mac_style:
            app.setStyle(mac_style)

    try:
        from context_aware_translation.ui import i18n
        from context_aware_translation.ui.main_window import MainWindow

        stylesheet = load_stylesheet()
        if stylesheet:
            app.setStyleSheet(stylesheet)

        saved_lang = i18n.get_saved_language()
        if saved_lang:
            i18n.load_translation(app, saved_lang)
        else:
            system_lang = i18n.get_system_language()
            i18n.load_translation(app, system_lang)

        window = MainWindow()
        window.show()
    except Exception:
        _show_startup_error(traceback.format_exc())
        raise

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
