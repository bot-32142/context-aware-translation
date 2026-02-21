"""Internationalization module for the application."""

import re
from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QLibraryInfo, QLocale, QSettings, QTranslator
from PySide6.QtWidgets import QApplication

# Supported languages: locale code -> display name
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh_CN": "简体中文",
}

# Module-level state
_current_translator: QTranslator | None = None
_current_qt_translator: QTranslator | None = None
_current_language: str = "en"


def get_translations_dir() -> Path:
    """Get the directory containing translation files.

    Handles both development and PyInstaller bundled environments.
    """
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "context_aware_translation" / "ui" / "translations"
    return Path(__file__).parent / "translations"


def get_system_language() -> str:
    """Detect the system locale and return the corresponding locale code.

    Tries full locale match (e.g., "zh_CN"), then language-only match (e.g., "zh"),
    finally falls back to "en".
    """
    system_locale = QLocale.system().name()  # e.g., "zh_CN", "en_US"

    # Try full match first
    if system_locale in SUPPORTED_LANGUAGES:
        return system_locale

    # Try language-only match (e.g., "zh" from "zh_TW")
    language_only = system_locale.split("_")[0]
    for locale_code in SUPPORTED_LANGUAGES:
        if locale_code.startswith(language_only):
            return locale_code

    # Fallback to English
    return "en"


def get_saved_language() -> str:
    """Read the saved language preference from QSettings.

    Returns empty string if no preference is saved.
    """
    settings = QSettings("CAT", "Context-Aware Translation")
    saved = settings.value("ui_language", "", type=str)
    # QSettings.value can return object type, ensure it's a string
    saved_str = str(saved) if saved else ""
    return saved_str if saved_str in SUPPORTED_LANGUAGES else ""


def save_language(locale_code: str) -> None:
    """Save the language preference to QSettings."""
    if locale_code not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {locale_code}")
    settings = QSettings("CAT", "Context-Aware Translation")
    settings.setValue("ui_language", locale_code)


def load_translation(app: QApplication, locale_code: str) -> bool:
    """Load and install a translation for the given locale.

    Args:
        app: The QApplication instance
        locale_code: The locale code (e.g., "zh_CN")

    Returns:
        True if translation was loaded successfully, False otherwise.
        Always returns True for "en" (base language).
    """
    global _current_translator, _current_qt_translator, _current_language

    # Remove current translators if any
    if _current_translator is not None:
        app.removeTranslator(_current_translator)
        _current_translator = None
    if _current_qt_translator is not None:
        app.removeTranslator(_current_qt_translator)
        _current_qt_translator = None

    # English is the source language, no translation needed
    if locale_code == "en":
        _current_language = "en"
        return True

    # Validate locale
    if locale_code not in SUPPORTED_LANGUAGES:
        _current_language = "en"
        return False

    # Load translation file
    translations_dir = get_translations_dir()
    translator = QTranslator()
    qm_file = translations_dir / f"{locale_code}.qm"

    if not qm_file.exists():
        _current_language = "en"
        return False

    if translator.load(str(qm_file)):
        app.installTranslator(translator)
        _current_translator = translator
        _current_language = locale_code

        # Best-effort: load Qt base translations (for QDialogButtonBox, etc.)
        qt_translator = QTranslator()
        qt_translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if qt_translator.load(f"qtbase_{locale_code}", qt_translations_path):
            app.installTranslator(qt_translator)
            _current_qt_translator = qt_translator

        return True
    else:
        _current_language = "en"
        return False


def get_current_language() -> str:
    """Return the currently active locale code."""
    return _current_language


def qarg(text: str, *args: object) -> str:
    """Replace Qt-style %1, %2, ... placeholders with provided arguments.

    PySide6's tr() returns a Python str which lacks QString.arg().
    This helper provides equivalent functionality using single-pass
    replacement to avoid double-substitution when arguments contain
    placeholder patterns.
    """

    def _replacer(m: re.Match) -> str:
        idx = int(m.group(1)) - 1
        return str(args[idx]) if idx < len(args) else m.group(0)

    return re.sub(r"%(\d+)", _replacer, text)


# Worker progress messages that need translation.
# Keys are English strings emitted by worker threads; values are markers
# passed through QT_TRANSLATE_NOOP with explicit ProgressMessages context
# so lupdate extracts entries under the same context used at runtime.
_PROGRESS_STATIC = {
    "Starting OCR...": QT_TRANSLATE_NOOP("ProgressMessages", "Starting OCR..."),
    "Extracting terms...": QT_TRANSLATE_NOOP("ProgressMessages", "Extracting terms..."),
    "Reviewing terms...": QT_TRANSLATE_NOOP("ProgressMessages", "Reviewing terms..."),
    "Translating glossary terms...": QT_TRANSLATE_NOOP("ProgressMessages", "Translating glossary terms..."),
    "Translating...": QT_TRANSLATE_NOOP("ProgressMessages", "Translating..."),
    "Preparing glossary export...": QT_TRANSLATE_NOOP("ProgressMessages", "Preparing glossary export..."),
    "Writing glossary file...": QT_TRANSLATE_NOOP("ProgressMessages", "Writing glossary file..."),
}

# Regex patterns for parameterised progress messages.
_PROGRESS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"OCR page (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "OCR page %1/%2"),
    ),
    (
        re.compile(r"Exporting document (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Exporting document %1/%2"),
    ),
    (
        re.compile(r"Summarizing glossary term (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Summarizing glossary term %1/%2"),
    ),
    (
        re.compile(r"Collecting glossary term (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Collecting glossary term %1/%2"),
    ),
    (
        re.compile(r"Translating chunk (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Translating chunk %1/%2"),
    ),
    (
        re.compile(r"Extracting terms from chunk (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Extracting terms from chunk %1/%2"),
    ),
    (
        re.compile(r"Reviewing batch (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Reviewing batch %1/%2"),
    ),
    (
        re.compile(r"Translating glossary group (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Translating glossary group %1/%2"),
    ),
    (
        re.compile(r"Translating batch (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Translating batch %1/%2"),
    ),
    (
        re.compile(r"Translating manga batch (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Translating manga batch %1/%2"),
    ),
]


def _translate_with_context(text: str) -> str:
    """Helper to translate with ProgressMessages context."""
    return QCoreApplication.translate("ProgressMessages", text)


def translate_progress_message(message: str) -> str:
    """Translate a progress message emitted by a worker thread.

    Worker threads must not call tr() (they run outside the GUI thread).
    Instead, they emit plain English strings and this function translates
    them on the UI side using QCoreApplication.translate().
    """
    if message in _PROGRESS_STATIC:
        return _translate_with_context(message)

    for pattern, template in _PROGRESS_PATTERNS:
        m = pattern.fullmatch(message)
        if m:
            return qarg(_translate_with_context(template), *m.groups())

    return message
