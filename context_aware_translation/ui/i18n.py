"""Internationalization module for the application."""

import re
import sys
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP as _QT_TRANSLATE_NOOP,
    QCoreApplication,
    QLibraryInfo,
    QLocale,
    QSettings,
    QTranslator,
)
from PySide6.QtWidgets import QApplication


def QT_TRANSLATE_NOOP(context: str, text: str) -> str:
    return cast(str, _QT_TRANSLATE_NOOP(context, text))


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
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "context_aware_translation" / "ui" / "translations"
    return Path(__file__).parent / "translations"


def get_qt_translations_dirs() -> list[Path]:
    """Return candidate directories for Qt's own translation catalogs."""
    candidates: list[Path] = []

    qt_translations_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    if qt_translations_dir.exists():
        candidates.append(qt_translations_dir)

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled_qt_dir = Path(meipass) / "PySide6" / "Qt" / "translations"
        if bundled_qt_dir.exists() and bundled_qt_dir not in candidates:
            candidates.append(bundled_qt_dir)

    return candidates


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
        for qt_translations_dir in get_qt_translations_dirs():
            if qt_translator.load(f"qtbase_{locale_code}", str(qt_translations_dir)):
                app.installTranslator(qt_translator)
                _current_qt_translator = qt_translator
                break

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
_PROGRESS_STATIC: dict[str, object] = {
    "Starting OCR...": QT_TRANSLATE_NOOP("ProgressMessages", "Starting OCR..."),
    "Extracting terms...": QT_TRANSLATE_NOOP("ProgressMessages", "Extracting terms..."),
    "Reviewing terms...": QT_TRANSLATE_NOOP("ProgressMessages", "Reviewing terms..."),
    "Translating glossary terms...": QT_TRANSLATE_NOOP("ProgressMessages", "Translating glossary terms..."),
    "Translating...": QT_TRANSLATE_NOOP("ProgressMessages", "Translating..."),
    "Preparing glossary export...": QT_TRANSLATE_NOOP("ProgressMessages", "Preparing glossary export..."),
    "Writing glossary file...": QT_TRANSLATE_NOOP("ProgressMessages", "Writing glossary file..."),
}

# Regex patterns for parameterised progress messages.
_PROGRESS_PATTERNS: list[tuple[re.Pattern[str], object]] = [
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
    (
        re.compile(r"Reembedding image (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Reembedding image %1/%2"),
    ),
    (
        re.compile(r"Reembedding manga page (\d+)/(\d+)"),
        QT_TRANSLATE_NOOP("ProgressMessages", "Reembedding manga page %1/%2"),
    ),
]


def _translate_with_context(text: str) -> str:
    """Helper to translate with ProgressMessages context."""
    return QCoreApplication.translate("ProgressMessages", text)


# ---- Task status labels ----
_TASK_STATUS_LABELS: dict[str, object] = {
    "blocked": QT_TRANSLATE_NOOP("TaskLabels", "Blocked"),
    "done": QT_TRANSLATE_NOOP("TaskLabels", "Done"),
    "queued": QT_TRANSLATE_NOOP("TaskLabels", "Queued"),
    "running": QT_TRANSLATE_NOOP("TaskLabels", "Running"),
    "paused": QT_TRANSLATE_NOOP("TaskLabels", "Paused"),
    "cancel_requested": QT_TRANSLATE_NOOP("TaskLabels", "Cancel Requested"),
    "cancelling": QT_TRANSLATE_NOOP("TaskLabels", "Cancelling"),
    "cancelled": QT_TRANSLATE_NOOP("TaskLabels", "Cancelled"),
    "completed": QT_TRANSLATE_NOOP("TaskLabels", "Completed"),
    "completed_with_errors": QT_TRANSLATE_NOOP("TaskLabels", "Completed with Errors"),
    "failed": QT_TRANSLATE_NOOP("TaskLabels", "Failed"),
}

# ---- Task type titles ----
_TASK_TYPE_LABELS: dict[str, object] = {
    "batch_translation": QT_TRANSLATE_NOOP("TaskLabels", "Batch Translation"),
    "glossary_extraction": QT_TRANSLATE_NOOP("TaskLabels", "Glossary Extraction"),
    "glossary_export": QT_TRANSLATE_NOOP("TaskLabels", "Glossary Export"),
    "glossary_review": QT_TRANSLATE_NOOP("TaskLabels", "Glossary Review"),
    "glossary_translation": QT_TRANSLATE_NOOP("TaskLabels", "Glossary Translation"),
    "chunk_retranslation": QT_TRANSLATE_NOOP("TaskLabels", "Chunk Retranslation"),
    "translation_text": QT_TRANSLATE_NOOP("TaskLabels", "Text Translation"),
    "translation_manga": QT_TRANSLATE_NOOP("TaskLabels", "Manga Translation"),
    "ocr": QT_TRANSLATE_NOOP("TaskLabels", "OCR"),
    "image_reembedding": QT_TRANSLATE_NOOP("TaskLabels", "Image Reembedding"),
}

# ---- Task phase labels ----
_TASK_PHASE_LABELS: dict[str, object] = {
    "ocr": QT_TRANSLATE_NOOP("TaskLabels", "OCR"),
    "extract_terms": QT_TRANSLATE_NOOP("TaskLabels", "Extracting terms"),
    "review": QT_TRANSLATE_NOOP("TaskLabels", "Reviewing terms"),
    "translate_glossary": QT_TRANSLATE_NOOP("TaskLabels", "Translating glossary"),
    "translate_chunks": QT_TRANSLATE_NOOP("TaskLabels", "Translating chunks"),
    "reembed": QT_TRANSLATE_NOOP("TaskLabels", "Reembedding images"),
    "export": QT_TRANSLATE_NOOP("TaskLabels", "Exporting"),
    "prepare": QT_TRANSLATE_NOOP("TaskLabels", "Preparing"),
    "translation_submit": QT_TRANSLATE_NOOP("TaskLabels", "Submitting batch jobs"),
    "translation_poll": QT_TRANSLATE_NOOP("TaskLabels", "Polling batch jobs"),
    "translation_validate": QT_TRANSLATE_NOOP("TaskLabels", "Validating batch output"),
    "translation_fallback": QT_TRANSLATE_NOOP("TaskLabels", "Fallback translation"),
    "apply": QT_TRANSLATE_NOOP("TaskLabels", "Applying results"),
    "done": QT_TRANSLATE_NOOP("TaskLabels", "Done"),
}

# ---- Running-stage labels (shown when phase is absent) ----
_RUNNING_STAGE_LABELS: dict[str, object] = {
    "batch_translation": QT_TRANSLATE_NOOP("TaskLabels", "Batch translation"),
    "glossary_extraction": QT_TRANSLATE_NOOP("TaskLabels", "Glossary extraction"),
    "glossary_translation": QT_TRANSLATE_NOOP("TaskLabels", "Glossary translation"),
    "glossary_review": QT_TRANSLATE_NOOP("TaskLabels", "Glossary review"),
    "glossary_export": QT_TRANSLATE_NOOP("TaskLabels", "Glossary export"),
    "translation_text": QT_TRANSLATE_NOOP("TaskLabels", "Text translation"),
    "translation_manga": QT_TRANSLATE_NOOP("TaskLabels", "Manga translation"),
    "chunk_retranslation": QT_TRANSLATE_NOOP("TaskLabels", "Chunk retranslation"),
    "ocr": QT_TRANSLATE_NOOP("TaskLabels", "OCR"),
    "image_reembedding": QT_TRANSLATE_NOOP("TaskLabels", "Image reembedding"),
}

# ---- Scope labels ----
_SCOPE_NO_DOCUMENT = QT_TRANSLATE_NOOP("TaskLabels", "No document scope")
_SCOPE_ALL_DOCUMENTS = QT_TRANSLATE_NOOP("TaskLabels", "All documents")
_SCOPE_ONE_DOCUMENT = QT_TRANSLATE_NOOP("TaskLabels", "1 document")
_SCOPE_N_DOCUMENTS = QT_TRANSLATE_NOOP("TaskLabels", "%1 documents")

# ---- Backend/runtime messages rendered in UI ----
_RUNTIME_MESSAGE_CONTEXT = "RuntimeMessages"

_RUNTIME_STATIC: dict[str, object] = {
    "Async batch translation is unavailable.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Async batch translation is unavailable."
    ),
    "Cannot modify documents while other document tasks are active.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Cannot modify documents while other document tasks are active."
    ),
    "Cannot save while another task is actively modifying this document.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Cannot save while another task is actively modifying this document."
    ),
    "Complete": QT_TRANSLATE_NOOP("RuntimeMessages", "Complete"),
    "Context not ready yet.": QT_TRANSLATE_NOOP("RuntimeMessages", "Context not ready yet."),
    "Export": QT_TRANSLATE_NOOP("RuntimeMessages", "Export"),
    "Image editing needs a shared connection in App Setup.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Image editing needs a shared connection in App Setup."
    ),
    "Image reinsertion blocked.": QT_TRANSLATE_NOOP("RuntimeMessages", "Image reinsertion blocked."),
    "Image reinsertion cancellation requested.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Image reinsertion cancellation requested."
    ),
    "Image reinsertion is already running for this document.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Image reinsertion is already running for this document."
    ),
    "Image reinsertion is blocked.": QT_TRANSLATE_NOOP("RuntimeMessages", "Image reinsertion is blocked."),
    "Inspect images": QT_TRANSLATE_NOOP("RuntimeMessages", "Inspect images"),
    "N/A": QT_TRANSLATE_NOOP("RuntimeMessages", "N/A"),
    "Needs OCR review": QT_TRANSLATE_NOOP("RuntimeMessages", "Needs OCR review"),
    "Needs setup": QT_TRANSLATE_NOOP("RuntimeMessages", "Needs setup"),
    "No document state changed.": QT_TRANSLATE_NOOP("RuntimeMessages", "No document state changed."),
    "No documents were deleted.": QT_TRANSLATE_NOOP("RuntimeMessages", "No documents were deleted."),
    "No image pages are available for OCR in this document.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "No image pages are available for OCR in this document."
    ),
    "No OCR text detected on this page.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "No OCR text detected on this page."
    ),
    "No pending images need reinsertion.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "No pending images need reinsertion."
    ),
    "No translatable units are ready in this document.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "No translatable units are ready in this document."
    ),
    "No translated images are ready for reinsertion.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "No translated images are ready for reinsertion."
    ),
    "Not started": QT_TRANSLATE_NOOP("RuntimeMessages", "Not started"),
    "OCR cancellation requested.": QT_TRANSLATE_NOOP("RuntimeMessages", "OCR cancellation requested."),
    "OCR is already running for this document.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "OCR is already running for this document."
    ),
    "OCR is locked after terms or translation have started for this document.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "OCR is locked after terms or translation have started for this document."
    ),
    "Open": QT_TRANSLATE_NOOP("RuntimeMessages", "Open"),
    "Open Images": QT_TRANSLATE_NOOP("RuntimeMessages", "Open Images"),
    "Open OCR": QT_TRANSLATE_NOOP("RuntimeMessages", "Open OCR"),
    "Open Setup": QT_TRANSLATE_NOOP("RuntimeMessages", "Open Setup"),
    "Open Terms": QT_TRANSLATE_NOOP("RuntimeMessages", "Open Terms"),
    "Open Terms to build terms": QT_TRANSLATE_NOOP("RuntimeMessages", "Open Terms to build terms"),
    "Open Translation": QT_TRANSLATE_NOOP("RuntimeMessages", "Open Translation"),
    "Ready to export": QT_TRANSLATE_NOOP("RuntimeMessages", "Ready to export"),
    "Read text from images": QT_TRANSLATE_NOOP("RuntimeMessages", "Read text from images"),
    "Reinsert Selected is available only for manga and EPUB documents.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Reinsert Selected is available only for manga and EPUB documents."
    ),
    "Retranslate chunk": QT_TRANSLATE_NOOP("RuntimeMessages", "Retranslate chunk"),
    "Retranslate is currently unavailable.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Retranslate is currently unavailable."
    ),
    "Review terms": QT_TRANSLATE_NOOP("RuntimeMessages", "Review terms"),
    "Submit async batch": QT_TRANSLATE_NOOP("RuntimeMessages", "Submit async batch"),
    "Target language is not configured for this project.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Target language is not configured for this project."
    ),
    "The selected image is no longer available.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "The selected image is no longer available."
    ),
    "This page could not be aligned to a translation unit. Rebuild terms after OCR changes.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT,
        "This page could not be aligned to a translation unit. Rebuild terms after OCR changes.",
    ),
    "Translate terms": QT_TRANSLATE_NOOP("RuntimeMessages", "Translate terms"),
    "Translate text": QT_TRANSLATE_NOOP("RuntimeMessages", "Translate text"),
    "Translate this document before putting text back into images.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Translate this document before putting text back into images."
    ),
    "Translated units": QT_TRANSLATE_NOOP("RuntimeMessages", "Translated units"),
    "Translation is already running for this document.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Translation is already running for this document."
    ),
    "Translation is unavailable.": QT_TRANSLATE_NOOP("RuntimeMessages", "Translation is unavailable."),
    "Translation needs a shared connection in App Setup.": QT_TRANSLATE_NOOP(
        _RUNTIME_MESSAGE_CONTEXT, "Translation needs a shared connection in App Setup."
    ),
    "Waiting in order": QT_TRANSLATE_NOOP("RuntimeMessages", "Waiting in order"),
}

_RUNTIME_PATTERNS: list[tuple[re.Pattern[str], object]] = [
    (
        re.compile(r"Blocked by (.+) on Document (\d+)\."),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Blocked by %1 on Document %2."),
    ),
    (
        re.compile(r"Chunk (\d+)"),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Chunk %1"),
    ),
    (
        re.compile(r"Context ready through Document (\d+)\."),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Context ready through Document %1."),
    ),
    (
        re.compile(r"Deleted (\d+) document\(s\), (\d+) sources, and (\d+) chunks\."),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Deleted %1 document(s), %2 sources, and %3 chunks."),
    ),
    (
        re.compile(r"Document (\d+)"),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Document %1"),
    ),
    (
        re.compile(r"Image (\d+)"),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Image %1"),
    ),
    (
        re.compile(r"Imported (\d+) document\(s\); skipped (\d+)\."),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Imported %1 document(s); skipped %2."),
    ),
    (
        re.compile(r"In progress \((\d+)/(\d+)\)"),
        QT_TRANSLATE_NOOP("RuntimeMessages", "In progress (%1/%2)"),
    ),
    (
        re.compile(r"Page (\d+)"),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Page %1"),
    ),
    (
        re.compile(r"Pending \((\d+)\)"),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Pending (%1)"),
    ),
    (
        re.compile(r"Reset (\d+) document\(s\); deleted (\d+) chunks and deleted (\d+) terms\."),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Reset %1 document(s); deleted %2 chunks and deleted %3 terms."),
    ),
    (
        re.compile(r"Waiting for Document (\d+) before continuing in order\."),
        QT_TRANSLATE_NOOP("RuntimeMessages", "Waiting for Document %1 before continuing in order."),
    ),
]

# ---- Task decision reasons/codes (shown in warnings/tooltips) ----
_TASK_DECISION_REASON_CONTEXT = "TaskDecisionReason"
_TASK_DECISION_CODE_CONTEXT = "TaskDecisionCode"

_TASK_DECISION_REASON_STATIC: dict[str, object] = {
    "All selected documents must be manga type for manga translation.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "All selected documents must be manga type for manga translation."
    ),
    "Already running": QT_TRANSLATE_NOOP("TaskDecisionReason", "Already running"),
    "Batch translation does not support manga documents.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Batch translation does not support manga documents."
    ),
    "Blocked by active task claims": QT_TRANSLATE_NOOP("TaskDecisionReason", "Blocked by active task claims"),
    "Book has no documents to translate.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Book has no documents to translate."
    ),
    "Book has no documents.": QT_TRANSLATE_NOOP("TaskDecisionReason", "Book has no documents."),
    "Cancel requested, cannot run": QT_TRANSLATE_NOOP("TaskDecisionReason", "Cancel requested, cannot run"),
    "Cannot delete active task": QT_TRANSLATE_NOOP("TaskDecisionReason", "Cannot delete active task"),
    "Cannot load config for this book. Check that a profile or custom config is assigned.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "Cannot load config for this book. Check that a profile or custom config is assigned.",
    ),
    "Cannot open book database.": QT_TRANSLATE_NOOP("TaskDecisionReason", "Cannot open book database."),
    "Chunk retranslation is interactive-only": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Chunk retranslation is interactive-only"
    ),
    "Claims conflict with active tasks": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Claims conflict with active tasks"
    ),
    "Image reembedding is disabled in current config.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Image reembedding is disabled in current config."
    ),
    "Image reembedding is disabled. Enable OCR image reembedding in your book config.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "Image reembedding is disabled. Enable OCR image reembedding in your book config.",
    ),
    "Manga translation requires explicit user initiation": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Manga translation requires explicit user initiation"
    ),
    "No documents are pending glossary build.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "No documents are pending glossary build."
    ),
    "No documents selected.": QT_TRANSLATE_NOOP("TaskDecisionReason", "No documents selected."),
    "No pending OCR sources found for this document.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "No pending OCR sources found for this document."
    ),
    "No pending OCR sources found for this document. All sources may already be OCR-completed.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "No pending OCR sources found for this document. All sources may already be OCR-completed.",
    ),
    "No terms are pending review.": QT_TRANSLATE_NOOP("TaskDecisionReason", "No terms are pending review."),
    "No terms found in glossary. Cannot export empty glossary.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "No terms found in glossary. Cannot export empty glossary."
    ),
    "No translated chunks found. Translate documents before running image reembedding.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "No translated chunks found. Translate documents before running image reembedding.",
    ),
    "No untranslated terms found.": QT_TRANSLATE_NOOP("TaskDecisionReason", "No untranslated terms found."),
    "OCR requires explicit user initiation": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "OCR requires explicit user initiation"
    ),
    "OCR task requires exactly one document_id in params.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "OCR task requires exactly one document_id in params."
    ),
    "Review config not set. Please configure review settings.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Review config not set. Please configure review settings."
    ),
    "Selected documents include manga type(s). Use translation_manga task instead.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Selected documents include manga type(s). Use translation_manga task instead."
    ),
    "Selected documents no longer exist.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Selected documents no longer exist."
    ),
    "Task already completed": QT_TRANSLATE_NOOP("TaskDecisionReason", "Task already completed"),
    "Task is already in terminal state": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Task is already in terminal state"
    ),
    "Task is already running": QT_TRANSLATE_NOOP("TaskDecisionReason", "Task is already running"),
    "Task is being cancelled": QT_TRANSLATE_NOOP("TaskDecisionReason", "Task is being cancelled"),
    "chunk_id is required for chunk_retranslation": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "chunk_id is required for chunk_retranslation"
    ),
    "chunk_id missing from task payload": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "chunk_id missing from task payload"
    ),
    "document_id is required for chunk_retranslation": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "document_id is required for chunk_retranslation"
    ),
    "document_id missing from task payload": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "document_id missing from task payload"
    ),
    "document_ids must be a list[int] or null.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "document_ids must be a list[int] or null."
    ),
    "document_ids must contain only integers.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "document_ids must contain only integers."
    ),
    "image_reembedding_config is required for image reembedding.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "image_reembedding_config is required for image reembedding."
    ),
    "image_reembedding_config is required for image reembedding. Please configure it in your book settings.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "image_reembedding_config is required for image reembedding. Please configure it in your book settings.",
    ),
    "manga_translator_config is required to translate manga documents.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "manga_translator_config is required to translate manga documents."
    ),
    "manga_translator_config is required to translate manga documents. Please configure it in your book settings.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "manga_translator_config is required to translate manga documents. Please configure it in your book settings.",
    ),
    "ocr_config is required for OCR tasks. Please configure it in your book settings.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "ocr_config is required for OCR tasks. Please configure it in your book settings.",
    ),
    "source_ids must be a list.": QT_TRANSLATE_NOOP("TaskDecisionReason", "source_ids must be a list."),
    "source_ids must be a list[int] or null.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "source_ids must be a list[int] or null."
    ),
    "source_ids must contain only integers.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "source_ids must contain only integers."
    ),
}

_TASK_DECISION_REASON_PATTERNS: list[tuple[re.Pattern[str], object]] = [
    (re.compile(r"Book not found: (.+)"), QT_TRANSLATE_NOOP("TaskDecisionReason", "Book not found: %1")),
    (
        re.compile(r"Cannot run task with status: (.+)"),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "Cannot run task with status: %1"),
    ),
    (
        re.compile(r"Chunk (\d+) belongs to document (\d+), not (\d+)\."),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "Chunk %1 belongs to document %2, not %3."),
    ),
    (
        re.compile(r"Chunk (\d+) not found in database\."),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "Chunk %1 not found in database."),
    ),
    (
        re.compile(r"Document type '([^']+)' does not support OCR\."),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "Document type '%1' does not support OCR."),
    ),
    (
        re.compile(r"Document type '([^']+)' does not support OCR\. Supported types: (.+)\."),
        QT_TRANSLATE_NOOP(
            _TASK_DECISION_REASON_CONTEXT, "Document type '%1' does not support OCR. Supported types: %2."
        ),
    ),
    (
        re.compile(r"Document type\(s\) (.+) do not support image reembedding\."),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "Document type(s) %1 do not support image reembedding."),
    ),
    (
        re.compile(r"Document type\(s\) (.+) do not support image reembedding\. Supported types: (.+)"),
        QT_TRANSLATE_NOOP(
            _TASK_DECISION_REASON_CONTEXT, "Document type(s) %1 do not support image reembedding. Supported types: %2"
        ),
    ),
    (
        re.compile(r"Document (\d+) has pending OCR\. Complete OCR before translating\."),
        QT_TRANSLATE_NOOP(
            _TASK_DECISION_REASON_CONTEXT, "Document %1 has pending OCR. Complete OCR before translating."
        ),
    ),
    (
        re.compile(r"Document (\d+) not found\."),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "Document %1 not found."),
    ),
    (
        re.compile(r"Selected document\(s\) are no longer pending: (.+)"),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "Selected document(s) are no longer pending: %1"),
    ),
    (
        re.compile(r"Status (.+) is not autorunnable"),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "Status %1 is not autorunnable"),
    ),
    (re.compile(r"Task not found: (.+)"), QT_TRANSLATE_NOOP("TaskDecisionReason", "Task not found: %1")),
    (
        re.compile(r"source_id (\d+) does not belong to document (\d+)\."),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "source_id %1 does not belong to document %2."),
    ),
    (
        re.compile(r"source_ids not found in selected documents: (.+)"),
        QT_TRANSLATE_NOOP("TaskDecisionReason", "source_ids not found in selected documents: %1"),
    ),
]

_TASK_DECISION_CODE_LABELS: dict[str, object] = {
    "blocked_claim_conflict": QT_TRANSLATE_NOOP("TaskDecisionCode", "Blocked by active task claims"),
    "config_snapshot_unavailable": QT_TRANSLATE_NOOP(
        _TASK_DECISION_CODE_CONTEXT,
        "Cannot load config for this book. Check that a profile or custom config is assigned.",
    ),
    "task_not_found": QT_TRANSLATE_NOOP("TaskDecisionCode", "Task not found"),
    "no_terms": QT_TRANSLATE_NOOP(
        _TASK_DECISION_CODE_CONTEXT, "No terms found in glossary. Cannot export empty glossary."
    ),
    "no_review_config": QT_TRANSLATE_NOOP(
        _TASK_DECISION_CODE_CONTEXT, "Review config not set. Please configure review settings."
    ),
    "no_pending_terms": QT_TRANSLATE_NOOP("TaskDecisionCode", "No terms are pending review."),
    "stale_selection": QT_TRANSLATE_NOOP("TaskDecisionCode", "Selected document(s) are no longer pending."),
    "no_pending_documents": QT_TRANSLATE_NOOP("TaskDecisionCode", "No documents are pending glossary build."),
    "blocked_ocr_pending": QT_TRANSLATE_NOOP("TaskDecisionCode", "Some selected documents still require OCR."),
    "no_untranslated_terms": QT_TRANSLATE_NOOP("TaskDecisionCode", "No untranslated terms found."),
}

_TASK_DECISION_WRAPPED_REASON_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Submit rejected: (?P<reason>.+)"),
    re.compile(r"Action [^:]+ not allowed for task [^:]+: (?P<reason>.+)"),
    re.compile(r"Cannot (?:re)?run task [^:]+: (?P<reason>.+)"),
    re.compile(r"Run validation failed for task [^:]+: code=(?P<code>[^,]+), reason=(?P<reason>.+)"),
    re.compile(r"strict-start failed: [^:]+: (?P<reason>.+)"),
]


def _translate_task(text: str) -> str:
    return QCoreApplication.translate("TaskLabels", text)


def _translate_task_decision_reason(reason: str) -> str:
    label = _TASK_DECISION_REASON_STATIC.get(reason)
    if label is not None:
        return QCoreApplication.translate(_TASK_DECISION_REASON_CONTEXT, label)

    for pattern, template in _TASK_DECISION_REASON_PATTERNS:
        matched = pattern.fullmatch(reason)
        if matched:
            return qarg(QCoreApplication.translate(_TASK_DECISION_REASON_CONTEXT, template), *matched.groups())
    return reason


def translate_task_status(status: str) -> str:
    """Translate a task status string for display."""
    label = _TASK_STATUS_LABELS.get(status)
    return _translate_task(label) if label is not None else status


def translate_task_type(task_type: str) -> str:
    """Translate a task type key for display."""
    label = _TASK_TYPE_LABELS.get(task_type)
    return _translate_task(label) if label is not None else task_type


def translate_task_phase(phase: str) -> str:
    """Translate a task phase key for display."""
    label = _TASK_PHASE_LABELS.get(phase)
    return _translate_task(label) if label is not None else _humanize_token(phase)


def translate_running_stage(task_type: str) -> str:
    """Translate a running-stage label (used when phase is absent)."""
    label = _RUNNING_STAGE_LABELS.get(task_type)
    return _translate_task(label) if label is not None else ""


def translate_runtime_text(text: str) -> str:
    """Translate backend/runtime English text shown directly in the UI."""
    label = _RUNTIME_STATIC.get(text)
    if label is not None:
        return QCoreApplication.translate(_RUNTIME_MESSAGE_CONTEXT, label)

    for pattern, template in _RUNTIME_PATTERNS:
        matched = pattern.fullmatch(text)
        if matched is None:
            continue
        groups = list(matched.groups())
        template_text = cast(str, template)
        if template_text == "Blocked by %1 on Document %2.":
            groups[0] = translate_runtime_text(groups[0])
        return qarg(QCoreApplication.translate(_RUNTIME_MESSAGE_CONTEXT, template_text), *groups)
    return text


def translate_backend_text(text: str, code: str | None = None) -> str:
    """Translate backend messages, blockers, and warnings for display."""
    if not text:
        return ""
    translated = translate_task_block_reason(text, code=code)
    if translated != text:
        return translated
    translated = translate_progress_message(text)
    if translated != text:
        return translated
    return translate_runtime_text(text)


def translate_progress_label(label: str | None) -> str:
    """Translate progress labels from tasks or backend summaries."""
    if not label:
        return ""
    task_phase = _TASK_PHASE_LABELS.get(label)
    if task_phase is not None:
        return _translate_task(cast(str, task_phase))
    translated = translate_progress_message(label)
    if translated != label:
        return translated
    return translate_runtime_text(label)


def translate_scope_label(document_count: int | None) -> str:
    """Translate a scope label based on document count.

    None means no document scope, 0 means all documents.
    """
    if document_count is None:
        return _translate_task(_SCOPE_NO_DOCUMENT)
    if document_count == 0:
        return _translate_task(_SCOPE_ALL_DOCUMENTS)
    if document_count == 1:
        return _translate_task(_SCOPE_ONE_DOCUMENT)
    return qarg(_translate_task(_SCOPE_N_DOCUMENTS), document_count)


def translate_task_block_reason(reason: str | None, code: str | None = None) -> str:
    """Translate backend task preflight denial reason/code for UI display."""
    reason_text, code_text = _unwrap_task_reason((reason or "").strip(), code)
    if reason_text:
        translated_reason = _translate_task_decision_reason(reason_text)
        if translated_reason != reason_text:
            return translated_reason
        if code_text and code_text != "ok":
            label = _TASK_DECISION_CODE_LABELS.get(code_text)
            if label is not None:
                return QCoreApplication.translate(_TASK_DECISION_CODE_CONTEXT, cast(str, label))
        return translated_reason

    if code_text and code_text != "ok":
        label = _TASK_DECISION_CODE_LABELS.get(code_text)
        if label is not None:
            return QCoreApplication.translate(_TASK_DECISION_CODE_CONTEXT, cast(str, label))
        return _humanize_token(code_text)
    return ""


def _humanize_token(value: str) -> str:
    return " ".join(part for part in value.replace("_", " ").strip().split()).title()


def _unwrap_task_reason(reason: str, code: str | None) -> tuple[str, str | None]:
    reason_text = reason.strip()
    code_text = (code or "").strip() or None

    while reason_text:
        unwrapped = False
        for pattern in _TASK_DECISION_WRAPPED_REASON_PATTERNS:
            matched = pattern.fullmatch(reason_text)
            if matched is None:
                continue
            groups = matched.groupdict()
            extracted_code = str(groups.get("code") or "").strip()
            next_reason = str(groups.get("reason") or "").strip()
            if extracted_code and not code_text:
                code_text = extracted_code
            if not next_reason or next_reason == reason_text:
                return reason_text, code_text
            reason_text = next_reason
            unwrapped = True
            break
        if not unwrapped:
            break
    return reason_text, code_text


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
            return qarg(_translate_with_context(cast(str, template)), *m.groups())

    return message
