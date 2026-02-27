"""Structural checks: TranslationView must not use legacy sync workers or task console."""

from __future__ import annotations

from pathlib import Path

TRANSLATION_VIEW_PATH = Path("context_aware_translation/ui/views/translation_view.py")


def _get_source() -> str:
    return TRANSLATION_VIEW_PATH.read_text(encoding="utf-8")


# ------------------------------------------------------------------
# No SyncTranslationTaskWorker instantiation
# ------------------------------------------------------------------


def test_no_sync_translation_task_worker_import():
    """TranslationView must not import SyncTranslationTaskWorker."""
    source = _get_source()
    assert "SyncTranslationTaskWorker" not in source, (
        "SyncTranslationTaskWorker must not be imported or used in translation_view.py"
    )


def test_no_sync_translation_task_worker_instantiation():
    """TranslationView must not instantiate SyncTranslationTaskWorker."""
    source = _get_source()
    assert "SyncTranslationTaskWorker(" not in source, (
        "SyncTranslationTaskWorker must not be instantiated in translation_view.py"
    )


# ------------------------------------------------------------------
# No TaskConsole
# ------------------------------------------------------------------


def test_no_task_console_import():
    """TranslationView must not import TaskConsole."""
    source = _get_source()
    assert "TaskConsole" not in source, "TaskConsole must not be used in translation_view.py after migration"


def test_no_task_console_attribute_in_class():
    """TranslationView class source must not reference task_console or sync_task_console."""
    source = _get_source()
    assert "task_console" not in source, "task_console attribute must not exist in translation_view.py after migration"
    assert "sync_task_console" not in source, (
        "sync_task_console attribute must not exist in translation_view.py after migration"
    )


# ------------------------------------------------------------------
# No legacy sync_translation submit
# ------------------------------------------------------------------


def test_no_sync_translation_task_type_submitted():
    """translation_view.py must not submit 'sync_translation' task type."""
    source = _get_source()
    assert '"sync_translation"' not in source, (
        "sync_translation task type must not be submitted from translation_view.py"
    )
    assert "'sync_translation'" not in source, (
        "sync_translation task type must not be submitted from translation_view.py"
    )


def test_no_sync_task_id_attribute():
    """_sync_task_id must not be present — sync tracking is removed."""
    source = _get_source()
    assert "_sync_task_id" not in source, "_sync_task_id must not be used in translation_view.py after migration"


def test_no_emitted_sync_translation_done_attribute():
    """_emitted_sync_translation_done must not be present — dedupe set for sync_translation is removed."""
    source = _get_source()
    assert "_emitted_sync_translation_done" not in source, (
        "_emitted_sync_translation_done must not be used in translation_view.py after migration"
    )


# ------------------------------------------------------------------
# No local progress bar for translation execution
# ------------------------------------------------------------------


def test_no_sync_translation_progress_bar():
    """translation_view.py must not reference sync_translation_progress_bar."""
    source = _get_source()
    assert "sync_translation_progress_bar" not in source, (
        "sync_translation_progress_bar must not exist in translation_view.py after migration"
    )


def test_no_sync_translation_section_label():
    """sync_translation_section_label must be removed after migration."""
    source = _get_source()
    assert "sync_translation_section_label" not in source, (
        "sync_translation_section_label must not exist in translation_view.py after migration"
    )


# ------------------------------------------------------------------
# All translation paths go through task_engine.submit_and_start
# ------------------------------------------------------------------


def test_translation_view_uses_submit_and_start_not_raw_worker():
    """TranslationView must use submit_and_start, not raw worker instantiation for translation."""
    source = _get_source()
    assert "submit_and_start" in source, (
        "translation_view.py must use task_engine.submit_and_start for translation tasks"
    )


def test_translation_view_uses_task_status_strip():
    """TranslationView must use TaskStatusStrip instead of TaskConsole."""
    source = _get_source()
    assert "TaskStatusStrip" in source, "TaskStatusStrip must be used in translation_view.py after migration"


# ------------------------------------------------------------------
# Structural: no removed method definitions
# ------------------------------------------------------------------


def test_no_handle_sync_task_update_method():
    """_handle_sync_task_update must be removed after migration."""
    source = _get_source()
    assert "_handle_sync_task_update" not in source, (
        "_handle_sync_task_update method must not exist in translation_view.py after migration"
    )


def test_no_initialize_sync_task_tracking_method():
    """_initialize_sync_task_tracking must be removed after migration."""
    source = _get_source()
    assert "_initialize_sync_task_tracking" not in source, (
        "_initialize_sync_task_tracking method must not exist in translation_view.py after migration"
    )


def test_no_on_sync_task_finished_method():
    """_on_sync_task_finished must be removed after migration."""
    source = _get_source()
    assert "_on_sync_task_finished" not in source, (
        "_on_sync_task_finished method must not exist in translation_view.py after migration"
    )


def test_no_is_sync_translation_running_method():
    """_is_sync_translation_running must be removed after migration."""
    source = _get_source()
    assert "_is_sync_translation_running" not in source, (
        "_is_sync_translation_running method must not exist in translation_view.py after migration"
    )


def test_no_on_task_console_refreshed_method():
    """_on_task_console_refreshed must be removed after migration."""
    source = _get_source()
    assert "_on_task_console_refreshed" not in source, (
        "_on_task_console_refreshed method must not exist in translation_view.py after migration"
    )
