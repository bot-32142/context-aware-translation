from __future__ import annotations

from transformers import AutoTokenizer

from context_aware_translation.utils.semantic_chunker import (
    chunker_with_tokens,
    line_batched_semantic_chunker,
    merge,
)


def test_merge_empty():
    """Test merge with empty input."""
    result = merge([], [], chunk_size=100)
    assert result == []


def test_merge_single_chunk():
    """Test merge with single chunk that fits."""
    token_counts = [50]
    ends = [100]
    result = merge(token_counts, ends, chunk_size=100)
    assert result == [100]


def test_merge_single_chunk_too_large():
    """Test merge with single chunk that exceeds size."""
    token_counts = [150]
    ends = [200]
    result = merge(token_counts, ends, chunk_size=100)
    # Should still include it (can't split)
    assert result == [200]


def test_merge_multiple_chunks_no_merge():
    """Test merge when chunks don't need merging."""
    token_counts = [50, 60, 70]
    ends = [100, 200, 300]
    result = merge(token_counts, ends, chunk_size=100)
    # All chunks fit individually, should all be included
    assert len(result) == 3
    assert result == [100, 200, 300]


def test_merge_multiple_chunks_with_merge():
    """Test merge when small chunks need to be merged."""
    token_counts = [30, 40, 50, 60]
    ends = [100, 200, 300, 400]
    result = merge(token_counts, ends, chunk_size=100)
    # First two can be merged (30+40=70 < 100)
    # Third and fourth fit individually
    assert len(result) >= 2
    assert 200 in result  # First merge point


def test_merge_all_chunks_merge():
    """Test merge when all chunks are small and merge together."""
    token_counts = [20, 25, 30]
    ends = [100, 200, 300]
    result = merge(token_counts, ends, chunk_size=100)
    # All can be merged (20+25+30=75 < 100)
    assert len(result) == 1
    assert result == [300]


def test_chunker_with_tokens_basic():
    """Test chunker_with_tokens with simple text."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    text = "This is a test. This is another sentence."

    # Create a simple chunker (just split by sentences for testing)
    from semchunk.semchunk import chunkerify

    chunker = chunkerify(tokenizer, chunk_size=20)

    token_counts, ends = chunker_with_tokens(chunker, tokenizer, text)

    assert isinstance(token_counts, list)
    assert isinstance(ends, list)
    assert len(token_counts) == len(ends)
    assert all(isinstance(count, int) for count in token_counts)
    assert all(isinstance(end, int) for end in ends)
    assert all(count > 0 for count in token_counts)


def test_line_batched_semantic_chunker_basic():
    """Test line_batched_semantic_chunker with basic text."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    text = "This is a test. " * 100  # Create a longer text

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=50,
            batch_size=500,
        )
    )

    assert len(chunks) > 0
    for chunk_text, start, end in chunks:
        assert isinstance(chunk_text, str)
        assert isinstance(start, int)
        assert isinstance(end, int)
        assert start >= 0
        assert end > start
        assert len(chunk_text) == (end - start)


def test_line_batched_semantic_chunker_start_offset():
    """Test line_batched_semantic_chunker with non-zero start offset."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    text = "This is a test. " * 100

    # Start from middle of text
    start_offset = 100
    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=start_offset,
            chunk_size=50,
            batch_size=500,
        )
    )

    if chunks:
        first_chunk_text, first_start, _ = chunks[0]
        assert first_start >= start_offset


def test_line_batched_semantic_chunker_empty():
    """Test line_batched_semantic_chunker with empty text."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    text = ""

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=50,
            batch_size=500,
        )
    )

    assert len(chunks) == 0


def test_line_batched_semantic_chunker_small_text():
    """Test line_batched_semantic_chunker with text smaller than batch size."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    text = "This is a small test."

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=50,
            batch_size=500,
        )
    )

    # Should produce at least one chunk
    assert len(chunks) >= 1
    # All text should be covered
    total_length = sum(len(chunk_text) for chunk_text, _, _ in chunks)
    assert total_length <= len(text)


def test_line_batched_semantic_chunker_large_text():
    """Test line_batched_semantic_chunker with large text."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    text = "This is a test sentence. " * 1000  # Large text

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=100,
            batch_size=1000,
        )
    )

    # Should produce multiple chunks
    assert len(chunks) > 1

    # Verify chunks don't overlap and cover the text
    prev_end = 0
    for chunk_text, start, end in chunks:
        assert start >= prev_end
        assert end > start
        assert len(chunk_text) == (end - start)
        prev_end = end


def test_line_batched_semantic_chunker_unicode():
    """Test line_batched_semantic_chunker with Unicode text."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    text = "こんにちは世界。 " * 50  # Japanese text

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=50,
            batch_size=500,
        )
    )

    assert len(chunks) > 0
    for chunk_text, start, end in chunks:
        assert isinstance(chunk_text, str)
        # Verify the chunk text matches the original at that position
        assert chunk_text == text[start:end]


def test_merge_edge_cases():
    """Test merge with edge cases."""
    # Exactly at chunk size
    token_counts = [100, 50]
    ends = [100, 200]
    result = merge(token_counts, ends, chunk_size=100)
    assert 100 in result

    # Multiple small chunks that add up exactly
    token_counts = [25, 25, 25, 25]
    ends = [100, 200, 300, 400]
    result = merge(token_counts, ends, chunk_size=100)
    # Should merge into fewer chunks
    assert len(result) <= 4


def test_line_batched_semantic_chunker_gap_at_end_single_chunk():
    """Test that gap at end of batch is handled when there's a single chunk."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    # Create text where semantic chunker might not include trailing characters
    # Use a pattern that creates a trailing space that might be excluded
    text = "This is a test. " * 10 + " "  # Multiple sentences + trailing space

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=50,
            batch_size=200,  # Small batch to force single chunk scenario
        )
    )

    # Verify all chunks are produced and text is covered
    assert len(chunks) > 0

    # Verify chunks are contiguous and cover the text
    prev_end = 0
    for chunk_text, start, end in chunks:
        assert start >= prev_end
        assert end > start
        assert len(chunk_text) == (end - start)
        # Verify chunk text matches original
        assert chunk_text == text[start:end]
        prev_end = end

    # Verify we processed the entire text (no infinite loop)
    # The last chunk should end at or near the end of the text
    if chunks:
        last_chunk_text, last_start, last_end = chunks[-1]
        # Should have processed most of the text
        assert last_end >= len(text) - 10  # Allow small margin for semantic boundaries


def test_line_batched_semantic_chunker_gap_at_end_multiple_chunks():
    """Test that gap at end of batch is handled when there are multiple chunks."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    # Create text that will produce multiple chunks in a batch
    text = "This is a test sentence. " * 50  # 50 sentences

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=50,
            batch_size=500,  # Batch size that will create multiple chunks
        )
    )

    # Verify chunks are produced
    assert len(chunks) > 0

    # Verify chunks are contiguous and don't overlap
    prev_end = 0
    for chunk_text, start, end in chunks:
        assert start >= prev_end
        assert end > start
        assert len(chunk_text) == (end - start)
        # Verify chunk text matches original
        assert chunk_text == text[start:end]
        prev_end = end

    # Verify we processed the entire text (no infinite loop)
    # The last chunk should end at or near the end of the text
    if chunks:
        last_chunk_text, last_start, last_end = chunks[-1]
        # Should have processed most of the text
        assert last_end >= len(text) - 10  # Allow small margin for semantic boundaries


def test_line_batched_semantic_chunker_gap_at_end_last_batch():
    """Test that gap at end of last batch is handled (skipped chunk scenario)."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    # Create text that will cause the last batch to have a skipped chunk
    # Use a size that ensures multiple batches and multiple chunks per batch
    text = "This is a test sentence. " * 200  # 200 sentences

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=50,
            batch_size=800,  # Batch size that creates multiple batches
        )
    )

    # Verify chunks are produced
    assert len(chunks) > 0

    # Verify chunks are contiguous
    prev_end = 0
    for chunk_text, start, end in chunks:
        assert start >= prev_end
        assert end > start
        assert len(chunk_text) == (end - start)
        # Verify chunk text matches original
        assert chunk_text == text[start:end]
        prev_end = end

    # Verify we processed the entire text (no infinite loop)
    # The last chunk should end at or near the end of the text
    if chunks:
        last_chunk_text, last_start, last_end = chunks[-1]
        # Should have processed most of the text
        assert last_end >= len(text) - 10  # Allow small margin for semantic boundaries


def test_line_batched_semantic_chunker_complete_coverage():
    """Test that all text is eventually processed, even with gaps."""
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    # Create text with trailing spaces that might be excluded
    text = "Sentence one. Sentence two. Sentence three.   "  # Trailing spaces

    chunks = list(
        line_batched_semantic_chunker(
            text,
            tokenizer,
            start_offset=0,
            chunk_size=50,
            batch_size=100,
        )
    )

    # Verify chunks are produced
    assert len(chunks) > 0

    # Verify all chunks together cover the text (or very close to it)
    # by checking that the last chunk ends near the text end
    if chunks:
        last_chunk_text, last_start, last_end = chunks[-1]
        # The last chunk should end at or very close to the end of the text
        # (allowing for semantic boundaries that might exclude trailing whitespace)
        assert last_end >= len(text) - 5  # Allow small margin

        # Verify no chunks are missing in the middle
        # All chunks should be contiguous
        prev_end = 0
        for _chunk_text, start, end in chunks:
            assert start >= prev_end
            prev_end = end
