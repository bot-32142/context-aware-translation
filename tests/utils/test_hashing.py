from __future__ import annotations

import hashlib

from context_aware_translation.utils.hashing import compute_chunk_hash


def test_compute_chunk_hash_basic():
    """Test basic hash computation."""
    text = "Hello, world!"
    result = compute_chunk_hash(text)

    # Should return SHA-256 hash
    assert isinstance(result, str)
    assert len(result) == 64  # SHA-256 produces 64 hex characters

    # Verify it's the correct hash
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result == expected


def test_compute_chunk_hash_empty_string():
    """Test hash computation with empty string."""
    text = ""
    result = compute_chunk_hash(text)

    assert isinstance(result, str)
    assert len(result) == 64

    # Empty string should produce a specific hash
    expected = hashlib.sha256(b"").hexdigest()
    assert result == expected


def test_compute_chunk_hash_unicode():
    """Test hash computation with Unicode characters."""
    text = "こんにちは世界！"
    result = compute_chunk_hash(text)

    assert isinstance(result, str)
    assert len(result) == 64

    # Verify UTF-8 encoding is used
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result == expected


def test_compute_chunk_hash_deterministic():
    """Test that same input produces same hash."""
    text = "Test text for determinism"
    result1 = compute_chunk_hash(text)
    result2 = compute_chunk_hash(text)

    assert result1 == result2


def test_compute_chunk_hash_different_inputs():
    """Test that different inputs produce different hashes."""
    text1 = "First text"
    text2 = "Second text"

    result1 = compute_chunk_hash(text1)
    result2 = compute_chunk_hash(text2)

    assert result1 != result2


def test_compute_chunk_hash_whitespace_sensitive():
    """Test that whitespace differences produce different hashes."""
    text1 = "Hello world"
    text2 = "Hello  world"  # Extra space
    text3 = "Hello\nworld"  # Newline

    result1 = compute_chunk_hash(text1)
    result2 = compute_chunk_hash(text2)
    result3 = compute_chunk_hash(text3)

    assert result1 != result2
    assert result1 != result3
    assert result2 != result3


def test_compute_chunk_hash_large_text():
    """Test hash computation with large text."""
    text = "A" * 10000
    result = compute_chunk_hash(text)

    assert isinstance(result, str)
    assert len(result) == 64

    # Verify it's correct
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result == expected


def test_compute_chunk_hash_special_characters():
    """Test hash computation with special characters."""
    text = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
    result = compute_chunk_hash(text)

    assert isinstance(result, str)
    assert len(result) == 64

    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result == expected


def test_compute_chunk_hash_document_scoped():
    """Document-scoped hash should differ for same text across documents."""
    text = "Same chunk text"
    hash_doc1 = compute_chunk_hash(text, document_id=1)
    hash_doc2 = compute_chunk_hash(text, document_id=2)
    hash_nonscoped = compute_chunk_hash(text)

    assert hash_doc1 != hash_doc2
    assert hash_doc1 != hash_nonscoped
    assert hash_doc2 != hash_nonscoped
