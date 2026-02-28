"""Tests for worker progress-message translation mapping."""

from __future__ import annotations

import context_aware_translation.ui.i18n as i18n


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
