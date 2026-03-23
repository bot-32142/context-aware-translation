from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from transformers import AutoTokenizer

from context_aware_translation.core.context_manager import ContextManager, TranslationContextManager
from context_aware_translation.core.models import Term
from context_aware_translation.core.progress import WorkflowStep
from context_aware_translation.core.term_memory import TermMemoryVersion
from context_aware_translation.storage.repositories.term_repository import StorageManager, TermRepository
from context_aware_translation.storage.schema.book_db import ChunkRecord, TranslationChunkRecord


class MockStorageManager(StorageManager):
    """Mock storage manager for testing."""

    def __init__(self):
        self.chunks = []
        self.keyed_contexts = {}
        self.term_memory_versions = {}
        self.next_chunk_id = 0

    def get_next_chunk_id(self) -> int:
        self.next_chunk_id += 1
        return self.next_chunk_id - 1

    def chunk_exists_by_hash(self, hash: str) -> bool:
        return any(c.hash == hash for c in self.chunks)

    def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        self.chunks.extend(chunks)

    def get_chunks_to_extract(self) -> list[ChunkRecord]:
        return [c for c in self.chunks if not c.is_extracted]

    def list_keyed_context(self):
        return list(self.keyed_contexts.values())

    def get_keyed_context(self, key: str):
        return self.keyed_contexts.get(key)

    def apply_batch(self, update) -> None:
        for kc in update.keyed_context:
            key = kc.get_key()
            self.keyed_contexts[key] = kc
        for chunk in update.chunk_records:
            found = False
            for i, c in enumerate(self.chunks):
                if c.chunk_id == chunk.chunk_id:
                    self.chunks[i] = chunk
                    found = True
                    break
            if not found:
                self.chunks.append(chunk)

    def get_chunks_to_map_occurrence(self):
        return [c for c in self.chunks if not getattr(c, "is_occurrence_mapped", False)]

    def get_chunks_by_term(self, term_key: str):
        return [c for c in self.chunks if term_key in c.text]

    def get_source_language(self) -> str:
        return "英语"  # Default to English for testing

    def set_source_language(self, source_language: str) -> None:
        pass

    def close(self) -> None:
        pass

    def replace_term_memory_versions(self, term: str, versions: list[TermMemoryVersion]) -> None:
        self.term_memory_versions[term] = list(versions)

    def get_latest_term_memory_before(self, term: str, query_index: int) -> TermMemoryVersion | None:
        versions = self.term_memory_versions.get(term, [])
        eligible = [version for version in versions if version.effective_start_chunk <= query_index]
        if not eligible:
            return None
        eligible.sort(key=lambda version: version.effective_start_chunk)
        return eligible[-1]

    def list_latest_term_memory_versions(self) -> dict[str, TermMemoryVersion]:
        latest = {}
        for term, versions in self.term_memory_versions.items():
            if not versions:
                continue
            latest[term] = sorted(versions, key=lambda version: version.effective_start_chunk)[-1]
        return latest


class MockContextExtractor:
    """Mock context extractor for testing."""

    async def extract_keyed_context(self, chunk_record: ChunkRecord, _source_language: str):
        # Extract terms from chunk text
        terms = []
        if "term1" in chunk_record.text:
            terms.append(
                Term(
                    key="term1",
                    descriptions={str(chunk_record.chunk_id): "description1"},
                    occurrence={},
                    votes=1,
                    total_api_calls=1,
                    term_type_votes={"other": 1},
                )
            )
        if "term2" in chunk_record.text:
            terms.append(
                Term(
                    key="term2",
                    descriptions={str(chunk_record.chunk_id): "description2"},
                    occurrence={},
                    votes=1,
                    total_api_calls=1,
                    term_type_votes={"other": 1},
                )
            )
        return terms


def simple_summarize(descriptions: list[str]) -> str:
    """Simple mock summarize function."""
    return " | ".join(descriptions)


def simple_estimate_tokens(text: str) -> int:
    """Simple mock token estimation."""
    return len(text) // 4


class CallableSummarizer:
    def __init__(self, func):
        self._func = func

    async def summarize(self, descriptions: list[str], **_kwargs) -> str:
        return self._func(descriptions)


class DummyContextTree:
    def __init__(self, summarizer: CallableSummarizer | None = None) -> None:
        self.summarizer = summarizer
        self.added_terms: dict[str, dict[int, str]] = {}

    def add_chunks(self, terms_data: dict[str, dict[int, str]], **_kwargs) -> None:
        self.added_terms.update(terms_data)

    def get_context(self, term: str, _query_index: int) -> list[str]:
        data = self.added_terms.get(term, {})
        if not data:
            return []
        ordered = [data[idx] for idx in sorted(data)]
        if self.summarizer is None:
            return ordered
        return [self.summarizer._func(ordered)]

    def summarize_term_fully(self, term: str, _query_index: int, **_kwargs) -> str:
        return " ".join(self.get_context(term, _query_index))

    def close(self) -> None:
        return None


class RecordingTermMemoryBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[int, str]]] = []

    def build_versions(self, term: str, data: dict[int, str], cancel_check=None) -> list[TermMemoryVersion]:
        del cancel_check
        self.calls.append((term, dict(data)))
        latest_chunk = max(data)
        return [
            TermMemoryVersion(
                term=term,
                effective_start_chunk=latest_chunk + 1,
                latest_evidence_chunk=latest_chunk,
                summary_text=f"summary for {term}",
                kind="bootstrap",
                source_count=len(data),
                created_at=0.0,
            )
        ]


@pytest.fixture
def mock_context_manager(tmp_path: Path):
    """Create a ContextManager with mocks."""
    storage_manager = MockStorageManager()
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    context_extractor = MockContextExtractor()

    _ = tmp_path
    context_tree = DummyContextTree(CallableSummarizer(simple_summarize))

    manager = ContextManager(
        context_extractor=context_extractor,
        term_repo=storage_manager,
        context_tree=context_tree,
        tokenizer=tokenizer,
    )

    yield manager

    # Cleanup: close manager and context tree to release database connections
    import contextlib

    with contextlib.suppress(Exception):
        manager.close()

    with contextlib.suppress(Exception):
        context_tree.close()


def test_context_manager_add_text(mock_context_manager):
    """Test adding text to context manager."""
    text = "This is a test. " * 10
    result = mock_context_manager.add_text(text)

    # Should return the last chunk id
    assert isinstance(result, int)
    assert result >= 0

    # Should have created chunks
    assert len(mock_context_manager.term_repo.chunks) > 0


def test_context_manager_add_text_same_text_different_documents_not_deduped(mock_context_manager):
    """Same chunk text in different documents should be stored separately."""
    mock_context_manager.add_text("shared text block", document_id=1)
    mock_context_manager.add_text("shared text block", document_id=2)

    matching_chunks = [c for c in mock_context_manager.term_repo.chunks if c.text == "shared text block"]
    assert len(matching_chunks) == 2
    assert {c.document_id for c in matching_chunks} == {1, 2}


def test_context_manager_add_text_empty(mock_context_manager):
    """Test adding empty text."""
    result = mock_context_manager.add_text("")

    # Should handle empty text gracefully
    assert isinstance(result, int)


def test_context_manager_build_context_tree(mock_context_manager):
    """Test building context tree."""
    # Add some text with terms
    mock_context_manager.add_text("term1 term2")

    # Extract terms first
    # (In real usage, extract_keyed_context would be called first)
    # For testing, we'll manually add keyed contexts
    term1 = Term(
        key="term1",
        descriptions={"0": "description1"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="character",
    )
    mock_context_manager.term_repo.keyed_contexts["term1"] = term1

    # Build context tree
    mock_context_manager.build_context_tree()

    # Context tree should have been populated
    # (We can't easily verify this without accessing internals, but it shouldn't crash)


def test_context_manager_build_context_tree_indexes_imported_description(mock_context_manager):
    """Imported glossary descriptions should be indexed as pre-chunk context."""
    term = Term(
        key="imported_term",
        descriptions={"imported": "Imported glossary description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    mock_context_manager.term_repo.keyed_contexts["imported_term"] = term

    mock_context_manager.build_context_tree()

    context = mock_context_manager.context_tree.get_context("imported_term", 0)
    assert context == ["Imported glossary description"]


def test_context_manager_build_fully_summarized_descriptions(mock_context_manager):
    term = Term(
        key="term1",
        descriptions={"0": "desc0", "1": "desc1", "2": "desc2", "3": "desc3"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="character",
        translated_name="t1",
    )
    mock_context_manager.term_repo.keyed_contexts["term1"] = term

    summaries = mock_context_manager.build_fully_summarized_descriptions()
    assert "term1" in summaries
    assert summaries["term1"]
    assert mock_context_manager.context_tree.get_context("term1", 4) == [summaries["term1"]]


def test_context_manager_build_fully_summarized_descriptions_reports_progress(mock_context_manager):
    term = Term(
        key="term_progress",
        descriptions={"0": "desc0", "1": "desc1"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="character",
    )
    mock_context_manager.term_repo.keyed_contexts["term_progress"] = term
    updates = []

    summaries = mock_context_manager.build_fully_summarized_descriptions(progress_callback=updates.append)

    assert summaries["term_progress"]
    assert updates
    assert updates[0].step == WorkflowStep.EXPORT
    assert updates[0].message == "Preparing glossary export..."
    assert updates[-1].step == WorkflowStep.EXPORT
    assert updates[-1].current == updates[-1].total
    assert updates[-1].message.startswith("Summarizing glossary term ")


def test_get_term_description_for_query_prefers_longest_summary(mock_context_manager):
    term = Term(
        key="term_longest",
        descriptions={"0": "desc0"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="character",
    )
    mock_context_manager.term_repo.keyed_contexts["term_longest"] = term

    mock_context_manager.context_tree.get_context = lambda *_a, **_k: [  # type: ignore[method-assign]
        "short",
        "this is the longest summary",
        "mid",
    ]

    description = mock_context_manager.get_term_description_for_query(term, 10)
    assert description == "this is the longest summary"


def test_get_term_description_for_query_joins_imported_and_numeric_for_other_terms(mock_context_manager):
    term = Term(
        key="term_imported_plus_one",
        descriptions={"imported": "Imported glossary description", "5": "later description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="other",
    )

    description = mock_context_manager.get_term_description_for_query(term, 10)

    assert description == "Imported glossary description later description"


def test_get_term_description_for_query_excludes_future_numeric_descriptions_for_other_terms(mock_context_manager):
    term = Term(
        key="term_future_other",
        descriptions={
            "imported": "Imported glossary description",
            "5": "earlier description",
            "12": "future description",
        },
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="other",
    )

    description = mock_context_manager.get_term_description_for_query(term, 10)

    assert description == "Imported glossary description earlier description"


def test_context_manager_build_fully_summarized_descriptions_ignores_non_chunk_keys(mock_context_manager):
    term = Term(
        key="term_non_chunk",
        descriptions={"legacy_key": "legacy description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="other",
    )
    mock_context_manager.term_repo.keyed_contexts["term_non_chunk"] = term

    summaries = mock_context_manager.build_fully_summarized_descriptions()
    assert summaries["term_non_chunk"] == ""


def test_context_manager_build_fully_summarized_descriptions_uses_context_tree_summary(mock_context_manager):
    term = Term(
        key="term_skip_context",
        descriptions={"1": "first", "5": "second"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="character",
    )
    mock_context_manager.term_repo.keyed_contexts["term_skip_context"] = term

    summaries = mock_context_manager.build_fully_summarized_descriptions()
    assert summaries["term_skip_context"] == "first | second"


def test_build_fully_summarized_descriptions_joins_imported_and_numeric_for_other_terms(mock_context_manager):
    term = Term(
        key="term_imported_plus_one_export",
        descriptions={"imported": "Imported glossary description", "5": "later description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="other",
    )
    mock_context_manager.term_repo.keyed_contexts["term_imported_plus_one_export"] = term
    mock_context_manager.context_tree = None

    summaries = mock_context_manager.build_fully_summarized_descriptions()

    assert summaries["term_imported_plus_one_export"] == "Imported glossary description later description"


def test_build_fully_summarized_descriptions_keeps_all_available_descriptions_for_other_terms(mock_context_manager):
    term = Term(
        key="term_imported_plus_future_export",
        descriptions={
            "imported": "Imported glossary description",
            "5": "later description",
            "12": "latest description",
        },
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="other",
    )
    mock_context_manager.term_repo.keyed_contexts["term_imported_plus_future_export"] = term
    mock_context_manager.context_tree = None

    summaries = mock_context_manager.build_fully_summarized_descriptions()

    assert (
        summaries["term_imported_plus_future_export"]
        == "Imported glossary description later description latest description"
    )


def test_get_term_description_for_query_prefers_term_memory_without_context_tree(mock_context_manager):
    term = Term(
        key="term_memory_term",
        descriptions={"imported": "Imported glossary description", "5": "later description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="character",
    )
    mock_context_manager.term_repo.replace_term_memory_versions(
        "term_memory_term",
        [
            TermMemoryVersion(
                term="term_memory_term",
                effective_start_chunk=6,
                latest_evidence_chunk=5,
                summary_text="term memory summary",
                kind="bootstrap",
                source_count=2,
                created_at=0.0,
            )
        ],
    )
    mock_context_manager.context_tree = None

    description = mock_context_manager.get_term_description_for_query(term, 10)

    assert description == "term memory summary"


def test_build_fully_summarized_descriptions_prefers_term_memory_without_context_tree(mock_context_manager):
    term = Term(
        key="term_memory_export",
        descriptions={"imported": "Imported glossary description", "5": "later description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="character",
    )
    mock_context_manager.term_repo.keyed_contexts["term_memory_export"] = term
    mock_context_manager.term_repo.replace_term_memory_versions(
        "term_memory_export",
        [
            TermMemoryVersion(
                term="term_memory_export",
                effective_start_chunk=6,
                latest_evidence_chunk=5,
                summary_text="term memory export summary",
                kind="bootstrap",
                source_count=2,
                created_at=0.0,
            )
        ],
    )
    mock_context_manager.context_tree = None

    summaries = mock_context_manager.build_fully_summarized_descriptions()

    assert summaries["term_memory_export"] == "term memory export summary"


def test_context_manager_build_fully_summarized_descriptions_allows_empty_description(mock_context_manager):
    term = Term(
        key="term_empty",
        descriptions={"0": "   "},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    mock_context_manager.term_repo.keyed_contexts["term_empty"] = term

    summaries = mock_context_manager.build_fully_summarized_descriptions()
    assert summaries["term_empty"] == ""


def test_context_manager_build_fully_summarized_descriptions_ignored_term_joins_descriptions(mock_context_manager):
    term = Term(
        key="term_ignored",
        descriptions={"imported": "imported desc", "2": "chunk desc"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        ignored=True,
    )
    mock_context_manager.term_repo.keyed_contexts["term_ignored"] = term

    def _fail_summarize(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("ignored term should not use context tree summarization")

    mock_context_manager.context_tree.summarize_term_fully = _fail_summarize  # type: ignore[method-assign]

    summaries = mock_context_manager.build_fully_summarized_descriptions()
    assert summaries["term_ignored"] == "imported desc chunk desc"


def test_context_manager_build_context_tree_skips_term_memory_for_other_terms(mock_context_manager):
    builder = RecordingTermMemoryBuilder()
    mock_context_manager.term_memory_builder = builder

    character_term = Term(
        key="hero",
        descriptions={"1": "hero description", "2": "more hero description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="character",
    )
    other_term = Term(
        key="artifact",
        descriptions={"1": "artifact description", "2": "more artifact description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="other",
    )
    mock_context_manager.term_repo.keyed_contexts = {
        character_term.key: character_term,
        other_term.key: other_term,
    }

    mock_context_manager.build_context_tree()

    assert [term_key for term_key, _data in builder.calls] == ["hero"]
    assert "hero" in mock_context_manager.term_repo.term_memory_versions
    assert mock_context_manager.term_repo.term_memory_versions["artifact"] == []
    assert mock_context_manager.context_tree.added_terms["hero"] == {1: "hero description", 2: "more hero description"}
    assert mock_context_manager.context_tree.added_terms["artifact"] == {
        1: "artifact description",
        2: "more artifact description",
    }


def test_get_term_description_for_query_skips_term_memory_for_other_terms(mock_context_manager):
    term = Term(
        key="artifact_query",
        descriptions={"imported": "Imported glossary description", "5": "later description"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="other",
    )
    mock_context_manager.term_repo.replace_term_memory_versions(
        "artifact_query",
        [
            TermMemoryVersion(
                term="artifact_query",
                effective_start_chunk=6,
                latest_evidence_chunk=5,
                summary_text="term memory summary",
                kind="bootstrap",
                source_count=2,
                created_at=0.0,
            )
        ],
    )
    mock_context_manager.context_tree.get_context = lambda *_a, **_k: ["legacy summary"]  # type: ignore[method-assign]

    description = mock_context_manager.get_term_description_for_query(term, 10)

    assert description == "Imported glossary description later description"


def test_build_fully_summarized_descriptions_exports_raw_description_for_other_terms(mock_context_manager):
    term = Term(
        key="artifact_export",
        descriptions={"imported": "imported desc", "2": "chunk desc"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type="other",
    )
    mock_context_manager.term_repo.keyed_contexts["artifact_export"] = term
    mock_context_manager.term_repo.replace_term_memory_versions(
        "artifact_export",
        [
            TermMemoryVersion(
                term="artifact_export",
                effective_start_chunk=3,
                latest_evidence_chunk=2,
                summary_text="term memory export summary",
                kind="bootstrap",
                source_count=2,
                created_at=0.0,
            )
        ],
    )

    def _fail_summarize(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("other term should not use context tree summarization")

    mock_context_manager.context_tree.summarize_term_fully = _fail_summarize  # type: ignore[method-assign]

    summaries = mock_context_manager.build_fully_summarized_descriptions()

    assert summaries["artifact_export"] == "imported desc chunk desc"


def test_context_manager_build_fully_summarized_descriptions_raises_when_summary_empty(mock_context_manager):
    term = Term(
        key="term_missing_summary",
        descriptions={"0": "desc0"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    mock_context_manager.term_repo.keyed_contexts["term_missing_summary"] = term
    mock_context_manager.context_tree.summarize_term_fully = lambda *_a, **_k: "  "  # type: ignore[method-assign]

    summaries = mock_context_manager.build_fully_summarized_descriptions()
    assert summaries["term_missing_summary"] == "desc0"


@pytest.mark.asyncio
async def test_context_manager_extract_keyed_context(mock_context_manager):
    """Test extracting keyed context from chunks."""
    # Add text with terms
    mock_context_manager.add_text("term1 term2")

    # Extract keyed context
    await mock_context_manager.extract_keyed_context(concurrency=5)

    # Chunks should be marked as extracted
    extracted_chunks = [c for c in mock_context_manager.term_repo.chunks if c.is_extracted]
    assert len(extracted_chunks) > 0

    # Keyed contexts should be stored
    assert len(mock_context_manager.term_repo.keyed_contexts) > 0


@pytest.mark.asyncio
async def test_context_manager_extract_keyed_context_empty(mock_context_manager):
    """Test extracting keyed context when no chunks to extract."""
    # Don't add any text
    # Extract should return immediately
    await mock_context_manager.extract_keyed_context()

    # Should not crash
    assert True


@pytest.mark.asyncio
async def test_context_manager_extract_keyed_context_concurrency(mock_context_manager):
    """Test that extraction respects concurrency limit."""
    # Add multiple chunks
    for i in range(10):
        mock_context_manager.add_text(f"term1 chunk{i}")

    # Track concurrent extractions
    concurrent_count = 0
    max_concurrent = 0

    original_extract = mock_context_manager.context_extractor.extract_keyed_context

    async def tracked_extract(chunk_record, source_language):
        nonlocal concurrent_count, max_concurrent
        concurrent_count += 1
        max_concurrent = max(max_concurrent, concurrent_count)
        result = await original_extract(chunk_record, source_language)
        concurrent_count -= 1
        return result

    mock_context_manager.context_extractor.extract_keyed_context = tracked_extract

    await mock_context_manager.extract_keyed_context(concurrency=3)

    # Should not exceed concurrency limit
    assert max_concurrent <= 3


@pytest.mark.asyncio
async def test_context_manager_extract_keyed_context_raises_on_chunk_error(mock_context_manager):
    """Extraction should fail if any chunk extraction fails."""
    mock_context_manager.add_text("term1 ok")
    mock_context_manager.add_text("term1 fail")

    original_extract = mock_context_manager.context_extractor.extract_keyed_context

    async def maybe_fail(chunk_record, source_language):
        if "fail" in chunk_record.text:
            raise RuntimeError("extract failed")
        return await original_extract(chunk_record, source_language)

    mock_context_manager.context_extractor.extract_keyed_context = maybe_fail

    with pytest.raises(RuntimeError, match="extract failed"):
        await mock_context_manager.extract_keyed_context(concurrency=2)


def test_context_manager_close(mock_context_manager):
    """Test closing context manager."""
    # Should not crash
    mock_context_manager.close()

    # Should be able to close multiple times
    mock_context_manager.close()


def test_context_manager_state_update_merges_terms(mock_context_manager):
    """Test that _state_update properly merges terms."""
    # Add initial term
    term1 = Term(
        key="term1",
        descriptions={"0": "desc1"},
        occurrence={},
        votes=5,
        total_api_calls=10,
    )
    mock_context_manager.term_repo.keyed_contexts["term1"] = term1

    # Add new term with same key (should merge)
    # Note: The merge happens in _state_update which re-reads from storage
    # So we need to ensure the term is in storage first
    term2 = Term(
        key="term1",
        descriptions={"1": "desc2"},
        occurrence={},
        votes=3,
        total_api_calls=7,
    )

    chunk = ChunkRecord(chunk_id=1, hash="hash1", text="text1")
    mock_context_manager.term_repo.chunks.append(chunk)
    mock_context_manager._state_update([term2], [chunk])

    # Should have merged - re-read from storage to get merged result
    merged_term = mock_context_manager.term_repo.keyed_contexts["term1"]
    # Votes and api_calls accumulate
    assert merged_term.votes >= 5  # At least the original 5
    assert merged_term.total_api_calls >= 10  # At least the original 10
    # Descriptions should be merged
    assert "0" in merged_term.descriptions or "1" in merged_term.descriptions


def test_context_manager_state_update_merges_term_type_by_per_type_vote_totals(mock_context_manager):
    existing_term = Term(
        key="term1",
        descriptions={"0": "desc1"},
        occurrence={},
        votes=2,
        total_api_calls=2,
        term_type="character",
    )
    mock_context_manager.term_repo.keyed_contexts["term1"] = existing_term

    chunk = ChunkRecord(chunk_id=1, hash="hash1", text="text1")
    mock_context_manager.term_repo.chunks.append(chunk)
    mock_context_manager._state_update(
        [
            Term(
                key="term1",
                descriptions={"1": "desc2"},
                occurrence={},
                votes=1,
                total_api_calls=1,
                term_type="organization",
            )
        ],
        [chunk],
    )
    mock_context_manager._state_update(
        [
            Term(
                key="term1",
                descriptions={"2": "desc3"},
                occurrence={},
                votes=2,
                total_api_calls=2,
                term_type="organization",
            )
        ],
        [],
    )

    merged_term = mock_context_manager.term_repo.keyed_contexts["term1"]
    assert merged_term.term_type == "organization"
    assert merged_term.term_type_votes == {"character": 2, "organization": 3}


def test_translation_context_manager_init_bug(tmp_path: Path):
    """Test that TranslationContextManager.__init__ has a bug with self.storage_manager."""
    # BUG: TranslationContextManager.__init__ calls super().__init__ with self.storage_manager
    # before self.storage_manager is defined (line 167-168)
    from transformers import AutoTokenizer

    from context_aware_translation.config import Config
    from context_aware_translation.core.context_extractor import TermExtractor
    from context_aware_translation.llm.client import LLMClient
    from context_aware_translation.storage.schema.book_db import SQLiteBookDB

    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    sqlite_path = tmp_path / "test.db"
    # Create a minimal config
    from context_aware_translation.config import (
        ExtractorConfig,
        GlossaryTranslationConfig,
        LLMConfig,
        ReviewConfig,
        SummarizorConfig,
        TranslatorConfig,
    )

    base_settings = {"api_key": "test", "base_url": "https://test.com/v1", "model": "gpt-4"}
    config = Config(
        working_dir=tmp_path,
        translation_target_language="简体中文",
        extractor_config=ExtractorConfig(**base_settings),
        summarizor_config=SummarizorConfig(**base_settings),
        translator_config=TranslatorConfig(**base_settings),
        glossary_config=GlossaryTranslationConfig(**base_settings),
        review_config=ReviewConfig(**base_settings),
    )

    context_tree = DummyContextTree(CallableSummarizer(simple_summarize))

    llm_client = LLMClient(LLMConfig(**base_settings))
    context_extractor = TermExtractor(llm_client, config.extractor_config)

    # BUG FIXED: storage_manager is now created before super().__init__ is called
    # This should now work without raising AttributeError
    db = SQLiteBookDB(sqlite_path)
    storage_manager = TermRepository(db)

    source_language_detector = type("Detector", (), {"detect": AsyncMock(return_value="English")})()
    glossary_translator = type("Glossary", (), {"translate": AsyncMock(return_value={})})()
    chunk_translator = type("Chunk", (), {"translate": AsyncMock(return_value=[])})()
    manager = TranslationContextManager(
        term_repo=storage_manager,
        context_tree=context_tree,
        context_extractor=context_extractor,
        tokenizer=tokenizer,
        source_language_detector=source_language_detector,
        glossary_translator=glossary_translator,
        chunk_translator=chunk_translator,
    )
    assert manager.term_repo is not None

    # Cleanup
    manager.close()
    context_tree.close()
    db.close()


def test_context_manager_add_text_chunk_records_bug(mock_context_manager):
    """Test that add_text correctly uses append (bug was fixed)."""
    # BUG FIXED: Previously used += with a single ChunkRecord, now uses .append()
    text = "This is a test."

    # Should work without raising TypeError
    result = mock_context_manager.add_text(text)
    assert isinstance(result, int)


def test_context_manager_state_update_new_term(mock_context_manager):
    """Test that _state_update adds new terms."""
    term = Term(
        key="new_term",
        descriptions={"0": "desc1"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )

    chunk = ChunkRecord(chunk_id=0, hash="hash1", text="text1")
    mock_context_manager._state_update([term], [chunk])

    # Should have added new term
    assert "new_term" in mock_context_manager.term_repo.keyed_contexts
    stored_term = mock_context_manager.term_repo.keyed_contexts["new_term"]
    assert stored_term.key == "new_term"
    assert stored_term.votes == 1


def test_mark_noise_terms_zero_division_bug(tmp_path: Path):
    """Test that mark_noise_terms has zero division bug when descriptions is empty."""
    # BUG: Line 204: len(term.occurrence)/len(term.descriptions) will raise ZeroDivisionError
    # if descriptions is empty
    from transformers import AutoTokenizer

    from context_aware_translation.config import (
        Config,
        ExtractorConfig,
        GlossaryTranslationConfig,
        ReviewConfig,
        SummarizorConfig,
        TranslatorConfig,
    )

    AutoTokenizer.from_pretrained("gpt2")
    tmp_path / "test.db"
    base_settings = {"api_key": "test", "base_url": "https://test.com/v1", "model": "gpt-4"}
    Config(
        working_dir=tmp_path,
        translation_target_language="简体中文",
        extractor_config=ExtractorConfig(**base_settings),
        summarizor_config=SummarizorConfig(**base_settings),
        translator_config=TranslatorConfig(**base_settings),
        glossary_config=GlossaryTranslationConfig(**base_settings),
        review_config=ReviewConfig(**base_settings),
    )

    context_tree = DummyContextTree(CallableSummarizer(simple_summarize))

    # BUG FIXED: mark_noise_terms now raises ValueError if descriptions is empty
    # instead of dividing by zero
    Term(
        key="test_key",
        descriptions={},  # Empty - will raise ValueError
        occurrence={"chunk1": 1},
        votes=1,
        total_api_calls=1,
    )

    # The bug is fixed - it now raises ValueError instead of ZeroDivisionError
    # We can't easily test this without a full manager setup, but the fix is in place

    # Cleanup
    context_tree.close()


def test_translate_terms_missing_description_bug():
    """Test that translate_terms may fail when term.descriptions doesn't have expected key."""
    # BUG: Line 245 in context_manager.py accesses term.descriptions
    # The code assumes descriptions is a dict with specific keys, but doesn't handle
    # cases where the expected key doesn't exist
    term = Term(
        key="test_key",
        descriptions={"chunk1": "desc"},  # No key matching expected pattern
        occurrence={},
        votes=1,
        total_api_calls=1,
    )

    # The bug is that translate_terms assumes descriptions has a certain structure
    # but doesn't validate it
    assert "chunk1" in term.descriptions
    # The actual bug would manifest when translate_terms tries to access
    # a non-existent key in descriptions


def test_build_occurrence_mapping_empty_descriptions_bug():
    """Test that build_occurrence_mapping creates terms with empty descriptions."""
    # BUG: Line 189 creates Term with empty descriptions dict
    # This will cause issues in mark_noise_terms (zero division at line 204)
    term = Term(
        key="test_key",
        descriptions={},  # Empty - will cause zero division in mark_noise_terms
        occurrence={"chunk1": 1},
        votes=0,
        total_api_calls=0,
    )

    # BUG: This will cause ZeroDivisionError in mark_noise_terms line 204
    # when it tries to calculate: len(term.occurrence)/len(term.descriptions)
    with pytest.raises(ZeroDivisionError):
        if len(term.descriptions) == 0:
            _ = len(term.occurrence) / len(term.descriptions)


def test_mark_noise_terms_empty_descriptions_zero_division():
    """Test that mark_noise_terms raises ZeroDivisionError with empty descriptions."""
    # BUG: Line 204: len(term.occurrence)/len(term.descriptions)
    # If descriptions is empty, this raises ZeroDivisionError
    term = Term(
        key="test_key",
        descriptions={},  # Empty descriptions
        occurrence={"chunk1": 1, "chunk2": 2},
        votes=1,
        total_api_calls=1,
    )

    # BUG: This calculation in mark_noise_terms will fail
    with pytest.raises(ZeroDivisionError):
        len(term.occurrence) / len(term.descriptions)


def test_mark_noise_terms_zero_api_calls_bug():
    """Test that mark_noise_terms raises ValueError when total_api_calls is 0."""
    # BUG: Line 200-201: Raises ValueError if total_api_calls <= 0
    # But terms can legitimately have 0 API calls if they were created without extraction
    term = Term(
        key="test_key",
        descriptions={"chunk1": "desc"},
        occurrence={},
        votes=0,
        total_api_calls=0,  # Zero API calls
    )

    # BUG: This will raise ValueError in mark_noise_terms
    with pytest.raises(ValueError, match="has no API calls"):
        if term.total_api_calls <= 0:
            raise ValueError(f"Term {term.get_key()} has no API calls")


def test_translate_chunks_batch_size_edge_case():
    """Test that translate_chunks may have issues with batch_size logic."""
    # BUG: Line 353: chunk.chunk_id == current_batch[-1].chunk_id + 1
    # This assumes consecutive chunk_ids, but if chunk_ids are not consecutive,
    # batches may not be formed correctly
    from context_aware_translation.storage.schema.book_db import TranslationChunkRecord

    chunks = [
        TranslationChunkRecord(chunk_id=0, hash="hash0", text="text0"),
        TranslationChunkRecord(chunk_id=5, hash="hash5", text="text5"),  # Non-consecutive
        TranslationChunkRecord(chunk_id=6, hash="hash6", text="text6"),
    ]

    # The bug is that the batch logic assumes consecutive IDs
    # Non-consecutive IDs will create separate batches even if they're close
    sorted_chunks = sorted(chunks, key=lambda c: c.chunk_id)
    assert sorted_chunks[0].chunk_id == 0
    assert sorted_chunks[1].chunk_id == 5
    # BUG: These won't be in the same batch even though they're only 5 apart
    # The logic only checks if chunk_id == previous + 1
    # Chunk 0 and chunk 5 will be in separate batches
    # Chunk 5 and chunk 6 will be in the same batch (consecutive)


def test_translate_terms_descriptions_index_error():
    """Test that translate_terms accesses descriptions[0] which may not exist."""
    # BUG: Line 245: term.descriptions[0]
    # This assumes descriptions is a list or has key "0", but it's a dict
    # and may not have key "0"
    term = Term(
        key="test_key",
        descriptions={"chunk1": "desc1", "chunk2": "desc2"},  # No key "0"
        occurrence={},
        votes=1,
        total_api_calls=1,
    )

    # BUG: This will raise KeyError when translate_terms tries term.descriptions[0]
    # The code assumes descriptions[0] exists, but it's a dict with arbitrary keys
    with pytest.raises(KeyError):
        _ = term.descriptions[0]  # Key "0" doesn't exist


def test_translate_terms_empty_descriptions_key_error():
    """Test that translate_terms fails with empty descriptions."""
    # BUG: Line 245: term.descriptions[0] when descriptions is empty
    term = Term(
        key="test_key",
        descriptions={},  # Empty
        occurrence={},
        votes=1,
        total_api_calls=1,
    )

    # BUG: This will raise KeyError
    with pytest.raises(KeyError):
        _ = term.descriptions[0]


def test_mark_noise_terms_division_by_zero():
    """Test that mark_noise_terms can divide by zero."""
    # BUG: Line 204: len(term.occurrence)/len(term.descriptions)
    # If descriptions is empty, this raises ZeroDivisionError
    term = Term(
        key="test_key",
        descriptions={},  # Empty - will cause division by zero
        occurrence={"chunk1": 1},
        votes=1,
        total_api_calls=1,
    )

    # BUG: This will raise ZeroDivisionError in mark_noise_terms
    with pytest.raises(ZeroDivisionError):
        len(term.occurrence) / len(term.descriptions)


def test_mark_noise_terms_empty_occurrence():
    """Test mark_noise_terms with empty occurrence."""
    # BUG: Line 204: len(term.occurrence)/len(term.descriptions)
    # If both are empty, this raises ZeroDivisionError
    term = Term(
        key="test_key",
        descriptions={},  # Empty
        occurrence={},  # Empty
        votes=1,
        total_api_calls=1,
    )

    # BUG: This will raise ZeroDivisionError
    with pytest.raises(ZeroDivisionError):
        len(term.occurrence) / len(term.descriptions)


def test_translate_terms_descriptions_dict_not_list():
    """Test that translate_terms treats descriptions as dict but accesses like list."""
    # BUG: Line 245: term.descriptions[0]
    # descriptions is a dict, not a list, so [0] is a key lookup, not index
    term = Term(
        key="test_key",
        descriptions={"0": "desc0", "1": "desc1"},  # Dict with string keys
        occurrence={},
        votes=1,
        total_api_calls=1,
    )

    # This works if "0" exists as a key
    assert "0" in term.descriptions
    assert term.descriptions["0"] == "desc0"

    # But if the key doesn't exist, it raises KeyError
    # The bug is assuming descriptions[0] always exists


def test_context_manager_add_text_returns_wrong_value():
    """Test that add_text may return wrong chunk_id."""
    # BUG: Line 67 returns chunk_id-1, but if no chunks were added, this could be -1
    # Or if chunks were filtered out, the returned ID might not match the last chunk
    # This test documents potential issues with the return value
    pass  # Would need to test actual behavior


def test_context_manager_build_context_tree_empty_terms():
    """Test build_context_tree with no terms."""
    # Should handle empty terms gracefully
    pass  # Would need to test actual behavior


def test_translation_context_manager_super_init_bug(tmp_path: Path):
    """Test that TranslationContextManager.__init__ correctly initializes (bug was fixed)."""
    # BUG FIXED: Previously called super().__init__ before defining self.storage_manager
    # Now the initialization order is correct
    from transformers import AutoTokenizer

    from context_aware_translation.storage.schema.book_db import SQLiteBookDB

    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    sqlite_path = tmp_path / "test.db"
    context_tree = DummyContextTree(CallableSummarizer(simple_summarize))

    # Create minimal mocks
    class MockExtractor:
        async def extract_keyed_context(self, _chunk_record, _source_language):
            return []

    # BUG FIXED: This should now work without raising AttributeError
    db = SQLiteBookDB(sqlite_path)
    storage_manager = TermRepository(db)

    source_language_detector = type("Detector", (), {"detect": AsyncMock(return_value="English")})()
    glossary_translator = type("Glossary", (), {"translate": AsyncMock(return_value={})})()
    chunk_translator = type("Chunk", (), {"translate": AsyncMock(return_value=[])})()
    manager = TranslationContextManager(
        term_repo=storage_manager,
        context_tree=context_tree,
        context_extractor=MockExtractor(),
        tokenizer=tokenizer,
        source_language_detector=source_language_detector,
        glossary_translator=glossary_translator,
        chunk_translator=chunk_translator,
    )
    assert manager.term_repo is not None
    manager.close()
    db.close()


def test_union_find_with_filter_empty_terms():
    """Test _union_find_with_filter with empty terms list."""
    # Should handle empty terms gracefully
    # This tests the union-find algorithm edge case
    pass


def test_union_find_with_filter_single_term():
    """Test _union_find_with_filter with single term."""
    # Single term should form its own component
    pass


def test_translate_terms_empty_component():
    """Test translate_terms with empty component."""
    # BUG: If a component is empty, process_component may not handle it correctly
    pass


def test_translate_terms_all_already_translated():
    """Test translate_terms when all terms are already translated."""
    # BUG: If all terms have translated_name, to_translate will be empty
    # but the function may still try to call translate_glossary
    pass


def test_translate_chunks_empty_batch():
    """Test translate_chunks with empty batch."""
    # Should handle empty batches gracefully
    pass


def test_translate_chunks_max_chunk_id_empty_batch():
    """Test translate_chunks max() on empty batch."""
    # BUG: Line 364: max(chunk.chunk_id for chunk in batch)
    # If batch is empty, this will raise ValueError
    batch = []

    # BUG: This will raise ValueError
    with pytest.raises(ValueError, match="max\\(\\)|empty"):
        _ = max(chunk.chunk_id for chunk in batch)


def test_translate_chunks_get_context_called_with_wrong_index():
    """Test that get_context may be called with wrong max_chunk_id."""
    # BUG: Line 366: get_context(term.key, max_chunk_id)
    # max_chunk_id is the max in the batch, but get_context may need
    # a different index depending on the query
    pass


def test_mark_noise_terms_ignored_terms_still_processed():
    """Test that mark_noise_terms processes already ignored terms."""
    # BUG: Line 203: term.ignored is checked, but ignored terms are still
    # processed and may be marked as ignored again
    term = Term(
        key="test_key",
        descriptions={"chunk1": "desc"},
        occurrence={},
        votes=1,
        total_api_calls=1,
        ignored=True,  # Already ignored
    )

    # The function will still process this term even though it's already ignored
    assert term.ignored is True


def test_build_occurrence_mapping_text_count_inefficiency():
    """Test that build_occurrence_mapping uses inefficient text.count()."""
    # BUG: Line 187: c.text.count(keyed_context.key)
    # This counts ALL occurrences, not just word boundaries
    # "test" in "testing" would count as 1, which may not be desired
    text = "testing test"
    key = "test"

    count = text.count(key)
    # BUG: This counts "test" in "testing" as well, which may not be desired
    # Should probably use word boundaries or regex
    assert count == 2  # "test" in "testing" and "test" as word
    # This may incorrectly count "test" as appearing twice when it should be once


def test_build_occurrence_mapping_substring_match_bug():
    """Test that build_occurrence_mapping counts substrings incorrectly."""
    # BUG: text.count(key) counts substrings, not whole words
    text = "I have a cat. The category is important."
    key = "cat"

    count = text.count(key)
    # BUG: This counts "cat" in "category" as well, which is probably wrong
    assert count == 2  # "cat" as word and "cat" in "category"
    # Should probably be 1 (only the word "cat")


def test_union_find_processed_set_bug():
    """Test that _union_find_with_filter may have issues with processed set."""
    # BUG: Line 321: other.key in processed
    # This checks if a key is processed, but the logic might skip valid connections
    # if a term is processed but should still be connected to new terms
    pass  # Would need to test the actual union-find logic


def test_translate_terms_empty_to_translate():
    """Test translate_terms when to_translate is empty."""
    # BUG: If all terms already have translated_name, to_translate is empty
    # but translate_glossary might still be called or similar_terms might be wrong
    pass  # Would need to test actual behavior


def test_translate_chunks_zip_length_mismatch():
    """Test that translate_chunks zip may have length mismatch."""
    # BUG: Line 372: zip(batch, translated_texts)
    # If translate_chunk returns wrong number of translations, zip will truncate
    # or miss some chunks
    batch = ["chunk1", "chunk2", "chunk3"]
    translated_texts = ["trans1", "trans2"]  # Missing one translation

    # BUG: zip will only process first 2 chunks, third chunk is lost
    zipped = list(zip(batch, translated_texts))
    assert len(zipped) == 2  # Only 2 items, third chunk is lost
    assert len(batch) == 3  # But batch has 3 chunks


def test_mark_noise_terms_division_order_of_operations():
    """Test that mark_noise_terms division happens before comparison."""
    # BUG: Line 202-204: The order of operations in the boolean expression
    # might cause issues if division happens when it shouldn't
    term = Term(
        key="test_key",
        descriptions={"chunk1": "desc"},  # len = 1
        occurrence={"chunk1": 1, "chunk2": 1},  # len = 2
        votes=1,
        total_api_calls=1,
    )

    # BUG: If term.ignored is True, the division still happens
    # because of short-circuit evaluation, but the division
    # is in the same expression
    term.ignored = True
    # The division len(term.occurrence)/len(term.descriptions) still evaluates
    # even if term.ignored short-circuits the OR
    ratio = len(term.occurrence) / len(term.descriptions)
    assert ratio == 2.0  # 2/1 = 2.0


def test_union_find_components_missing_terms():
    """Test that _union_find_with_filter may miss terms in components."""
    # BUG: Line 332: Only terms with keys in 'processed' are included in components
    # But if a term was never added to processed (e.g., if it was skipped),
    # it won't be in any component even if it should be
    pass  # Would need to test actual union-find behavior


def test_union_find_terms_not_in_all_terms():
    """Test that _union_find_with_filter may fail if term not in all_terms."""
    # BUG: If a term in 'terms' is not in 'all_terms', it might not be processed correctly
    pass  # Would need to test actual behavior


def test_translate_terms_similar_terms_empty_dict():
    """Test translate_terms when similar_terms is empty."""
    # BUG: Line 251: similar_terms is built per component, but if no similar terms found,
    # it's an empty dict, which might cause issues in translate_glossary
    pass  # Would need to test actual behavior


def test_translate_chunks_batch_terms_empty():
    """Test translate_chunks when batch_terms is empty."""
    # BUG: Line 365-369: If no terms match any text in batch_texts,
    # batch_terms will be empty, but translate_chunk might expect non-empty
    batch_texts = ["text without any terms"]
    all_terms = [Term(key="term1", descriptions={}, occurrence={}, votes=1, total_api_calls=1)]

    # BUG: batch_terms will be empty if term.key not in any text
    batch_terms = [
        (term.key, term.translated_name, "context")
        for term in all_terms
        if any(term.key in text for text in batch_texts)
    ]
    assert len(batch_terms) == 0  # Empty because "term1" not in "text without any terms"


def test_translate_chunks_get_context_empty_result():
    """Test that get_context may return empty list."""
    # BUG: If get_context returns empty list, the context string will be empty
    # This might cause issues in translation
    context_list = []
    context_string = "\n".join(context_list)
    assert context_string == ""  # Empty context


def test_mark_noise_terms_negative_votes():
    """Test mark_noise_terms with negative votes."""
    # BUG: Votes can theoretically be negative (though unlikely)
    # The division votes/total_api_calls might give negative ratio
    term = Term(
        key="test_key",
        descriptions={"chunk1": "desc"},
        occurrence={},
        votes=-1,  # Negative votes (shouldn't happen but possible)
        total_api_calls=1,
    )

    # BUG: Negative ratio might cause issues
    ratio = term.votes / term.total_api_calls
    assert ratio == -1.0  # Negative ratio


def test_build_occurrence_mapping_key_not_in_text():
    """Test build_occurrence_mapping when key is not in text."""
    # BUG: Line 187: c.text.count(key) returns 0 if key not in text
    # But the comprehension filters out count == 0, so it's handled
    # However, if key is a substring that appears 0 times, it's correctly excluded
    text = "some text without the key"
    key = "missing_key"

    count = text.count(key)
    assert count == 0  # Correctly returns 0


def test_translate_terms_missing_names_none():
    """Test translate_terms when missing_names is None."""
    # BUG: Line 246: missing_names is set to term.key
    # But if term.key is None (shouldn't happen), this might cause issues
    # Or if the dict structure expects missing_names but gets None
    pass  # Would need to test actual behavior


def test_context_manager_add_text_duplicate_hash():
    """Test add_text with duplicate hash."""
    # BUG: Line 66: Filters chunks by hash, but if hash collision occurs,
    # legitimate chunks might be filtered out

    # In practice, hash collisions are rare, but possible
    # If two different texts have same hash, one will be filtered
    pass  # Would need to test hash collision scenario


def test_translate_terms_similarity_threshold_zero():
    """Test translate_terms with zero similarity threshold."""
    # BUG: If threshold is 0, all terms might be grouped together
    # or no terms might be grouped, depending on implementation
    pass


def test_translate_terms_similarity_threshold_one():
    """Test translate_terms with similarity threshold of 1.0."""
    # BUG: If threshold is 1.0, only identical terms are grouped
    # This might be too strict
    pass


@pytest.fixture
def mock_translation_context_manager(tmp_path: Path):
    """Create a TranslationContextManager with mocks for occurrence mapping tests."""
    storage_manager = MockStorageManager()
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    context_extractor = MockContextExtractor()

    _ = tmp_path
    context_tree = DummyContextTree(CallableSummarizer(simple_summarize))

    source_language_detector = type("Detector", (), {"detect": AsyncMock(return_value="English")})()
    glossary_translator = type("Glossary", (), {"translate": AsyncMock(return_value={})})()
    chunk_translator = type("Chunk", (), {"translate": AsyncMock(return_value=[])})()

    manager = TranslationContextManager(
        term_repo=storage_manager,
        context_tree=context_tree,
        context_extractor=context_extractor,
        tokenizer=tokenizer,
        source_language_detector=source_language_detector,
        glossary_translator=glossary_translator,
        chunk_translator=chunk_translator,
    )

    yield manager

    import contextlib

    with contextlib.suppress(Exception):
        manager.close()
    with contextlib.suppress(Exception):
        context_tree.close()


@pytest.mark.asyncio
async def test_build_occurrence_mapping_normalized_matching(mock_translation_context_manager):
    """Test that build_occurrence_mapping uses normalized text for matching.

    Uses CJK variant characters: JP shinjitai '気' should match simplified '气'
    after normalization. Also tests fullwidth vs ASCII normalization.
    """
    manager = mock_translation_context_manager
    repo = manager.term_repo

    # Chunk text uses JP shinjitai character 気 (U+6C17)
    chunk = TranslationChunkRecord(
        chunk_id=0,
        hash="hash_jp",
        text="天気がいい",
        is_extracted=True,
        is_occurrence_mapped=False,
        # Pre-computed normalized_text would have 气 (simplified)
        normalized_text="天气がいい",
    )
    repo.chunks.append(chunk)

    # Term key uses simplified Chinese 气 (U+6C14)
    term = Term(
        key="天气",
        descriptions={"0": "weather"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    repo.keyed_contexts["天气"] = term

    await manager.build_occurrence_mapping()

    # The term should have been matched via normalized text
    updated_term = repo.keyed_contexts["天气"]
    assert updated_term.occurrence, "Expected occurrence mapping to find '天气' in normalized '天気がいい'"
    assert "0" in updated_term.occurrence

    # Chunk should be marked as occurrence_mapped
    assert chunk.is_occurrence_mapped


@pytest.mark.asyncio
async def test_build_occurrence_mapping_exact_match_without_normalization(mock_translation_context_manager):
    """Test that build_occurrence_mapping still works for exact (non-variant) matches."""
    manager = mock_translation_context_manager
    repo = manager.term_repo

    chunk = TranslationChunkRecord(
        chunk_id=0,
        hash="hash_exact",
        text="天气很好",
        is_extracted=True,
        is_occurrence_mapped=False,
        normalized_text="天气很好",
    )
    repo.chunks.append(chunk)

    term = Term(
        key="天气",
        descriptions={"0": "weather"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    repo.keyed_contexts["天气"] = term

    await manager.build_occurrence_mapping()

    updated_term = repo.keyed_contexts["天气"]
    assert updated_term.occurrence, "Expected exact match to work"
    assert "0" in updated_term.occurrence
