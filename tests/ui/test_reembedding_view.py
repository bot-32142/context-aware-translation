from types import SimpleNamespace
from unittest.mock import MagicMock

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

    assert ReembeddingView._get_translated_lines_with_fallback(view, 1) == ["hola", "world"]


def test_get_translated_lines_manga_keeps_empty_for_untranslated_chunks() -> None:
    view = _make_view(
        "manga",
        [
            _chunk(chunk_id=1, text="JP PAGE 1", translation="EN PAGE 1", is_translated=True),
            _chunk(chunk_id=2, text="JP PAGE 2", translation=None, is_translated=False),
        ],
    )

    assert ReembeddingView._get_translated_lines_with_fallback(view, 1) == ["EN PAGE 1", ""]
