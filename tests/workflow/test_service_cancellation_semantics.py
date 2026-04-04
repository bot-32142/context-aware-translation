from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_aware_translation.config import TranslatorBatchConfig
from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
from context_aware_translation.workflow.ops import (
    bootstrap_ops,
    export_ops,
    glossary_ops,
    ocr_ops,
    translation_ops,
)
from context_aware_translation.workflow.runtime import WorkflowContext


@pytest.mark.asyncio
async def test_translate_late_cancel_after_completion_reports_success():
    state = {"completed": False}

    async def _translate_chunks(**_kwargs) -> None:
        state["completed"] = True

    config = MagicMock()
    config.translator_config = SimpleNamespace(concurrency=2, num_of_chunks_per_llm_call=4)

    manager = MagicMock()
    manager.detect_language = AsyncMock()
    manager.translate_chunks = AsyncMock(side_effect=_translate_chunks)

    document_repo = MagicMock()
    document_repo.list_documents.return_value = [{"document_id": 1, "document_type": "text"}]

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=MagicMock(),
        document_repo=document_repo,
    )

    def cancel_check() -> bool:
        return state["completed"]

    with patch.object(bootstrap_ops, "process_document", new=AsyncMock()):
        await translation_ops.translate(service, cancel_check=cancel_check)
    manager.detect_language.assert_awaited_once()
    manager.translate_chunks.assert_awaited_once()


@pytest.mark.asyncio
async def test_translate_uses_regular_chunk_path_even_when_batch_config_present():
    config = MagicMock()
    config.translator_config = SimpleNamespace(concurrency=2, num_of_chunks_per_llm_call=4)
    config.translator_batch_config = TranslatorBatchConfig(
        provider="gemini_ai_studio",
        api_key="k",
        model="gemini-2.5-flash",
    )

    manager = MagicMock()
    manager.detect_language = AsyncMock()
    manager.translate_chunks = AsyncMock()

    document_repo = MagicMock()
    document_repo.list_documents.return_value = [{"document_id": 1, "document_type": "text"}]

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=MagicMock(),
        document_repo=document_repo,
    )

    with patch.object(bootstrap_ops, "process_document", new=AsyncMock()):
        await translation_ops.translate(service)

    manager.translate_chunks.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_ocr_late_cancel_after_processing_reports_success():
    state = {"completed": False}

    async def _process_ocr(_llm_client, _source_ids, cancel_check=None) -> int:  # noqa: ANN001
        _ = cancel_check
        state["completed"] = True
        return 1

    config = MagicMock()
    config.ocr_config = object()

    document = MagicMock()
    document.document_id = 42
    document.process_ocr = AsyncMock(side_effect=_process_ocr)

    document_repo = MagicMock()
    document_repo.get_document_sources_needing_ocr.return_value = [{"source_id": 10}]

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=MagicMock(),
        db=MagicMock(),
        document_repo=document_repo,
    )

    def cancel_check() -> bool:
        return state["completed"]

    processed = await ocr_ops.run_ocr(
        service,
        document_loader=lambda *_args, **_kwargs: [document],
        cancel_check=cancel_check,
    )

    assert processed == 1


@pytest.mark.asyncio
async def test_translate_glossary_late_cancel_after_completion_reports_success():
    state = {"completed": False}

    async def _translate_terms(**_kwargs) -> None:
        state["completed"] = True

    config = MagicMock()
    config.glossary_config = SimpleNamespace(concurrency=3)
    config.llm_concurrency = 8

    manager = MagicMock()
    manager.translate_terms = AsyncMock(side_effect=_translate_terms)

    db = MagicMock()
    db.get_source_language.return_value = "ja"

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=db,
        document_repo=MagicMock(),
    )

    def cancel_check() -> bool:
        return state["completed"]

    await glossary_ops.translate_glossary(service, cancel_check=cancel_check)
    db.get_source_language.assert_not_called()
    manager.translate_terms.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_terms_late_cancel_after_completion_reports_success():
    state = {"completed": False}

    async def _review_terms(**_kwargs) -> None:
        state["completed"] = True

    config = MagicMock()
    config.review_config = SimpleNamespace(concurrency=2)

    manager = MagicMock()
    manager.review_terms = AsyncMock(side_effect=_review_terms)

    db = MagicMock()
    db.get_source_language.return_value = "ja"

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=db,
        document_repo=MagicMock(),
    )

    def cancel_check() -> bool:
        return state["completed"]

    await glossary_ops.review_terms(service, cancel_check=cancel_check)
    db.get_source_language.assert_not_called()
    manager.review_terms.assert_awaited_once()


@pytest.mark.asyncio
async def test_translate_glossary_detects_source_language_from_terms_when_missing():
    config = MagicMock()
    config.glossary_config = SimpleNamespace(concurrency=3)
    config.llm_concurrency = 8

    detector = MagicMock()
    detector.detect = AsyncMock(return_value="ja")

    manager = MagicMock()
    manager.source_language_detector = detector
    manager.translate_terms = AsyncMock(side_effect=[ValueError("source language not found"), None])
    manager.detect_language = AsyncMock(side_effect=ValueError("no text chunks found"))

    db = MagicMock()
    db.get_source_language.return_value = None
    db.list_terms.return_value = [
        SimpleNamespace(key="用語", descriptions={"imported": "説明テキスト"}),
        SimpleNamespace(key="二つ目", descriptions={}),
    ]

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=db,
        document_repo=MagicMock(),
    )
    with patch("context_aware_translation.workflow.ops.bootstrap_ops.load_documents", return_value=[]):
        await glossary_ops.translate_glossary(service, cancel_check=None)

    detector.detect.assert_awaited_once()
    db.set_source_language.assert_called_once_with("ja")
    assert manager.translate_terms.await_count == 2


@pytest.mark.asyncio
async def test_translate_glossary_uses_ready_non_ocr_documents_for_language_detection():
    config = MagicMock()
    config.glossary_config = SimpleNamespace(concurrency=3)
    config.llm_concurrency = 8
    config.translator_config = SimpleNamespace(chunk_size=300)

    manager = MagicMock()
    manager.translate_terms = AsyncMock(side_effect=[ValueError("source language not found"), None])
    manager.detect_language = AsyncMock()
    manager.add_text = MagicMock()
    manager.source_language_detector = MagicMock()
    manager.source_language_detector.detect = AsyncMock(return_value="ja")

    db = MagicMock()
    db.get_source_language.return_value = None
    db.list_terms.return_value = []

    pending_ocr_doc = MagicMock()
    pending_ocr_doc.document_id = 1
    pending_ocr_doc.document_type = "manga"
    pending_ocr_doc.ocr_required_for_translation = True
    pending_ocr_doc.is_ocr_completed.return_value = False
    pending_ocr_doc.is_text_added.return_value = False

    ready_text_doc = MagicMock()
    ready_text_doc.document_id = 2
    ready_text_doc.document_type = "text"
    ready_text_doc.ocr_required_for_translation = False
    ready_text_doc.is_ocr_completed.return_value = False
    ready_text_doc.is_text_added.return_value = False
    ready_text_doc.get_text.return_value = "これはテストです"
    ready_text_doc.mark_text_added = MagicMock()

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=db,
        document_repo=MagicMock(),
    )
    with patch(
        "context_aware_translation.workflow.ops.bootstrap_ops.load_documents",
        return_value=[ready_text_doc, pending_ocr_doc],
    ):
        await glossary_ops.translate_glossary(service, cancel_check=None)

    manager.add_text.assert_called_once_with(
        text="これはテストです",
        max_token_size_per_chunk=300,
        document_id=2,
        document_type="text",
    )
    ready_text_doc.mark_text_added.assert_called_once()
    pending_ocr_doc.get_text.assert_not_called()
    manager.detect_language.assert_awaited_once()
    db.list_terms.assert_not_called()
    assert manager.translate_terms.await_count == 2


@pytest.mark.asyncio
async def test_ensure_glossary_source_language_propagates_non_missing_detect_language_errors():
    config = MagicMock()
    config.translator_config = SimpleNamespace(chunk_size=300)

    manager = MagicMock()
    manager.detect_language = AsyncMock(side_effect=ValueError("LLM unavailable"))
    manager.add_text = MagicMock()

    db = MagicMock()
    db.get_source_language.return_value = None

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=db,
        document_repo=MagicMock(),
    )
    with (
        patch("context_aware_translation.workflow.ops.bootstrap_ops.load_documents", return_value=[]),
        pytest.raises(ValueError, match="LLM unavailable"),
    ):
        await bootstrap_ops.ensure_glossary_source_language(service, cancel_check=None)


@pytest.mark.asyncio
async def test_translate_builds_context_tree_and_forwards_force_flag():
    config = MagicMock()
    config.translator_config = SimpleNamespace(concurrency=2, num_of_chunks_per_llm_call=4)

    manager = MagicMock()
    manager.detect_language = AsyncMock()
    manager.translate_chunks = AsyncMock()

    document_repo = MagicMock()
    document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "text"},
        {"document_id": 2, "document_type": "manga"},
    ]

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=MagicMock(),
        document_repo=document_repo,
    )

    with patch.object(bootstrap_ops, "process_document", new=AsyncMock()):
        await translation_ops.translate(service, document_ids=[2], force=True)

    manager.detect_language.assert_awaited_once()
    manager.build_context_tree.assert_called_once_with(cancel_check=None, progress_callback=None)
    manager.translate_chunks.assert_awaited_once()
    call_kwargs = manager.translate_chunks.await_args.kwargs
    assert call_kwargs["doc_type_by_id"] == {2: "manga"}
    assert call_kwargs["force"] is True


@pytest.mark.asyncio
async def test_translate_builds_context_tree():
    config = MagicMock()
    config.translator_config = SimpleNamespace(concurrency=2, num_of_chunks_per_llm_call=4)

    manager = MagicMock()
    manager.detect_language = AsyncMock()
    manager.translate_chunks = AsyncMock()

    document_repo = MagicMock()
    document_repo.list_documents.return_value = [{"document_id": 7, "document_type": "text"}]

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=MagicMock(),
        document_repo=document_repo,
    )

    with patch.object(bootstrap_ops, "process_document", new=AsyncMock()):
        await translation_ops.translate(service)

    manager.detect_language.assert_awaited_once()
    manager.build_context_tree.assert_called_once_with(cancel_check=None, progress_callback=None)
    manager.translate_chunks.assert_awaited_once()


@pytest.mark.asyncio
async def test_retranslate_chunk_forwards_progress_and_reports_single_chunk_completion():
    progress_updates: list[ProgressUpdate] = []

    def _build_context_tree(**kwargs):  # noqa: ANN003
        callback = kwargs["progress_callback"]
        assert callback is not None
        callback(
            ProgressUpdate(
                step=WorkflowStep.TERM_MEMORY,
                current=1,
                total=2,
                message="Summarizing term memory 1/2",
            )
        )

    chunk = SimpleNamespace(chunk_id=42, text="source text", translation=None, is_translated=False)
    term = SimpleNamespace(ignored=False)

    config = MagicMock()
    config.translator_config = SimpleNamespace(concurrency=2, num_of_chunks_per_llm_call=4)

    manager = MagicMock()
    manager.detect_language = AsyncMock()
    manager.build_context_tree.side_effect = _build_context_tree
    manager.term_repo.list_keyed_context.return_value = [term]
    manager.build_batch_request_payload.return_value = (["source text"], ["term"])
    manager.chunk_translator.translate = AsyncMock(return_value=["translated"])

    db = MagicMock()
    db.get_chunk_by_id.return_value = chunk
    db.get_source_language.return_value = "Japanese"

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=db,
        document_repo=MagicMock(),
    )

    with patch.object(bootstrap_ops, "process_document", new=AsyncMock()):
        translated = await translation_ops.retranslate_chunk(
            service,
            chunk_id=42,
            document_id=7,
            progress_callback=progress_updates.append,
        )

    assert translated == "translated"
    manager.build_context_tree.assert_called_once_with(
        cancel_check=None,
        progress_callback=progress_updates.append,
    )
    assert [(update.step, update.current, update.total) for update in progress_updates] == [
        (WorkflowStep.TERM_MEMORY, 1, 2),
        (WorkflowStep.TRANSLATE_CHUNKS, 0, 1),
        (WorkflowStep.TRANSLATE_CHUNKS, 1, 1),
    ]
    manager.chunk_translator.translate.assert_awaited_once_with(
        ["source text"],
        ["term"],
        "Japanese",
        cancel_check=None,
    )


@pytest.mark.asyncio
async def test_translate_does_not_preflight_earlier_stack_for_text_selection():
    config = MagicMock()
    config.translator_config = SimpleNamespace(concurrency=2, num_of_chunks_per_llm_call=4)

    manager = MagicMock()
    manager.detect_language = AsyncMock()
    manager.translate_chunks = AsyncMock()

    document_repo = MagicMock()
    document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "text"},
        {"document_id": 2, "document_type": "text"},
        {"document_id": 3, "document_type": "text"},
    ]

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=MagicMock(),
        document_repo=document_repo,
    )
    with patch.object(bootstrap_ops, "process_document", new=AsyncMock()) as process_document:
        await translation_ops.translate(service, document_ids=[2])

    manager.detect_language.assert_awaited_once()
    process_document.assert_awaited_once_with(service, [2], cancel_check=None)
    manager.translate_chunks.assert_awaited_once()
    assert manager.translate_chunks.await_args.kwargs["doc_type_by_id"] == {2: "text"}


@pytest.mark.asyncio
async def test_translate_preflights_stack_for_ocr_required_selection():
    config = MagicMock()
    config.translator_config = SimpleNamespace(concurrency=2, num_of_chunks_per_llm_call=4)

    manager = MagicMock()
    manager.detect_language = AsyncMock()
    manager.translate_chunks = AsyncMock()

    document_repo = MagicMock()
    document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "pdf"},
        {"document_id": 2, "document_type": "manga"},
        {"document_id": 3, "document_type": "text"},
    ]

    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=MagicMock(),
        document_repo=document_repo,
    )
    with patch.object(bootstrap_ops, "process_document", new=AsyncMock()) as process_document:
        await translation_ops.translate(service, document_ids=[2])

    manager.detect_language.assert_awaited_once()
    process_document.assert_awaited_once_with(service, [1, 2], cancel_check=None)
    manager.translate_chunks.assert_awaited_once()
    assert manager.translate_chunks.await_args.kwargs["doc_type_by_id"] == {2: "manga"}


class _FakeExportDocument:
    document_type = "text"
    supported_export_formats = ["txt"]
    export_calls: list[tuple[list[_FakeExportDocument], str, str]] = []

    def __init__(self, document_id: int = 1) -> None:
        self.document_id = document_id
        self.received_lines: list[str] | None = None

    def can_export(self, _export_format: str) -> bool:
        return True

    def get_text(self) -> str:
        return "original\ntext\n"

    async def set_text(self, lines: list[str], **_kwargs) -> None:  # noqa: ANN003
        self.received_lines = list(lines)

    @classmethod
    def export_merged(cls, documents, export_format, file_path) -> None:  # noqa: ANN001
        cls.export_calls.append((list(documents), str(export_format), str(file_path)))


class _FakeMangaExportDocument(_FakeExportDocument):
    document_type = "manga"


@pytest.mark.asyncio
async def test_export_strict_mode_raises_for_untranslated_chunks(tmp_path):
    config = MagicMock()
    config.image_reembedding_config = None

    manager = MagicMock()
    manager.get_translated_lines.side_effect = ValueError("Cannot export: chunks [2] are not translated yet")

    fake_doc = _FakeExportDocument()
    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=MagicMock(),
        document_repo=MagicMock(),
    )
    with (
        patch("context_aware_translation.workflow.ops.bootstrap_ops.load_documents", return_value=[fake_doc]),
        pytest.raises(ValueError, match="not translated"),
    ):
        await export_ops.export(
            service,
            file_path=tmp_path / "out.txt",
            export_format="txt",
            allow_original_fallback=False,
        )

    assert fake_doc.received_lines is None


@pytest.mark.asyncio
async def test_export_fallback_mode_merges_translated_and_original_chunks(tmp_path):
    config = MagicMock()
    config.image_reembedding_config = None

    manager = MagicMock()
    manager.get_translated_lines.side_effect = ValueError("Cannot export: chunks [2] are not translated yet")

    db = MagicMock()
    db.list_chunks.return_value = [
        SimpleNamespace(chunk_id=1, text="hello\n", translation="hola\n", is_translated=True),
        SimpleNamespace(chunk_id=2, text="world\n", translation=None, is_translated=False),
    ]

    fake_doc = _FakeExportDocument()
    _FakeExportDocument.export_calls = []
    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=db,
        document_repo=MagicMock(),
    )
    with patch("context_aware_translation.workflow.ops.bootstrap_ops.load_documents", return_value=[fake_doc]):
        await export_ops.export(
            service,
            file_path=tmp_path / "out.txt",
            export_format="txt",
            allow_original_fallback=True,
        )

    assert fake_doc.received_lines == ["hola", "world", ""]
    assert _FakeExportDocument.export_calls


@pytest.mark.asyncio
async def test_export_fallback_mode_for_manga_keeps_untranslated_pages_unreembedded(tmp_path):
    config = MagicMock()
    config.image_reembedding_config = None

    manager = MagicMock()
    manager.get_translated_lines.side_effect = ValueError("Cannot export: chunks [2] are not translated yet")

    db = MagicMock()
    db.list_chunks.return_value = [
        SimpleNamespace(chunk_id=1, text="JP PAGE 1", translation="EN PAGE 1", is_translated=True),
        SimpleNamespace(chunk_id=2, text="JP PAGE 2", translation=None, is_translated=False),
    ]

    fake_doc = _FakeMangaExportDocument()
    _FakeMangaExportDocument.export_calls = []
    service = WorkflowContext(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=db,
        document_repo=MagicMock(),
    )
    with patch("context_aware_translation.workflow.ops.bootstrap_ops.load_documents", return_value=[fake_doc]):
        await export_ops.export(
            service,
            file_path=tmp_path / "out.cbz",
            export_format="txt",
            allow_original_fallback=True,
        )

    # Untranslated manga page should stay empty so reembedding is skipped.
    assert fake_doc.received_lines == ["EN PAGE 1", ""]
    assert _FakeMangaExportDocument.export_calls
