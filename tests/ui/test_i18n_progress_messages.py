"""Tests for worker progress-message translation mapping."""

from __future__ import annotations

import context_aware_translation.ui.i18n as i18n


class _FakeRegistryPath:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def exists(self) -> bool:
        return self._exists


def test_translate_progress_message_static_uses_progress_context(monkeypatch):
    monkeypatch.setattr(i18n, "_translate_with_context", lambda text: f"T:{text}")
    assert i18n.translate_progress_message("Starting OCR...") == "T:Starting OCR..."


def test_translate_progress_message_dynamic_patterns(monkeypatch):
    monkeypatch.setattr(i18n, "_translate_with_context", lambda text: f"T:{text}")
    assert i18n.translate_progress_message("Extracting terms from chunk 2/10") == "T:Extracting terms from chunk 2/10"
    assert i18n.translate_progress_message("Reviewing batch 1/3") == "T:Reviewing batch 1/3"
    assert i18n.translate_progress_message("Translating glossary group 4/9") == "T:Translating glossary group 4/9"
    assert i18n.translate_progress_message("Translating batch 7/20") == "T:Translating batch 7/20"
    assert i18n.translate_progress_message("Translating manga batch 5/8") == "T:Translating manga batch 5/8"
    assert i18n.translate_progress_message("Summarizing term memory 3/7") == "T:Summarizing term memory 3/7"
    assert i18n.translate_progress_message("Collecting glossary term 1/5") == "T:Collecting glossary term 1/5"


def test_translate_progress_message_unknown_passthrough():
    unknown = "some custom status text"
    assert i18n.translate_progress_message(unknown) == unknown


def test_translate_task_block_reason_static_passthrough_without_translator():
    assert i18n.translate_task_block_reason("Task is already running") == "Task is already running"


def test_translate_task_block_reason_pattern_passthrough_without_translator():
    assert i18n.translate_task_block_reason("Book not found: book-1") == "Book not found: book-1"


def test_translate_task_block_reason_code_mapping_without_translator():
    assert i18n.translate_task_block_reason(None, "blocked_claim_conflict") == "Blocked by active task claims"


def test_translate_task_block_reason_unknown_code_humanized():
    assert i18n.translate_task_block_reason(None, "custom_error_code") == "Custom Error Code"


def test_translate_backend_text_runtime_warning_uses_runtime_map(monkeypatch):
    monkeypatch.setattr(i18n.QCoreApplication, "translate", lambda _ctx, text: f"T:{text}")
    assert (
        i18n.translate_backend_text("Image reinsertion is already running for this document.")
        == "T:Image reinsertion is already running for this document."
    )
    assert (
        i18n.translate_backend_text("Another OCR task is already running for this document.")
        == "T:Another OCR task is already running for this document."
    )
    assert (
        i18n.translate_backend_text("Another terms task is already running for this project.")
        == "T:Another terms task is already running for this project."
    )


def test_translate_backend_text_runtime_task_titles_and_queued_messages(monkeypatch):
    translations = {
        "Build terms": "构建术语",
        "Translate and Export": "一键翻译并导出",
        "Translate manga": "翻译漫画",
        "Put text back into images": "将文字重新放回图片",
        "%1 queued.": "%1 已排队",
    }
    monkeypatch.setattr(i18n.QCoreApplication, "translate", lambda _ctx, text: translations.get(text, text))

    assert i18n.translate_backend_text("Build terms") == "构建术语"
    assert i18n.translate_backend_text("Build terms queued.") == "构建术语 已排队"
    assert i18n.translate_backend_text("Translate and Export queued.") == "一键翻译并导出 已排队"
    assert i18n.translate_backend_text("Translate manga queued.") == "翻译漫画 已排队"
    assert i18n.translate_backend_text("Put text back into images queued.") == "将文字重新放回图片 已排队"


def test_translate_progress_label_supports_one_shot_phase_and_title(monkeypatch):
    monkeypatch.setattr(i18n, "_translate_task", lambda text: f"T:{text}")
    assert i18n.translate_progress_label("rare_filter") == "T:Filtering rare terms"
    assert i18n.translate_task_type("translate_and_export") == "T:Translate and Export"


def test_resolve_startup_language_prefers_saved_language(monkeypatch):
    monkeypatch.setattr(i18n, "get_saved_language", lambda: "zh_CN")
    monkeypatch.setattr(i18n, "get_default_registry_db_path", lambda: _FakeRegistryPath(True))
    monkeypatch.setattr(i18n, "save_language", lambda _locale_code: (_ for _ in ()).throw(AssertionError))

    assert i18n.resolve_startup_language() == "zh_CN"


def test_resolve_startup_language_uses_system_language_on_first_run(monkeypatch):
    saved_languages: list[str] = []

    monkeypatch.setattr(i18n, "get_saved_language", lambda: "")
    monkeypatch.setattr(i18n, "get_default_registry_db_path", lambda: _FakeRegistryPath(False))
    monkeypatch.setattr(i18n, "get_system_language", lambda: "zh_CN")
    monkeypatch.setattr(i18n, "save_language", saved_languages.append)

    assert i18n.resolve_startup_language() == "zh_CN"
    assert saved_languages == ["zh_CN"]


def test_resolve_startup_language_falls_back_to_english_after_first_run(monkeypatch):
    monkeypatch.setattr(i18n, "get_saved_language", lambda: "")
    monkeypatch.setattr(i18n, "get_default_registry_db_path", lambda: _FakeRegistryPath(True))
    monkeypatch.setattr(i18n, "get_system_language", lambda: "zh_CN")
    monkeypatch.setattr(i18n, "save_language", lambda _locale_code: (_ for _ in ()).throw(AssertionError))

    assert i18n.resolve_startup_language() == "en"
