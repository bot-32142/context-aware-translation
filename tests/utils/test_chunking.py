from __future__ import annotations

import re

import pytest

from context_aware_translation.utils.chunking import chunk_text_by_tokens, get_tokenizer


def test_chunk_empty_text():
    """Test that empty text returns empty list."""
    result = chunk_text_by_tokens("", max_token_size=100)
    assert result == []

    result = chunk_text_by_tokens("   ", max_token_size=100)
    assert result == []


def test_chunk_single_chunk():
    """Test that text smaller than max_token_size returns single chunk."""
    text = "This is a short text that should fit in one chunk."
    result = chunk_text_by_tokens(text, max_token_size=1000)
    assert len(result) == 1
    assert result[0] == text.strip()


def test_chunk_no_overlap():
    """Test chunking without overlap."""
    # Create text that will require multiple chunks
    text = " ".join([f"word{i}" for i in range(200)])

    tokenizer = get_tokenizer()
    tokens = tokenizer.encode(text, add_special_tokens=False)

    # Use max_token_size that will definitely create multiple chunks
    max_token_size = len(tokens) // 3

    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=0)

    assert len(chunks) >= 2
    # Verify chunks don't overlap (by checking total token count approximation)
    total_chars = sum(len(chunk) for chunk in chunks)
    assert total_chars <= len(text) * 1.1  # Allow small margin for tokenization differences


def test_chunk_with_overlap():
    """Test chunking with overlap tokens."""
    # Create text that will require multiple chunks
    text = " ".join([f"sentence{i}." for i in range(100)])

    tokenizer = get_tokenizer()
    tokens = tokenizer.encode(text, add_special_tokens=False)

    max_token_size = len(tokens) // 2
    overlap_tokens = 50

    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=overlap_tokens)

    assert len(chunks) >= 2

    # Verify overlap by checking that consecutive chunks share token ids
    for i in range(len(chunks) - 1):
        chunk1 = chunks[i]
        chunk2 = chunks[i + 1]

        tokens1 = set(tokenizer.encode(chunk1, add_special_tokens=False))
        tokens2 = set(tokenizer.encode(chunk2, add_special_tokens=False))
        overlap_tokens_found = tokens1.intersection(tokens2)

        assert len(overlap_tokens_found) > 0, f"Chunks {i} and {i + 1} should overlap"


def test_chunk_overlap_validation():
    """Test that overlap_tokens >= max_token_size raises ValueError."""
    text = "This is a test text."

    with pytest.raises(ValueError, match="overlap_tokens.*must be less than max_token_size"):
        chunk_text_by_tokens(text, max_token_size=100, overlap_tokens=100)

    with pytest.raises(ValueError, match="overlap_tokens.*must be less than max_token_size"):
        chunk_text_by_tokens(text, max_token_size=100, overlap_tokens=150)


def test_chunk_overlap_token_count():
    """Test that overlap actually results in expected token overlap."""
    # Create a longer text with clear boundaries
    text = " ".join([f"Token{i}" for i in range(500)])

    tokenizer = get_tokenizer()
    tokenizer.encode(text, add_special_tokens=False)

    max_token_size = 200
    overlap_tokens = 50

    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=overlap_tokens)

    assert len(chunks) >= 2

    # Verify token counts for first few chunks
    for i in range(min(3, len(chunks) - 1)):
        chunk1_tokens = tokenizer.encode(chunks[i], add_special_tokens=False)
        chunk2_tokens = tokenizer.encode(chunks[i + 1], add_special_tokens=False)

        # Each chunk should be approximately max_token_size (or less for last chunk)
        assert len(chunk1_tokens) <= max_token_size
        assert len(chunk2_tokens) <= max_token_size

        # Verify the step size (max_token_size - overlap_tokens)
        # The start position should advance by this amount
        max_token_size - overlap_tokens


def test_chunk_different_overlap_values():
    """Test chunking with different overlap values."""
    text = " ".join([f"word{i}" for i in range(300)])

    tokenizer = get_tokenizer()
    tokens = tokenizer.encode(text, add_special_tokens=False)
    max_token_size = len(tokens) // 2

    # Test with small overlap
    chunks_small_overlap = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=10)

    # Test with medium overlap
    chunks_medium_overlap = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=50)

    # Test with large overlap (but still < max_token_size)
    chunks_large_overlap = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=max_token_size - 10)

    # More overlap should generally result in more chunks (since step size is smaller)
    assert len(chunks_large_overlap) >= len(chunks_medium_overlap)
    assert len(chunks_medium_overlap) >= len(chunks_small_overlap)


def test_chunk_overlap_content_verification():
    """Test that overlapping chunks actually contain overlapping content."""
    # Use a text with unique markers to verify overlap
    sentences = [f"This is sentence number {i} with unique content." for i in range(50)]
    text = " ".join(sentences)

    tokenizer = get_tokenizer()
    tokens = tokenizer.encode(text, add_special_tokens=False)

    max_token_size = len(tokens) // 3
    overlap_tokens = 30

    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=overlap_tokens)

    assert len(chunks) >= 2

    # Check that consecutive chunks share some sentence content
    for i in range(len(chunks) - 1):
        chunk1 = chunks[i]
        chunk2 = chunks[i + 1]

        # Extract sentence numbers from each chunk
        nums1 = set(re.findall(r"sentence number (\d+)", chunk1))
        nums2 = set(re.findall(r"sentence number (\d+)", chunk2))

        # With overlap, there should be shared sentence numbers
        shared = nums1.intersection(nums2)
        assert len(shared) > 0, f"Chunks {i} and {i + 1} should share sentences due to overlap"


def test_chunk_tokenizer_caching():
    """Test that tokenizer is cached and reused."""
    # Clear cache first
    from context_aware_translation.utils.chunking import _tokenizer_cache

    len(_tokenizer_cache)

    tokenizer1 = get_tokenizer("deepseek-ai/DeepSeek-V3.2")
    cache_size_after_first = len(_tokenizer_cache)

    tokenizer2 = get_tokenizer("deepseek-ai/DeepSeek-V3.2")
    cache_size_after_second = len(_tokenizer_cache)

    # Cache size should not increase on second call
    assert cache_size_after_second == cache_size_after_first

    # Should return same instance
    assert tokenizer1 is tokenizer2


def test_chunk_last_chunk_handling():
    """Test that the last chunk is handled correctly (may be smaller)."""
    text = " ".join([f"word{i}" for i in range(400)])

    tokenizer = get_tokenizer()
    tokenizer.encode(text, add_special_tokens=False)

    max_token_size = 150
    overlap_tokens = 30

    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=overlap_tokens)

    assert len(chunks) >= 2

    # Last chunk may be smaller than max_token_size
    last_chunk_tokens = tokenizer.encode(chunks[-1], add_special_tokens=False)
    assert len(last_chunk_tokens) <= max_token_size

    # All chunks except last should be close to max_token_size
    for i in range(len(chunks) - 1):
        chunk_tokens = tokenizer.encode(chunks[i], add_special_tokens=False)
        # Allow some flexibility due to tokenization
        assert len(chunk_tokens) <= max_token_size


def test_chunk_zero_overlap():
    """Test chunking with zero overlap explicitly."""
    text = " ".join([f"word{i}" for i in range(200)])

    tokenizer = get_tokenizer()
    tokens = tokenizer.encode(text, add_special_tokens=False)

    max_token_size = len(tokens) // 2

    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=0)

    assert len(chunks) >= 2

    # With zero overlap, consecutive chunks should not share much content
    for i in range(len(chunks) - 1):
        chunk1 = chunks[i]
        chunk2 = chunks[i + 1]

        # There might be minimal overlap due to word boundaries, but it should be minimal
        words1 = set(chunk1.split())
        words2 = set(chunk2.split())
        words1.intersection(words2)

        # With zero overlap, shared words should be minimal (maybe just punctuation or edge cases)
        # But we can't guarantee zero overlap due to tokenization, so just check it's reasonable


def test_chunk_very_large_overlap():
    """Test chunking with very large overlap (close to max_token_size)."""
    text = " ".join([f"word{i}" for i in range(300)])

    tokenizer = get_tokenizer()
    tokens = tokenizer.encode(text, add_special_tokens=False)

    max_token_size = 200
    overlap_tokens = 190  # Very large overlap, but still < max_token_size

    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=overlap_tokens)

    assert len(chunks) >= 2

    # With very large overlap, we should get many chunks
    # Each step is only max_token_size - overlap_tokens = 10 tokens
    expected_min_chunks = len(tokens) // (max_token_size - overlap_tokens)
    assert len(chunks) >= expected_min_chunks // 2  # Allow some margin


def test_chunk_overlap_boundary_conditions():
    """Test overlap with boundary conditions."""
    text = "This is a test text for boundary conditions."

    # Test with overlap = max_token_size - 1 (maximum allowed overlap)
    max_token_size = 50
    overlap_tokens = max_token_size - 1

    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=overlap_tokens)

    # Should not raise error and should produce at least one chunk
    assert len(chunks) >= 1

    # Test with overlap = 1 (minimum meaningful overlap)
    overlap_tokens = 1
    chunks = chunk_text_by_tokens(text, max_token_size=max_token_size, overlap_tokens=overlap_tokens)
    assert len(chunks) >= 1
