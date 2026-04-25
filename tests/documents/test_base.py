import inspect
from unittest.mock import MagicMock

import pytest

from context_aware_translation.documents.base import Document


def test_document_is_importable():
    assert Document is not None
    assert inspect.isabstract(Document)


def test_document_load_returns_none_for_empty_db():
    mock_repo = MagicMock()
    mock_repo.get_document_row.return_value = None

    result = Document.load(mock_repo)

    assert result is None
    mock_repo.get_document_row.assert_called_once()


def test_document_load_raises_for_unknown_document_type():
    mock_repo = MagicMock()
    mock_repo.get_document_row.return_value = {
        "document_type": "unknown_type",
        "document_id": 1,
    }

    with pytest.raises(ValueError, match="Unknown document type: unknown_type"):
        Document.load(mock_repo)


def test_document_has_all_abstract_methods():
    abstract_methods = {
        "process_ocr",
        "get_text",
        "is_text_added",
        "mark_text_added",
        "set_text",
        "reembed",
        "export_preserve_structure",
        "can_export",
        "is_ocr_completed",
    }

    actual_abstract_methods = {
        name
        for name, method in inspect.getmembers(Document, predicate=inspect.isfunction)
        if getattr(method, "__isabstractmethod__", False)
    }

    assert actual_abstract_methods == abstract_methods


def test_document_abstract_methods_have_correct_signatures():
    assert hasattr(Document, "process_ocr")
    process_ocr_sig = inspect.signature(Document.process_ocr)
    assert list(process_ocr_sig.parameters.keys()) == [
        "self",
        "llm_client",
        "source_ids",
        "cancel_check",
        "on_item_processed",
    ]

    assert hasattr(Document, "get_text")
    get_text_sig = inspect.signature(Document.get_text)
    assert list(get_text_sig.parameters.keys()) == ["self"]

    assert hasattr(Document, "is_text_added")
    is_text_added_sig = inspect.signature(Document.is_text_added)
    assert list(is_text_added_sig.parameters.keys()) == ["self"]

    assert hasattr(Document, "mark_text_added")
    mark_text_added_sig = inspect.signature(Document.mark_text_added)
    assert list(mark_text_added_sig.parameters.keys()) == ["self"]

    assert hasattr(Document, "set_text")
    set_text_sig = inspect.signature(Document.set_text)
    assert list(set_text_sig.parameters.keys()) == [
        "self",
        "lines",
        "cancel_check",
        "progress_callback",
    ]

    assert hasattr(Document, "export_preserve_structure")
    export_preserve_structure_sig = inspect.signature(Document.export_preserve_structure)
    assert list(export_preserve_structure_sig.parameters.keys()) == ["self", "output_folder"]


def test_document_cannot_be_instantiated():
    mock_repo = MagicMock()

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        Document(mock_repo, 1)


def test_document_has_init_with_correct_signature():
    init_sig = inspect.signature(Document.__init__)
    assert list(init_sig.parameters.keys()) == ["self", "repo", "document_id"]


def test_document_has_load_classmethod():
    assert hasattr(Document, "load")
    assert isinstance(inspect.getattr_static(Document, "load"), classmethod)
    load_sig = inspect.signature(Document.load)
    assert list(load_sig.parameters.keys()) == ["repo", "ocr_config", "translator_config"]


def test_document_load_dispatches_to_text_document():
    from context_aware_translation.documents.text import TextDocument

    mock_repo = MagicMock()
    mock_repo.get_document_row.return_value = {
        "document_type": "text",
        "document_id": 1,
    }

    result = Document.load(mock_repo)

    assert isinstance(result, TextDocument)
    assert result.document_id == 1
    assert result.repo is mock_repo


def test_document_load_dispatches_to_pdf_document():
    from context_aware_translation.documents.pdf import PDFDocument

    mock_repo = MagicMock()
    mock_repo.get_document_row.return_value = {
        "document_type": "pdf",
        "document_id": 2,
    }

    result = Document.load(mock_repo)

    assert isinstance(result, PDFDocument)
    assert result.document_id == 2
    assert result.repo is mock_repo


def test_document_load_dispatches_to_subtitle_document():
    from context_aware_translation.documents.subtitle import SubtitleDocument

    mock_repo = MagicMock()
    mock_repo.get_document_row.return_value = {
        "document_type": "subtitle",
        "document_id": 4,
    }

    result = Document.load(mock_repo)

    assert isinstance(result, SubtitleDocument)
    assert result.document_id == 4
    assert result.repo is mock_repo


def test_document_load_dispatches_to_scanned_book_document():
    from context_aware_translation.documents.scanned_book import ScannedBookDocument

    mock_repo = MagicMock()
    mock_repo.get_document_row.return_value = {
        "document_type": "scanned_book",
        "document_id": 3,
    }

    result = Document.load(mock_repo)

    assert isinstance(result, ScannedBookDocument)
    assert result.document_id == 3
    assert result.repo is mock_repo


def test_document_classes_registry():
    """Test get_document_classes() returns all document types with required methods."""
    from context_aware_translation.documents.base import get_document_classes

    classes = get_document_classes()

    # Verify 6 classes returned (text, subtitle, pdf, scanned_book, manga, epub)
    assert len(classes) == 6

    # Verify all have can_import and do_import methods
    for cls in classes:
        assert hasattr(cls, "can_import"), f"{cls.__name__} missing can_import method"
        assert hasattr(cls, "do_import"), f"{cls.__name__} missing do_import method"
        assert callable(cls.can_import), f"{cls.__name__}.can_import not callable"
        assert callable(cls.do_import), f"{cls.__name__}.do_import not callable"
