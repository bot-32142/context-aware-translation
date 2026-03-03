from __future__ import annotations

import asyncio

import pytest

from context_aware_translation.core.manga_document_handler import MangaDocumentHandler
from context_aware_translation.storage.book_db import TranslationChunkRecord


class DummyImageFetcher:
    def fetch_source_image(self, source_id: int) -> tuple[bytes, str]:  # noqa: ARG002
        return (b"image", "image/png")

    def fetch_source_ocr_text(self, source_id: int) -> str:  # noqa: ARG002
        return ""

    def list_page_source_ids(self, document_id: int) -> list[int]:
        assert document_id == 1
        return [10]


class DummyMangaPageTranslator:
    async def translate(self, page_images, terms, source_language, extracted_texts=None):  # noqa: ANN001, ARG002
        raise AssertionError("translate should not be called when alignment is invalid")


class DummyTermRepo:
    def __init__(self, chunks: list[TranslationChunkRecord]) -> None:
        self._chunks = chunks

    def get_source_language(self) -> str:
        return "English"

    def list_keyed_context(self) -> list:
        return []

    def list_chunks(self, document_id: int | None = None) -> list[TranslationChunkRecord]:
        if document_id is None:
            return list(self._chunks)
        return [c for c in self._chunks if c.document_id == document_id]

    def get_chunks_to_translate(
        self, document_ids: list[int] | None = None, force: bool = False
    ) -> list[TranslationChunkRecord]:
        _ = force
        if document_ids is None:
            return list(self._chunks)
        return [c for c in self._chunks if c.document_id in document_ids]


class DummyContextTree:
    def get_context(self, key: str, max_chunk_id: int) -> list[str]:  # noqa: ARG002
        return []


class DummyManager:
    def __init__(self, chunks: list[TranslationChunkRecord]) -> None:
        self.term_repo = DummyTermRepo(chunks)
        self.context_tree = DummyContextTree()

    def _state_update(self, extracted_keyed_context, chunk_records):  # noqa: ANN001, ARG002
        return None


@pytest.mark.asyncio
async def test_manga_document_handler_raises_on_source_chunk_mismatch() -> None:
    chunks = [
        TranslationChunkRecord(chunk_id=0, hash="h0", text="p1", document_id=1),
        TranslationChunkRecord(chunk_id=1, hash="h1", text="p2", document_id=1),
    ]
    manager = DummyManager(chunks)
    handler = MangaDocumentHandler(
        manga_page_translator=DummyMangaPageTranslator(),
        image_fetcher=DummyImageFetcher(),
        concurrency=1,
    )

    with pytest.raises(ValueError, match="alignment mismatch"):
        await handler.translate_chunks([1], manager)


class TwoPageImageFetcher:
    def fetch_source_image(self, source_id: int) -> tuple[bytes, str]:
        return (f"img-{source_id}".encode(), "image/png")

    def fetch_source_ocr_text(self, source_id: int) -> str:
        return f"ocr-{source_id}"

    def list_page_source_ids(self, document_id: int) -> list[int]:
        assert document_id == 1
        return [101, 102]


class PartiallyFailingMangaPageTranslator:
    async def translate(self, page_images, terms, source_language, extracted_texts=None):  # noqa: ANN001, ARG002
        marker = page_images[0][0]
        if marker == b"img-102":
            raise RuntimeError("failed-page-102")
        await asyncio.sleep(0.05)
        return [f"translated-{marker.decode()}"]


class LLMRateLimitError(Exception):
    pass


class MixedPriorityFailingMangaPageTranslator:
    async def translate(self, page_images, terms, source_language, extracted_texts=None):  # noqa: ANN001, ARG002
        marker = page_images[0][0]
        if marker == b"img-101":
            raise ValueError("translation: '翻译文本' length mismatch — expected 1, got 0")
        if marker == b"img-102":
            await asyncio.sleep(0.05)
            raise LLMRateLimitError("Rate limit exceeded: HTTP 429 Too Many Requests")
        return [f"translated-{marker.decode()}"]


class FinalMismatchMangaPageTranslator:
    async def translate(self, page_images, terms, source_language, extracted_texts=None):  # noqa: ANN001, ARG002
        marker = page_images[0][0]
        if marker == b"img-101":
            raise LLMRateLimitError("Rate limit exceeded: HTTP 429 Too Many Requests")
        if marker == b"img-102":
            await asyncio.sleep(0.05)
            raise ValueError("translation: '翻译文本' length mismatch — expected 1, got 0")
        return [f"translated-{marker.decode()}"]


class RecordingMangaPageTranslator:
    def __init__(self) -> None:
        self.calls: list[list[bytes]] = []

    async def translate(self, page_images, terms, source_language, extracted_texts=None):  # noqa: ANN001, ARG002
        markers = [img_bytes for (img_bytes, _mime) in page_images]
        self.calls.append(markers)
        return [f"translated-{marker.decode()}" for marker in markers]


@pytest.mark.asyncio
async def test_manga_document_handler_persists_successful_batches_when_some_fail() -> None:
    chunks = [
        TranslationChunkRecord(chunk_id=0, hash="h0", text="p1", document_id=1),
        TranslationChunkRecord(chunk_id=1, hash="h1", text="p2", document_id=1),
    ]
    manager = DummyManager(chunks)
    handler = MangaDocumentHandler(
        manga_page_translator=PartiallyFailingMangaPageTranslator(),
        image_fetcher=TwoPageImageFetcher(),
        concurrency=2,
    )

    with pytest.raises(RuntimeError, match="failed-page-102"):
        await handler.translate_chunks([1], manager)

    chunks_by_id = {chunk.chunk_id: chunk for chunk in manager.term_repo.list_chunks(document_id=1)}
    assert chunks_by_id[0].translation == "translated-img-101"
    assert chunks_by_id[0].is_translated is True
    assert chunks_by_id[1].translation is None
    assert chunks_by_id[1].is_translated is False


@pytest.mark.asyncio
async def test_manga_document_handler_surfaces_rate_limit_over_validation_error() -> None:
    chunks = [
        TranslationChunkRecord(chunk_id=0, hash="h0", text="p1", document_id=1),
        TranslationChunkRecord(chunk_id=1, hash="h1", text="p2", document_id=1),
    ]
    manager = DummyManager(chunks)
    handler = MangaDocumentHandler(
        manga_page_translator=MixedPriorityFailingMangaPageTranslator(),
        image_fetcher=TwoPageImageFetcher(),
        concurrency=2,
    )

    with pytest.raises(LLMRateLimitError, match="429"):
        await handler.translate_chunks([1], manager)


@pytest.mark.asyncio
async def test_manga_document_handler_raises_last_exception_even_if_not_rate_limit() -> None:
    chunks = [
        TranslationChunkRecord(chunk_id=0, hash="h0", text="p1", document_id=1),
        TranslationChunkRecord(chunk_id=1, hash="h1", text="p2", document_id=1),
    ]
    manager = DummyManager(chunks)
    handler = MangaDocumentHandler(
        manga_page_translator=FinalMismatchMangaPageTranslator(),
        image_fetcher=TwoPageImageFetcher(),
        concurrency=2,
    )

    with pytest.raises(ValueError, match="length mismatch"):
        await handler.translate_chunks([1], manager)


@pytest.mark.asyncio
async def test_manga_document_handler_respects_source_ids_filter() -> None:
    chunks = [
        TranslationChunkRecord(chunk_id=0, hash="h0", text="p1", document_id=1),
        TranslationChunkRecord(chunk_id=1, hash="h1", text="p2", document_id=1),
    ]
    manager = DummyManager(chunks)
    translator = RecordingMangaPageTranslator()
    handler = MangaDocumentHandler(
        manga_page_translator=translator,
        image_fetcher=TwoPageImageFetcher(),
        concurrency=1,
    )

    await handler.translate_chunks([1], manager, source_ids=[102])

    assert translator.calls == [[b"img-102"]]
    chunks_by_id = {chunk.chunk_id: chunk for chunk in manager.term_repo.list_chunks(document_id=1)}
    assert chunks_by_id[0].translation is None
    assert chunks_by_id[0].is_translated is False
    assert chunks_by_id[1].translation == "translated-img-102"
    assert chunks_by_id[1].is_translated is True
