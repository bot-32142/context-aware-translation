from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from context_aware_translation.ui.views.reembedding_view import ReembeddingView


def _chunk(*, chunk_id: int, text: str, translation: str | None, is_translated: bool) -> SimpleNamespace:
    return SimpleNamespace(
        chunk_id=chunk_id,
        text=text,
        translation=translation,
        is_translated=is_translated,
    )


def _make_view(doc_type: str, chunks: list[SimpleNamespace]) -> ReembeddingView:
    term_db = MagicMock()
    term_db.list_chunks.return_value = chunks
    return SimpleNamespace(_current_doc_type=doc_type, term_db=term_db)  # type: ignore[return-value]


def test_get_translated_lines_text_doc_returns_empty_when_fully_untranslated() -> None:
    view = _make_view(
        "pdf",
        [
            _chunk(chunk_id=2, text="world\n", translation=None, is_translated=False),
            _chunk(chunk_id=1, text="hello\n", translation=None, is_translated=False),
        ],
    )

    assert ReembeddingView._get_translated_lines_with_fallback(view, 1) == []


def test_get_translated_lines_text_doc_keeps_partial_fallback_behavior() -> None:
    view = _make_view(
        "epub",
        [
            _chunk(chunk_id=1, text="hello\n", translation="hola\n", is_translated=True),
            _chunk(chunk_id=2, text="world\n", translation=None, is_translated=False),
        ],
    )

    assert ReembeddingView._get_translated_lines_with_fallback(view, 1) == ["hola", "world", ""]


def test_get_translated_lines_manga_keeps_empty_for_untranslated_chunks() -> None:
    view = _make_view(
        "manga",
        [
            _chunk(chunk_id=1, text="JP PAGE 1", translation="EN PAGE 1", is_translated=True),
            _chunk(chunk_id=2, text="JP PAGE 2", translation=None, is_translated=False),
        ],
    )

    assert ReembeddingView._get_translated_lines_with_fallback(view, 1) == ["EN PAGE 1", ""]


def test_collect_manga_items_skips_pages_without_ocr_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeMangaDocument:
        def __init__(self) -> None:
            self.document_id = 1
            self._page_translations = {10: "EN PAGE 1", 12: "EN PAGE 3"}

    from context_aware_translation.documents import manga as manga_module

    monkeypatch.setattr(manga_module, "MangaDocument", _FakeMangaDocument)

    view = SimpleNamespace()
    view.document_repo = MagicMock()
    view.document_repo.get_document_sources.return_value = [
        {"source_id": 10, "sequence_number": 0, "ocr_json": '{"text":"jp1"}', "binary_content": b"img1"},
        {"source_id": 11, "sequence_number": 1, "ocr_json": '{"text":""}', "binary_content": b"img2"},
        {"source_id": 12, "sequence_number": 2, "ocr_json": '{"text":"jp3"}', "binary_content": b"img3"},
    ]
    view._reembedded_images = {0: (b"r1", "image/png"), 2: (b"r3", "image/png")}

    items = ReembeddingView._collect_manga_items(view, _FakeMangaDocument())

    assert [item.source_id for item in items] == [10, 12]
    assert [item.element_idx for item in items] == [0, 2]
    assert items[0].reembedded_image_bytes == b"r1"
    assert items[1].reembedded_image_bytes == b"r3"


def test_collect_manga_items_skips_pages_without_translated_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeMangaDocument:
        def __init__(self) -> None:
            self.document_id = 1
            self._page_translations = {10: "EN PAGE 1", 12: ""}

    from context_aware_translation.documents import manga as manga_module

    monkeypatch.setattr(manga_module, "MangaDocument", _FakeMangaDocument)

    view = SimpleNamespace()
    view.document_repo = MagicMock()
    view.document_repo.get_document_sources.return_value = [
        {"source_id": 10, "sequence_number": 0, "ocr_json": '{"text":"jp1"}', "binary_content": b"img1"},
        {"source_id": 12, "sequence_number": 1, "ocr_json": '{"text":"jp2"}', "binary_content": b"img2"},
    ]
    view._reembedded_images = {}

    items = ReembeddingView._collect_manga_items(view, _FakeMangaDocument())

    assert [item.source_id for item in items] == [10]
