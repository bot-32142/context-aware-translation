from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from context_aware_translation.core.context_manager import TranslationContextManager, TranslationContextManagerAdapter
from context_aware_translation.core.models import Term
from context_aware_translation.storage.book_db import TermRecord, TranslationChunkRecord


class DummyTokenizer:
    def encode(self, text: str) -> list[int]:
        return [ord(char) for char in text]


class DummyContextTree:
    def __init__(self, context_map: dict[str, list[str]] | None = None) -> None:
        self.context_map = context_map or {}

    def get_context(self, key: str, _max_chunk_id: int) -> list[str]:
        return self.context_map.get(key, [])

    def get_longest_context_summary(self, key: str, _max_chunk_id: int) -> str:
        summaries = self.get_context(key, _max_chunk_id)
        if not summaries:
            return ""
        return max(summaries, key=lambda s: len((s or "").strip()))

    def close(self) -> None:
        pass


class DummyContextExtractor:
    async def extract_keyed_context(self, _chunk_record, _source_language: str):
        return []


class DummyTermRepo:
    def __init__(
        self,
        source_language: str | None = None,
        terms: list[Term] | None = None,
        chunks: list[TranslationChunkRecord] | None = None,
        pending_terms: list[TermRecord] | None = None,
    ) -> None:
        self._source_language = source_language
        self._terms = {term.key: term for term in terms or []}
        self.chunks = chunks or []
        self._pending_terms = pending_terms or []

    def get_source_language(self) -> str | None:
        return self._source_language

    def set_source_language(self, source_language: str) -> None:
        self._source_language = source_language

    def list_chunks(self) -> list[TranslationChunkRecord]:
        return list(self.chunks)

    def get_terms_to_translate(self) -> list[Term]:
        return list(self._terms.values())

    def list_keyed_context(self) -> list[Term]:
        return list(self._terms.values())

    def get_keyed_context(self, key: str) -> Term | None:
        return self._terms.get(key)

    def apply_batch(self, update) -> None:
        for keyed_context in update.keyed_context:
            existing = self._terms.get(keyed_context.key)
            if existing:
                existing.merge(keyed_context)
            else:
                self._terms[keyed_context.key] = keyed_context
        for chunk in update.chunk_records:
            for index, existing_chunk in enumerate(self.chunks):
                if existing_chunk.chunk_id == chunk.chunk_id:
                    self.chunks[index] = chunk
                    break
            else:
                self.chunks.append(chunk)

    def get_terms_pending_review(self) -> list[TermRecord]:
        return list(self._pending_terms)

    def upsert_terms(self, terms: list[TermRecord]) -> None:
        updates_by_key = {t.key: t for t in terms}
        self._pending_terms = [updates_by_key.get(t.key, t) for t in self._pending_terms]

    def get_chunks_to_translate(
        self, document_ids: list[int] | None = None, force: bool = False
    ) -> list[TranslationChunkRecord]:
        chunks = self.chunks
        if document_ids is not None:
            chunks = [c for c in chunks if c.document_id in document_ids]
        if not force:
            chunks = [c for c in chunks if not c.is_translated]
        return list(chunks)


class DetectLanguageStrategy:
    def __init__(self, language: str) -> None:
        self.detect = AsyncMock(return_value=language)


class GlossaryTranslatorStrategy:
    def __init__(self) -> None:
        async def translate(items, _similar_terms, _source_language, **_kwargs):
            return {item["canonical_name"]: f"translated-{item['canonical_name']}" for item in items}

        self.translate = AsyncMock(side_effect=translate)


class PartiallyFailingGlossaryTranslatorStrategy:
    def __init__(self, fail_for: str) -> None:
        async def translate(items, _similar_terms, _source_language, **_kwargs):
            names = [item["canonical_name"] for item in items]
            if fail_for in names:
                raise RuntimeError(f"failed-{fail_for}")
            return {name: f"translated-{name}" for name in names}

        self.translate = AsyncMock(side_effect=translate)


class ChunkTranslatorStrategy:
    def __init__(self) -> None:
        async def translate(texts, _terms, _source_language, **_kwargs):
            return [f"translated-{text}" for text in texts]

        self.translate = AsyncMock(side_effect=translate)


class CapturingChunkTranslatorStrategy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

        async def translate(texts, terms, _source_language, **_kwargs):
            self.calls.append({"texts": list(texts), "terms": list(terms)})
            return [f"translated-{text}" for text in texts]

        self.translate = AsyncMock(side_effect=translate)


class PartiallyFailingChunkTranslatorStrategy:
    def __init__(self, fail_text: str) -> None:
        async def translate(texts, _terms, _source_language, **_kwargs):
            if any(fail_text in text for text in texts):
                raise RuntimeError(f"failed-chunk-{fail_text}")
            await asyncio.sleep(0.05)
            return [f"translated-{text}" for text in texts]

        self.translate = AsyncMock(side_effect=translate)


class LLMRateLimitError(Exception):
    pass


class MixedPriorityFailingChunkTranslatorStrategy:
    def __init__(self) -> None:
        async def translate(texts, _terms, _source_language, **_kwargs):
            text = texts[0]
            if "mismatch" in text:
                raise ValueError("translation: '翻译文本' length mismatch — expected 1, got 0")
            if "rate-limit" in text:
                await asyncio.sleep(0.05)
                raise LLMRateLimitError("Rate limit exceeded: HTTP 429 Too Many Requests")
            return [f"translated-{text}" for text in texts]

        self.translate = AsyncMock(side_effect=translate)


class FinalMismatchChunkTranslatorStrategy:
    def __init__(self) -> None:
        async def translate(texts, _terms, _source_language, **_kwargs):
            text = texts[0]
            if "rate-limit" in text:
                raise LLMRateLimitError("Rate limit exceeded: HTTP 429 Too Many Requests")
            if "mismatch" in text:
                await asyncio.sleep(0.05)
                raise ValueError("translation: '翻译文本' length mismatch — expected 1, got 0")
            return [f"translated-{text}" for text in texts]

        self.translate = AsyncMock(side_effect=translate)


class TermReviewerStrategy:
    def __init__(self) -> None:
        async def review_batch(_terms, _source_language, **_kwargs):
            return {"keep": [], "ignore": []}

        self.review_batch = AsyncMock(side_effect=review_batch)


class FailingTermReviewerStrategy:
    def __init__(self) -> None:
        async def review_batch(_terms, _source_language, **_kwargs):
            raise RuntimeError("review failed")

        self.review_batch = AsyncMock(side_effect=review_batch)


class AdapterProbeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[int, ...], int, int, int]] = []
        self._inflight = 0
        self.max_inflight = 0

    async def translate_chunks(
        self,
        concurrency: int,
        batch_size: int,
        max_tokens_per_batch: int,
        document_ids: list[int],
        force: bool = False,
        progress_callback=None,
    ) -> None:
        _ = force
        _ = progress_callback
        self.calls.append((tuple(document_ids), concurrency, batch_size, max_tokens_per_batch))
        self._inflight += 1
        self.max_inflight = max(self.max_inflight, self._inflight)
        await asyncio.sleep(0.01)
        self._inflight -= 1


class AdapterProbeHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[int, ...]] = []
        self._inflight = 0
        self.max_inflight = 0

    async def translate_chunks(
        self,
        document_ids: list[int],
        _manager,
        force: bool = False,
        progress_callback=None,
    ) -> None:
        _ = force
        _ = progress_callback
        self.calls.append(tuple(document_ids))
        self._inflight += 1
        self.max_inflight = max(self.max_inflight, self._inflight)
        await asyncio.sleep(0.01)
        self._inflight -= 1


@pytest.mark.asyncio
async def test_translation_context_manager_detect_language_uses_strategy_object():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree()
    term_repo = DummyTermRepo(
        source_language=None,
        chunks=[TranslationChunkRecord(chunk_id=0, hash="hash0", text="hello world")],
    )
    detector = DetectLanguageStrategy("French")

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=detector,
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.detect_language()

    detector.detect.assert_awaited_once_with("hello world", cancel_check=None)
    assert term_repo.get_source_language() == "French"


@pytest.mark.asyncio
async def test_translation_context_manager_translate_terms_uses_glossary_strategy_object():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree()
    term = Term(
        key="term1",
        descriptions={"0": "description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    term_repo = DummyTermRepo(source_language="English", terms=[term])
    glossary_strategy = GlossaryTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=glossary_strategy,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.translate_terms(translation_name_similarity_threshold=0.0, concurrency=1)

    glossary_strategy.translate.assert_awaited()
    assert term_repo.get_keyed_context("term1").translated_name == "translated-term1"


@pytest.mark.asyncio
async def test_translation_context_manager_translate_terms_persists_successful_components_when_some_fail():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree()
    term_a = Term(
        key="term-a",
        descriptions={"0": "description-a"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    term_b = Term(
        key="term-b",
        descriptions={"0": "description-b"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    term_repo = DummyTermRepo(source_language="English", terms=[term_a, term_b])
    glossary_strategy = PartiallyFailingGlossaryTranslatorStrategy(fail_for="term-b")

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=glossary_strategy,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    with pytest.raises(RuntimeError, match="failed-term-b"):
        await manager.translate_terms(
            translation_name_similarity_threshold=1.0,
            concurrency=2,
            max_terms_per_batch=1,  # keep each component in its own bin/call
        )

    assert term_repo.get_keyed_context("term-a").translated_name == "translated-term-a"
    assert term_repo.get_keyed_context("term-b").translated_name is None


@pytest.mark.asyncio
async def test_translation_context_manager_translate_chunks_uses_chunk_strategy_object():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree({"term1": ["context line"]})
    term = Term(
        key="term1",
        descriptions={"0": "description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="term1-translation",
    )
    chunk = TranslationChunkRecord(chunk_id=0, hash="hash0", text="term1 is here")
    term_repo = DummyTermRepo(source_language="English", terms=[term], chunks=[chunk])
    chunk_strategy = ChunkTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=chunk_strategy,
        term_reviewer=None,
    )

    await manager.translate_chunks(concurrency=1, batch_size=2)

    chunk_strategy.translate.assert_awaited()
    assert term_repo.chunks[0].translation == "translated-term1 is here"


@pytest.mark.asyncio
async def test_translate_chunks_splits_to_single_chunk_when_token_budget_is_tiny():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree()
    term = Term(
        key="term1",
        descriptions={"0": "description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="term1-translation",
    )
    chunks = [
        TranslationChunkRecord(chunk_id=0, hash="h0", text="first chunk"),
        TranslationChunkRecord(chunk_id=1, hash="h1", text="second chunk"),
    ]
    term_repo = DummyTermRepo(source_language="English", terms=[term], chunks=chunks)
    chunk_strategy = CapturingChunkTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=chunk_strategy,
        term_reviewer=None,
    )

    await manager.translate_chunks(concurrency=1, batch_size=0, max_tokens_per_batch=1)

    assert chunk_strategy.translate.await_count == 2
    assert [len(call["texts"]) for call in chunk_strategy.calls] == [1, 1]


@pytest.mark.asyncio
async def test_translate_chunks_groups_more_chunks_when_token_budget_allows():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree()
    term = Term(
        key="term1",
        descriptions={"0": "description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="term1-translation",
    )
    chunks = [
        TranslationChunkRecord(chunk_id=0, hash="h0", text="first chunk"),
        TranslationChunkRecord(chunk_id=1, hash="h1", text="second chunk"),
    ]
    term_repo = DummyTermRepo(source_language="English", terms=[term], chunks=chunks)
    chunk_strategy = CapturingChunkTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=chunk_strategy,
        term_reviewer=None,
    )

    await manager.translate_chunks(concurrency=1, batch_size=0, max_tokens_per_batch=50000)

    assert chunk_strategy.translate.await_count == 1
    assert len(chunk_strategy.calls[0]["texts"]) == 2


@pytest.mark.asyncio
async def test_translate_chunks_uses_context_tree_description_for_imported_glossary():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree({"term1": ["Imported glossary description"]})
    term = Term(
        key="term1",
        descriptions={"imported": "Imported glossary description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="term1-translation",
    )
    chunk = TranslationChunkRecord(
        chunk_id=0,
        hash="hash0",
        text="term1 appears here",
        normalized_text="term1 appears here",
    )
    term_repo = DummyTermRepo(source_language="English", terms=[term], chunks=[chunk])
    chunk_strategy = CapturingChunkTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=chunk_strategy,
        term_reviewer=None,
    )

    await manager.translate_chunks(concurrency=1, batch_size=1)

    assert chunk_strategy.translate.await_count == 1
    sent_terms = chunk_strategy.calls[0]["terms"]
    assert sent_terms == [("term1", "term1-translation", "Imported glossary description")]


@pytest.mark.asyncio
async def test_translate_chunks_prefers_late_context_summary_over_imported_description():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree({"term1": ["late context summary"]})
    term = Term(
        key="term1",
        descriptions={"imported": "Imported glossary description", "5": "later description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="term1-translation",
    )
    chunk = TranslationChunkRecord(
        chunk_id=6,
        hash="hash0",
        text="term1 appears here",
        normalized_text="term1 appears here",
    )
    term_repo = DummyTermRepo(source_language="English", terms=[term], chunks=[chunk])
    chunk_strategy = CapturingChunkTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=chunk_strategy,
        term_reviewer=None,
    )

    await manager.translate_chunks(concurrency=1, batch_size=1)

    assert chunk_strategy.translate.await_count == 1
    sent_terms = chunk_strategy.calls[0]["terms"]
    assert sent_terms == [("term1", "term1-translation", "late context summary")]


@pytest.mark.asyncio
async def test_translation_context_manager_translate_chunks_persists_successful_batches_when_some_fail():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree({"term1": ["context line"]})
    term = Term(
        key="term1",
        descriptions={"0": "description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="term1-translation",
    )
    chunk_ok = TranslationChunkRecord(chunk_id=0, hash="hash0", text="ok text")
    chunk_fail = TranslationChunkRecord(chunk_id=1, hash="hash1", text="fail text")
    term_repo = DummyTermRepo(source_language="English", terms=[term], chunks=[chunk_ok, chunk_fail])
    chunk_strategy = PartiallyFailingChunkTranslatorStrategy(fail_text="fail")

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=chunk_strategy,
        term_reviewer=None,
    )

    with pytest.raises(RuntimeError, match="failed-chunk-fail"):
        await manager.translate_chunks(concurrency=2, batch_size=1)

    chunks_by_id = {chunk.chunk_id: chunk for chunk in term_repo.chunks}
    assert chunks_by_id[0].translation == "translated-ok text"
    assert chunks_by_id[0].is_translated is True
    assert chunks_by_id[1].translation is None
    assert chunks_by_id[1].is_translated is False


@pytest.mark.asyncio
async def test_translation_context_manager_translate_chunks_surfaces_rate_limit_over_validation_error():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree({"term1": ["context line"]})
    term = Term(
        key="term1",
        descriptions={"0": "description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="term1-translation",
    )
    chunk_value_error = TranslationChunkRecord(chunk_id=0, hash="h0", text="mismatch text")
    chunk_rate_limit = TranslationChunkRecord(chunk_id=1, hash="h1", text="rate-limit text")
    term_repo = DummyTermRepo(source_language="English", terms=[term], chunks=[chunk_value_error, chunk_rate_limit])
    chunk_strategy = MixedPriorityFailingChunkTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=chunk_strategy,
        term_reviewer=None,
    )

    with pytest.raises(LLMRateLimitError, match="429"):
        await manager.translate_chunks(concurrency=2, batch_size=1)


@pytest.mark.asyncio
async def test_translation_context_manager_translate_chunks_raises_last_exception_even_if_not_rate_limit():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree({"term1": ["context line"]})
    term = Term(
        key="term1",
        descriptions={"0": "description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="term1-translation",
    )
    chunk_rate_limit = TranslationChunkRecord(chunk_id=0, hash="h0", text="rate-limit text")
    chunk_value_error = TranslationChunkRecord(chunk_id=1, hash="h1", text="mismatch text")
    term_repo = DummyTermRepo(source_language="English", terms=[term], chunks=[chunk_rate_limit, chunk_value_error])
    chunk_strategy = FinalMismatchChunkTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=chunk_strategy,
        term_reviewer=None,
    )

    with pytest.raises(ValueError, match="length mismatch"):
        await manager.translate_chunks(concurrency=2, batch_size=1)


@pytest.mark.asyncio
async def test_translation_context_manager_review_terms_raises_on_batch_error():
    tokenizer = DummyTokenizer()
    context_tree = DummyContextTree()
    pending = [
        TermRecord(
            key="term1",
            descriptions={"0": "desc"},
            occurrence={},
            votes=1,
            total_api_calls=1,
            is_reviewed=False,
        )
    ]
    term_repo = DummyTermRepo(
        source_language="English",
        pending_terms=pending,
    )

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=context_tree,
        context_extractor=DummyContextExtractor(),
        tokenizer=tokenizer,
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=FailingTermReviewerStrategy(),
    )

    with pytest.raises(RuntimeError, match="review failed"):
        await manager.review_terms(concurrency=1, batch_size=1)


@pytest.mark.asyncio
async def test_translation_context_manager_adapter_translate_chunks_serial_default_manager():
    manager = AdapterProbeManager()
    adapter = TranslationContextManagerAdapter(manager)  # type: ignore[arg-type]

    await adapter.translate_chunks(
        concurrency=3,
        batch_size=2,
        doc_type_by_id={1: "text", 2: "text", 3: "text"},
    )

    assert manager.max_inflight == 1
    assert sorted(call[0] for call in manager.calls) == [(1,), (2,), (3,)]


@pytest.mark.asyncio
async def test_translation_context_manager_adapter_translate_chunks_serial_handler():
    manager = AdapterProbeManager()
    handler = AdapterProbeHandler()
    adapter = TranslationContextManagerAdapter(manager)  # type: ignore[arg-type]
    adapter.register_handler("manga", handler)

    await adapter.translate_chunks(
        concurrency=3,
        batch_size=2,
        doc_type_by_id={1: "manga", 2: "manga", 3: "manga"},
    )

    assert handler.max_inflight == 1
    assert sorted(handler.calls) == [(1,), (2,), (3,)]


@pytest.mark.asyncio
async def test_translation_context_manager_adapter_forwards_default_arguments():
    manager = AdapterProbeManager()
    adapter = TranslationContextManagerAdapter(manager)  # type: ignore[arg-type]

    await adapter.translate_chunks(
        concurrency=3,
        batch_size=2,
        doc_type_by_id={1: "text"},
    )

    assert manager.calls == [((1,), 3, 2, 4000)]


# ---------------------------------------------------------------------------
# Tests for batching: _greedy_nearest_neighbor_split, _bin_pack_small_components,
# and the refactored translate_terms flow.
# ---------------------------------------------------------------------------


def _make_term(key: str, description: str = "desc", votes: int = 1, translated_name: str | None = None) -> Term:
    return Term(
        key=key,
        descriptions={"0": description},
        occurrence={},
        votes=votes,
        total_api_calls=1,
        translated_name=translated_name,
    )


def _make_term_record(key: str, description: str = "desc", votes: int = 1, is_reviewed: bool = False) -> TermRecord:
    return TermRecord(
        key=key,
        descriptions={"0": description},
        occurrence={},
        votes=votes,
        total_api_calls=1,
        is_reviewed=is_reviewed,
    )


class TestGreedyNearestNeighborSplit:
    def test_empty_input(self):
        result = TranslationContextManager._greedy_nearest_neighbor_split([], 20)
        assert result == []

    def test_all_fit_in_one_batch(self):
        terms = [_make_term(f"term{i}") for i in range(5)]
        result = TranslationContextManager._greedy_nearest_neighbor_split(terms, 20)
        assert len(result) == 1
        assert len(result[0]) == 5

    def test_respects_max_batch_size(self):
        terms = [_make_term(f"term{i}") for i in range(50)]
        result = TranslationContextManager._greedy_nearest_neighbor_split(terms, 20)
        for batch in result:
            assert len(batch) <= 20

    def test_covers_all_terms(self):
        terms = [_make_term(f"term{i}") for i in range(50)]
        result = TranslationContextManager._greedy_nearest_neighbor_split(terms, 20)
        result_keys = {t.key for batch in result for t in batch}
        expected_keys = {t.key for t in terms}
        assert result_keys == expected_keys

    def test_seeds_with_highest_votes(self):
        terms = [
            _make_term("low_votes_a", votes=1),
            _make_term("high_votes", votes=100),
            _make_term("low_votes_b", votes=1),
        ]
        result = TranslationContextManager._greedy_nearest_neighbor_split(terms, 2)
        # First batch should be seeded with the highest-vote term
        assert result[0][0].key == "high_votes"

    def test_groups_similar_terms(self):
        terms = [
            _make_term("dragon_fire"),
            _make_term("dragon_ice"),
            _make_term("dragon_wind"),
            _make_term("cat_black"),
            _make_term("cat_white"),
        ]
        result = TranslationContextManager._greedy_nearest_neighbor_split(terms, 3)
        # With greedy NN, similar terms should cluster together
        for batch in result:
            keys = [t.key for t in batch]
            # At least one batch should have multiple dragon_ or cat_ terms
            dragon_count = sum(1 for k in keys if k.startswith("dragon_"))
            cat_count = sum(1 for k in keys if k.startswith("cat_"))
            assert dragon_count >= 2 or cat_count >= 2 or len(batch) <= 2

    def test_single_term(self):
        terms = [_make_term("only")]
        result = TranslationContextManager._greedy_nearest_neighbor_split(terms, 20)
        assert len(result) == 1
        assert result[0][0].key == "only"

    def test_exact_batch_boundary(self):
        terms = [_make_term(f"t{i}") for i in range(40)]
        result = TranslationContextManager._greedy_nearest_neighbor_split(terms, 20)
        assert len(result) == 2
        assert all(len(b) == 20 for b in result)


class TestBinPackSmallComponents:
    def test_empty_input(self):
        result = TranslationContextManager._bin_pack_small_components([], 20)
        assert result == []

    def test_single_component_fits(self):
        comp = [_make_term("a"), _make_term("b")]
        result = TranslationContextManager._bin_pack_small_components([comp], 20)
        assert len(result) == 1
        assert result[0] == [comp]

    def test_multiple_components_packed_into_one_bin(self):
        comp1 = [_make_term("a"), _make_term("b")]  # 2 untranslated
        comp2 = [_make_term("c")]  # 1 untranslated
        result = TranslationContextManager._bin_pack_small_components([comp1, comp2], 20)
        assert len(result) == 1  # both fit in one bin

    def test_components_split_across_bins_when_full(self):
        # 3 components of 8 untranslated each => max_batch=20 => 2 bins (8+8=16, 8)
        comps = [[_make_term(f"c{i}_{j}") for j in range(8)] for i in range(3)]
        result = TranslationContextManager._bin_pack_small_components(comps, 20)
        assert len(result) == 2
        # No bin should exceed 20 untranslated terms
        for bin_comps in result:
            total_untranslated = sum(1 for comp in bin_comps for t in comp if not t.translated_name)
            assert total_untranslated <= 20

    def test_never_splits_a_component(self):
        comp = [_make_term(f"t{i}") for i in range(15)]  # 15 untranslated, fits in one bin
        result = TranslationContextManager._bin_pack_small_components([comp], 20)
        assert len(result) == 1
        assert len(result[0]) == 1
        assert len(result[0][0]) == 15

    def test_translated_terms_dont_count(self):
        # Component has 5 terms but only 2 untranslated
        comp = [
            _make_term("a"),
            _make_term("b"),
            _make_term("c", translated_name="trans_c"),
            _make_term("d", translated_name="trans_d"),
            _make_term("e", translated_name="trans_e"),
        ]
        comp2 = [_make_term(f"x{i}") for i in range(18)]  # 18 untranslated
        result = TranslationContextManager._bin_pack_small_components([comp, comp2], 20)
        # 18 + 2 = 20, should fit in one bin
        assert len(result) == 1


class TestGroupBySimilarity:
    def test_empty_input(self):
        result, sim_cache = TranslationContextManager._group_by_similarity([], 0.7)
        assert result == []
        assert sim_cache == {}

    def test_single_term(self):
        terms = [_make_term_record("alpha")]
        result, _ = TranslationContextManager._group_by_similarity(terms, 0.7)
        assert len(result) == 1
        assert len(result[0]) == 1

    def test_dissimilar_terms_separate(self):
        terms = [_make_term_record("dragon"), _make_term_record("castle"), _make_term_record("wizard")]
        result, _ = TranslationContextManager._group_by_similarity(terms, 0.7)
        # All dissimilar — each should be its own component
        assert len(result) == 3

    def test_similar_terms_grouped(self):
        terms = [
            _make_term_record("dragon_fire"),
            _make_term_record("dragon_ice"),
            _make_term_record("dragon_wind"),
            _make_term_record("xyz"),
        ]
        result, _ = TranslationContextManager._group_by_similarity(terms, 0.7)
        # The dragon_* terms should be grouped; xyz should be separate
        dragon_component = None
        for comp in result:
            keys = {t.key for t in comp}
            if "dragon_fire" in keys:
                dragon_component = keys
        assert dragon_component is not None
        assert "dragon_ice" in dragon_component
        assert "dragon_wind" in dragon_component
        assert "xyz" not in dragon_component

    def test_transitive_grouping(self):
        # A~B and B~C should put all three in one component even if A and C aren't directly similar
        terms = [
            _make_term_record("abcdef"),
            _make_term_record("abcdeg"),  # similar to abcdef
            _make_term_record("abcdeh"),  # similar to abcdeg
        ]
        result, _ = TranslationContextManager._group_by_similarity(terms, 0.7)
        assert len(result) == 1
        assert len(result[0]) == 3

    def test_high_threshold_keeps_separate(self):
        terms = [_make_term_record("dragon_fire"), _make_term_record("dragon_ice")]
        result, _ = TranslationContextManager._group_by_similarity(terms, 1.0)
        # With threshold=1.0, only exact matches group together
        assert len(result) == 2

    def test_works_with_term_type(self):
        # Verify it works with Term objects too (generic)
        terms = [_make_term("dragon_fire"), _make_term("dragon_ice")]
        result, _ = TranslationContextManager._group_by_similarity(terms, 0.7)
        assert len(result) == 1
        assert len(result[0]) == 2


class TestBinPackComponents:
    def test_empty_input(self):
        result = TranslationContextManager._bin_pack_components([], 20)
        assert result == []

    def test_single_component_fits(self):
        comp = [_make_term_record("a"), _make_term_record("b")]
        result = TranslationContextManager._bin_pack_components([comp], 20)
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_multiple_components_packed(self):
        comp1 = [_make_term_record("a"), _make_term_record("b")]
        comp2 = [_make_term_record("c")]
        result = TranslationContextManager._bin_pack_components([comp1, comp2], 20)
        assert len(result) == 1
        assert len(result[0]) == 3

    def test_components_overflow_into_multiple_batches(self):
        # 3 components of 8 terms each => max_batch=20 => 2 batches (8+8=16, 8)
        comps = [[_make_term_record(f"c{i}_{j}") for j in range(8)] for i in range(3)]
        result = TranslationContextManager._bin_pack_components(comps, 20)
        assert len(result) == 2
        for batch in result:
            assert len(batch) <= 20

    def test_never_splits_component(self):
        comp = [_make_term_record(f"t{i}") for i in range(15)]
        result = TranslationContextManager._bin_pack_components([comp], 20)
        assert len(result) == 1
        assert len(result[0]) == 15

    def test_all_terms_covered(self):
        comps = [[_make_term_record(f"c{i}_{j}") for j in range(5)] for i in range(7)]
        result = TranslationContextManager._bin_pack_components(comps, 10)
        all_keys = {t.key for batch in result for t in batch}
        expected_keys = {f"c{i}_{j}" for i in range(7) for j in range(5)}
        assert all_keys == expected_keys


class RecordingTermReviewerStrategy:
    """Records each review_batch() call's term keys for inspection."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

        async def review_batch(terms, _source_language, **_kwargs):
            keys = [t.key for t in terms]
            self.calls.append(keys)
            return {"keep": keys, "ignore": []}

        self.review_batch = AsyncMock(side_effect=review_batch)


@pytest.mark.asyncio
async def test_review_terms_groups_similar_terms_in_same_batch():
    """Similar terms should be grouped in the same review batch."""
    pending = [
        _make_term_record("dragon_fire", votes=3),
        _make_term_record("dragon_ice", votes=2),
        _make_term_record("dragon_wind", votes=1),
        _make_term_record("xyz_aaa", votes=3),
        _make_term_record("xyz_bbb", votes=2),
    ]
    term_repo = DummyTermRepo(source_language="English", pending_terms=pending)
    recorder = RecordingTermReviewerStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=recorder,
    )

    await manager.review_terms(concurrency=1, batch_size=3, similarity_threshold=0.7)

    # All terms should be reviewed
    all_reviewed = {k for call in recorder.calls for k in call}
    assert all_reviewed == {t.key for t in pending}

    # Similar terms should cluster: find which batch has dragon terms
    for call in recorder.calls:
        dragon_count = sum(1 for k in call if k.startswith("dragon_"))
        xyz_count = sum(1 for k in call if k.startswith("xyz_"))
        # A batch should not mix dragon and xyz terms
        assert dragon_count == 0 or xyz_count == 0, f"Expected dragon and xyz terms in separate batches, got: {call}"


@pytest.mark.asyncio
async def test_review_terms_all_terms_covered_with_similarity_batching():
    """Verify no terms are lost when using similarity-based batching."""
    pending = [_make_term_record(f"term_{i:03d}") for i in range(50)]
    term_repo = DummyTermRepo(source_language="English", pending_terms=pending)
    recorder = RecordingTermReviewerStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("English"),
        glossary_translator=GlossaryTranslatorStrategy(),
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=recorder,
    )

    await manager.review_terms(concurrency=5, batch_size=10, similarity_threshold=0.7)

    all_reviewed = {k for call in recorder.calls for k in call}
    assert all_reviewed == {t.key for t in pending}
    for call in recorder.calls:
        assert len(call) <= 10


class RecordingGlossaryTranslatorStrategy:
    """Records each translate() call's arguments for inspection."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

        async def translate(items, similar_terms, source_language, **_kwargs):  # noqa: ARG001
            self.calls.append(
                {
                    "untranslated": [item["canonical_name"] for item in items],
                    "similar_terms": dict(similar_terms),
                }
            )
            return {item["canonical_name"]: f"translated-{item['canonical_name']}" for item in items}

        self.translate = AsyncMock(side_effect=translate)


@pytest.mark.asyncio
async def test_translate_terms_large_component_splits_and_persists_immediately():
    """A component with >max_terms_per_batch untranslated terms should be split
    into sub-batches and each sub-batch should persist immediately."""
    terms = [_make_term(f"term_{i:03d}") for i in range(25)]
    term_repo = DummyTermRepo(source_language="Japanese", terms=terms)
    recorder = RecordingGlossaryTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("Japanese"),
        glossary_translator=recorder,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.translate_terms(
        translation_name_similarity_threshold=0.0,
        concurrency=5,
        max_terms_per_batch=10,
    )

    # Should have made 3 LLM calls (25 terms / 10 per batch = 3 batches)
    assert len(recorder.calls) == 3
    # Each call should have at most 10 untranslated terms
    for call in recorder.calls:
        assert len(call["untranslated"]) <= 10
    # All terms should be covered
    all_translated = {k for call in recorder.calls for k in call["untranslated"]}
    assert all_translated == {t.key for t in terms}
    # All terms should now be translated in the repo
    for term in terms:
        assert term_repo.get_keyed_context(term.key).translated_name is not None


@pytest.mark.asyncio
async def test_translate_terms_small_components_binpacked():
    """Small components should be bin-packed and processed in parallel."""
    # Create two groups of terms that won't be grouped by union-find (threshold=1.0)
    terms_a = [_make_term(f"alpha_{i}") for i in range(5)]
    terms_b = [_make_term(f"beta_{i}") for i in range(5)]
    all_terms = terms_a + terms_b
    term_repo = DummyTermRepo(source_language="Japanese", terms=all_terms)
    recorder = RecordingGlossaryTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("Japanese"),
        glossary_translator=recorder,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.translate_terms(
        translation_name_similarity_threshold=1.0,  # high threshold = separate components
        concurrency=5,
        max_terms_per_batch=20,
    )

    # Both components (5 terms each) should be bin-packed into one call (5+5=10 <= 20)
    # or processed as separate small batches depending on bin packing
    total_translated = {k for call in recorder.calls for k in call["untranslated"]}
    assert total_translated == {t.key for t in all_terms}
    # All terms translated
    for t in all_terms:
        assert term_repo.get_keyed_context(t.key).translated_name is not None


@pytest.mark.asyncio
async def test_translate_terms_later_subbatches_get_earlier_translations_as_context():
    """Later sub-batches within a large component should receive translations
    from earlier sub-batches as similar_terms context."""
    terms = [_make_term(f"word_{i:02d}") for i in range(10)]
    term_repo = DummyTermRepo(source_language="Japanese", terms=terms)
    recorder = RecordingGlossaryTranslatorStrategy()

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("Japanese"),
        glossary_translator=recorder,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.translate_terms(
        translation_name_similarity_threshold=0.0,  # all in one component
        concurrency=1,  # sequential to ensure ordering
        max_terms_per_batch=5,
    )

    assert len(recorder.calls) == 2
    # First call should have no similar_terms (nothing translated yet)
    assert recorder.calls[0]["similar_terms"] == {} or all(
        v.startswith("translated-") is False for v in recorder.calls[0]["similar_terms"].values()
    )
    # Second call should have similar_terms from first call's translations
    second_similar = recorder.calls[1]["similar_terms"]
    # At least some terms from the first batch should appear as context
    first_batch_keys = set(recorder.calls[0]["untranslated"])
    context_from_first = {k for k in second_similar if k in first_batch_keys}
    assert len(context_from_first) > 0, "Later sub-batches should get earlier translations as context"


@pytest.mark.asyncio
async def test_translate_terms_progress_reports_subbatches():
    """Progress should report sub-batch count, not just component count."""
    terms = [_make_term(f"t{i:02d}") for i in range(25)]
    term_repo = DummyTermRepo(source_language="Japanese", terms=terms)
    recorder = RecordingGlossaryTranslatorStrategy()
    progress_updates = []

    def progress_cb(update):
        progress_updates.append(update)

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("Japanese"),
        glossary_translator=recorder,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.translate_terms(
        translation_name_similarity_threshold=0.0,
        concurrency=1,
        max_terms_per_batch=10,
        progress_callback=progress_cb,
    )

    # 25 terms / 10 per batch = 3 sub-batches => 1 initial + 3 progress updates
    assert len(progress_updates) == 4
    assert progress_updates[0].current == 0
    assert progress_updates[0].total == 3
    assert progress_updates[-1].total == 3
    assert progress_updates[-1].current == 3


@pytest.mark.asyncio
async def test_translate_terms_progress_reports_small_components():
    """Progress should be reported for small bin-packed components."""
    # Two small components that will be separate bins (threshold=1.0 prevents grouping)
    terms_a = [_make_term(f"alpha_{i}") for i in range(3)]
    terms_b = [_make_term(f"beta_{i}") for i in range(3)]
    all_terms = terms_a + terms_b
    term_repo = DummyTermRepo(source_language="Japanese", terms=all_terms)
    recorder = RecordingGlossaryTranslatorStrategy()
    progress_updates = []

    def progress_cb(update):
        progress_updates.append(update)

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("Japanese"),
        glossary_translator=recorder,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.translate_terms(
        translation_name_similarity_threshold=1.0,  # separate components
        concurrency=5,
        max_terms_per_batch=5,
        progress_callback=progress_cb,
    )

    # Initial progress (0/total) + one per bin
    assert len(progress_updates) >= 2
    assert progress_updates[0].current == 0
    assert progress_updates[-1].current == progress_updates[-1].total
    # All updates should be TRANSLATE_GLOSSARY step
    from context_aware_translation.core.progress import WorkflowStep

    assert all(u.step == WorkflowStep.TRANSLATE_GLOSSARY for u in progress_updates)


@pytest.mark.asyncio
async def test_translate_terms_progress_reports_when_all_already_translated():
    """Progress should still be reported for bins where all terms are already translated."""
    terms = [
        _make_term("already_done_1", translated_name="trans1"),
        _make_term("already_done_2", translated_name="trans2"),
        _make_term("needs_work", translated_name=None),
    ]
    term_repo = DummyTermRepo(source_language="Japanese", terms=terms)
    recorder = RecordingGlossaryTranslatorStrategy()
    progress_updates = []

    def progress_cb(update):
        progress_updates.append(update)

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("Japanese"),
        glossary_translator=recorder,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.translate_terms(
        translation_name_similarity_threshold=0.0,
        concurrency=1,
        max_terms_per_batch=20,
        progress_callback=progress_cb,
    )

    # Should have at least initial + final progress update
    assert len(progress_updates) >= 2
    assert progress_updates[0].current == 0
    assert progress_updates[-1].current == progress_updates[-1].total


@pytest.mark.asyncio
async def test_translate_terms_progress_reports_mixed_small_and_large():
    """Progress should report correctly with a mix of small and large components."""
    # Large component (>5 untranslated) — will be split into sub-batches
    large_terms = [_make_term(f"big_{i:02d}") for i in range(12)]
    # Small component — will be bin-packed
    small_terms = [_make_term(f"small_{i}") for i in range(3)]
    all_terms = large_terms + small_terms
    term_repo = DummyTermRepo(source_language="Japanese", terms=all_terms)
    recorder = RecordingGlossaryTranslatorStrategy()
    progress_updates = []

    def progress_cb(update):
        progress_updates.append(update)

    manager = TranslationContextManager(
        term_repo=term_repo,
        context_tree=DummyContextTree(),
        context_extractor=DummyContextExtractor(),
        tokenizer=DummyTokenizer(),
        source_language_detector=DetectLanguageStrategy("Japanese"),
        glossary_translator=recorder,
        chunk_translator=ChunkTranslatorStrategy(),
        term_reviewer=None,
    )

    await manager.translate_terms(
        translation_name_similarity_threshold=1.0,  # separate large from small
        concurrency=1,
        max_terms_per_batch=5,
        progress_callback=progress_cb,
    )

    # Large: 12 terms / 5 per batch = 3 sub-batches
    # Small: 3 terms = 1 bin
    # Total work units = 4
    # Progress updates = 1 initial + 4 = 5
    assert progress_updates[0].current == 0
    assert progress_updates[-1].current == progress_updates[-1].total
    # Monotonically increasing
    for i in range(1, len(progress_updates)):
        assert progress_updates[i].current >= progress_updates[i - 1].current


# ---------------------------------------------------------------------------
# JSON-based integration test using test-terms.json
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Slow integration test (~110s)")
@pytest.mark.asyncio
async def test_batching_against_expected_json():
    """Load real terms from test-terms.json, run the batching algorithm, and
    compare the LLM calls against expected_batching_output.json.

    This allows manual evaluation of the algorithm by inspecting the JSON files.
    The expected JSON contains both the untranslated terms per batch and the
    translated context available to each batch (accumulated from prior batches).
    """
    test_dir = Path(__file__).parent
    terms_path = test_dir / "test-terms.json"
    expected_path = test_dir / "expected_batching_output.json"

    if not terms_path.exists():
        pytest.skip("test-terms.json not found")
    if not expected_path.exists():
        pytest.skip("expected_batching_output.json not found")

    with open(terms_path, encoding="utf-8") as f:
        raw_data = json.load(f)
    with open(expected_path, encoding="utf-8") as f:
        expected = json.load(f)

    raw_terms = raw_data["待翻译术语组"]
    max_batch = expected["max_terms_per_batch"]

    # Build Term objects (all untranslated, votes=1 — single large component)
    terms = [
        Term(
            key=raw["待翻译名称"],
            descriptions={"0": raw["描述"]},
            occurrence={str(i): 1},
            votes=1,
            total_api_calls=1,
        )
        for i, raw in enumerate(raw_terms)
    ]

    # Run the split algorithm (same as what translate_terms uses for large components)
    sub_batches = TranslationContextManager._greedy_nearest_neighbor_split(terms, max_batch)

    # Simulate sequential processing to build translated context per batch
    translated: dict[str, str] = {}
    actual_calls = []
    for batch in sub_batches:
        to_translate_items = [
            {"canonical_name": t.key, "description": t.descriptions["0"], "missing_names": t.key} for t in batch
        ]
        similar_terms = TranslationContextManager._collect_similar_terms(to_translate_items, translated)
        actual_calls.append(
            {
                "untranslated": [t.key for t in batch],
                "translated_context": dict(similar_terms),
            }
        )
        # Simulate translation
        for t in batch:
            translated[t.key] = f"translated-{t.key}"

    # Structural assertions
    assert len(actual_calls) == expected["total_batches"]
    for i, (actual, exp) in enumerate(zip(actual_calls, expected["calls"])):
        assert actual["untranslated"] == exp["untranslated"], (
            f"Batch {i} untranslated mismatch: got {actual['untranslated'][:3]}... "
            f"expected {exp['untranslated'][:3]}..."
        )
        assert actual["translated_context"] == exp["translated_context"], f"Batch {i} translated_context mismatch"

    # First batch should have no translated context
    assert expected["calls"][0]["translated_context"] == {}

    # Later batches should have growing translated context
    assert len(expected["calls"][10]["translated_context"]) > 0

    # All terms covered
    actual_keys = {k for call in actual_calls for k in call["untranslated"]}
    assert len(actual_keys) == expected["total_terms"]

    # No batch exceeds max size
    for call in actual_calls:
        assert len(call["untranslated"]) <= max_batch
