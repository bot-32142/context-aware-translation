"""Tests for ocr_required_for_translation flag behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.documents.epub import EPUBDocument
from context_aware_translation.documents.manga import MangaDocument
from context_aware_translation.documents.pdf import PDFDocument
from context_aware_translation.documents.scanned_book import ScannedBookDocument
from context_aware_translation.documents.text import TextDocument
from context_aware_translation.workflow.service import WorkflowService

# =========================================================================
# Flag value tests
# =========================================================================


def test_epub_ocr_not_required_for_translation():
    assert EPUBDocument.ocr_required_for_translation is False


def test_text_ocr_not_required_for_translation():
    assert TextDocument.ocr_required_for_translation is False


@pytest.mark.parametrize(
    "doc_cls",
    [PDFDocument, ScannedBookDocument, MangaDocument],
    ids=["pdf", "scanned_book", "manga"],
)
def test_image_documents_require_ocr_for_translation(doc_cls: type) -> None:
    assert doc_cls.ocr_required_for_translation is True


# =========================================================================
# Workflow integration tests
# =========================================================================


def _make_service() -> WorkflowService:
    config = MagicMock()
    config.ocr_config = None
    config.translator_config = SimpleNamespace(chunk_size=500)

    manager = MagicMock()
    manager.add_text = MagicMock()

    return WorkflowService(
        config=config,
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=manager,
        db=MagicMock(),
        document_repo=MagicMock(),
    )


@pytest.mark.asyncio
async def test_epub_with_pending_ocr_proceeds_through_process_document():
    """EPUB with incomplete OCR should NOT raise ValueError."""
    service = _make_service()

    document = MagicMock()
    document.document_id = 1
    document.document_type = "epub"
    document.ocr_required_for_translation = False
    document.is_ocr_completed.return_value = False
    document.is_text_added.return_value = False
    document.get_text.return_value = "Hello world"
    document.mark_text_added = MagicMock()

    with patch.object(service, "_load_documents", return_value=[document]):
        await service._process_document()

    document.get_text.assert_called_once()
    document.mark_text_added.assert_called_once()


@pytest.mark.asyncio
async def test_non_epub_with_pending_ocr_raises_error():
    """Non-EPUB document with incomplete OCR should raise ValueError."""
    service = _make_service()

    document = MagicMock()
    document.document_id = 1
    document.document_type = "scanned_book"
    document.ocr_required_for_translation = True
    document.is_ocr_completed.return_value = False

    with (
        patch.object(service, "_load_documents", return_value=[document]),
        pytest.raises(ValueError, match="has not completed OCR"),
    ):
        await service._process_document()


@pytest.mark.asyncio
async def test_epub_with_completed_ocr_also_works():
    """EPUB with completed OCR should proceed normally."""
    service = _make_service()

    document = MagicMock()
    document.document_id = 1
    document.document_type = "epub"
    document.ocr_required_for_translation = False
    document.is_ocr_completed.return_value = True
    document.is_text_added.return_value = False
    document.get_text.return_value = "Hello world"
    document.mark_text_added = MagicMock()

    with patch.object(service, "_load_documents", return_value=[document]):
        await service._process_document()

    document.get_text.assert_called_once()
