"""Entry point for the PySide6 desktop application."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from . import i18n
from .main_window import MainWindow


def load_stylesheet() -> str:
    """Load the application stylesheet."""
    style_path = Path(__file__).parent / "resources" / "styles.qss"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return ""


def main() -> None:
    """Launch the application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Context-Aware Translation")
    app.setOrganizationName("CAT")
    app.setOrganizationDomain("context-aware-translation")

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
