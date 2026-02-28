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
_TASK_STATUS_LABELS: dict[str, str] = {
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
_TASK_TYPE_LABELS: dict[str, str] = {
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
_TASK_PHASE_LABELS: dict[str, str] = {
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
_RUNNING_STAGE_LABELS: dict[str, str] = {
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

# ---- Task decision reasons/codes (shown in warnings/tooltips) ----
_TASK_DECISION_REASON_CONTEXT = "TaskDecisionReason"
_TASK_DECISION_CODE_CONTEXT = "TaskDecisionCode"

_TASK_DECISION_REASON_STATIC: dict[str, str] = {
    "All selected documents must be manga type for manga translation.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "All selected documents must be manga type for manga translation."
    ),
    "Already running": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Already running"),
    "Batch translation does not support manga documents.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Batch translation does not support manga documents."
    ),
    "Blocked by active task claims": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Blocked by active task claims"),
    "Book has no documents to translate.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Book has no documents to translate."
    ),
    "Book has no documents.": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Book has no documents."),
    "Cancel requested, cannot run": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Cancel requested, cannot run"),
    "Cannot delete active task": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Cannot delete active task"),
    "Cannot load config for this book. Check that a profile or custom config is assigned.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "Cannot load config for this book. Check that a profile or custom config is assigned.",
    ),
    "Cannot open book database.": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Cannot open book database."),
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
    "No documents selected.": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "No documents selected."),
    "No pending OCR sources found for this document.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "No pending OCR sources found for this document."
    ),
    "No pending OCR sources found for this document. All sources may already be OCR-completed.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "No pending OCR sources found for this document. All sources may already be OCR-completed.",
    ),
    "No terms are pending review.": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "No terms are pending review."),
    "No terms found in glossary. Cannot export empty glossary.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "No terms found in glossary. Cannot export empty glossary."
    ),
    "No translated chunks found. Translate documents before running image reembedding.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT,
        "No translated chunks found. Translate documents before running image reembedding.",
    ),
    "No untranslated terms found.": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "No untranslated terms found."),
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
    "Task already completed": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Task already completed"),
    "Task is already in terminal state": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "Task is already in terminal state"
    ),
    "Task is already running": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Task is already running"),
    "Task is being cancelled": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Task is being cancelled"),
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
    "source_ids must be a list.": QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "source_ids must be a list."),
    "source_ids must be a list[int] or null.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "source_ids must be a list[int] or null."
    ),
    "source_ids must contain only integers.": QT_TRANSLATE_NOOP(
        _TASK_DECISION_REASON_CONTEXT, "source_ids must contain only integers."
    ),
}

_TASK_DECISION_REASON_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Book not found: (.+)"), QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Book not found: %1")),
    (
        re.compile(r"Cannot run task with status: (.+)"),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Cannot run task with status: %1"),
    ),
    (
        re.compile(r"Chunk (\d+) belongs to document (\d+), not (\d+)\."),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Chunk %1 belongs to document %2, not %3."),
    ),
    (
        re.compile(r"Chunk (\d+) not found in database\."),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Chunk %1 not found in database."),
    ),
    (
        re.compile(r"Document type '([^']+)' does not support OCR\."),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Document type '%1' does not support OCR."),
    ),
    (
        re.compile(r"Document type '([^']+)' does not support OCR\. Supported types: (.+)\."),
        QT_TRANSLATE_NOOP(
            _TASK_DECISION_REASON_CONTEXT, "Document type '%1' does not support OCR. Supported types: %2."
        ),
    ),
    (
        re.compile(r"Document type\(s\) (.+) do not support image reembedding\."),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Document type(s) %1 do not support image reembedding."),
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
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Document %1 not found."),
    ),
    (
        re.compile(r"Selected document\(s\) are no longer pending: (.+)"),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Selected document(s) are no longer pending: %1"),
    ),
    (
        re.compile(r"Status (.+) is not autorunnable"),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Status %1 is not autorunnable"),
    ),
    (re.compile(r"Task not found: (.+)"), QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "Task not found: %1")),
    (
        re.compile(r"source_id (\d+) does not belong to document (\d+)\."),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "source_id %1 does not belong to document %2."),
    ),
    (
        re.compile(r"source_ids not found in selected documents: (.+)"),
        QT_TRANSLATE_NOOP(_TASK_DECISION_REASON_CONTEXT, "source_ids not found in selected documents: %1"),
    ),
]

_TASK_DECISION_CODE_LABELS: dict[str, str] = {
    "blocked_claim_conflict": QT_TRANSLATE_NOOP(_TASK_DECISION_CODE_CONTEXT, "Blocked by active task claims"),
    "config_snapshot_unavailable": QT_TRANSLATE_NOOP(
        _TASK_DECISION_CODE_CONTEXT,
        "Cannot load config for this book. Check that a profile or custom config is assigned.",
    ),
    "task_not_found": QT_TRANSLATE_NOOP(_TASK_DECISION_CODE_CONTEXT, "Task not found"),
    "no_terms": QT_TRANSLATE_NOOP(
        _TASK_DECISION_CODE_CONTEXT, "No terms found in glossary. Cannot export empty glossary."
    ),
    "no_review_config": QT_TRANSLATE_NOOP(
        _TASK_DECISION_CODE_CONTEXT, "Review config not set. Please configure review settings."
    ),
    "no_pending_terms": QT_TRANSLATE_NOOP(_TASK_DECISION_CODE_CONTEXT, "No terms are pending review."),
    "stale_selection": QT_TRANSLATE_NOOP(_TASK_DECISION_CODE_CONTEXT, "Selected document(s) are no longer pending."),
    "no_pending_documents": QT_TRANSLATE_NOOP(_TASK_DECISION_CODE_CONTEXT, "No documents are pending glossary build."),
    "blocked_ocr_pending": QT_TRANSLATE_NOOP(_TASK_DECISION_CODE_CONTEXT, "Some selected documents still require OCR."),
    "no_untranslated_terms": QT_TRANSLATE_NOOP(_TASK_DECISION_CODE_CONTEXT, "No untranslated terms found."),
}


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
    reason_text = (reason or "").strip()
    if reason_text:
        return _translate_task_decision_reason(reason_text)

    code_text = (code or "").strip()
    if not code_text or code_text == "ok":
        return ""

    label = _TASK_DECISION_CODE_LABELS.get(code_text)
    if label is not None:
        return QCoreApplication.translate(_TASK_DECISION_CODE_CONTEXT, label)
    return _humanize_token(code_text)


def _humanize_token(value: str) -> str:
    return " ".join(part for part in value.replace("_", " ").strip().split()).title()


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
