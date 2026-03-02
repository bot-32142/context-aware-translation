"""Entry point for the PySide6 desktop application."""

import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QStyleFactory


def load_stylesheet() -> str:
    """Load the application stylesheet."""
    style_path = Path(__file__).parent / "resources" / "styles.qss"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return ""


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
    except Exception:
        # Surface startup failures when running as a packaged GUI app
        # where stderr is typically not visible to end users.
        detail = traceback.format_exc()
        try:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                "Startup Error",
                f"Context-Aware Translation failed to start.\n\nPlease send this traceback to support:\n\n{detail}",
            )
        finally:
            raise

    # Load stylesheet
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)

    # Load translations
    saved_lang = i18n.get_saved_language()
    if saved_lang:
        i18n.load_translation(app, saved_lang)
    else:
        system_lang = i18n.get_system_language()
        i18n.load_translation(app, system_lang)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
