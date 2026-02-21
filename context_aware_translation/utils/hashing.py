from __future__ import annotations

import hashlib


def compute_chunk_hash(text: str, document_id: int | None = None) -> str:
    """
    Compute SHA-256 hash of chunk text for deduplication.

    Args:
        text: The chunk text to hash
        document_id: Optional document scope for deduplication.
            When provided, identical text across different documents
            produces different hashes while preserving in-document dedup.

    Returns:
        SHA-256 hash as hexadecimal string
    """
    payload = text if document_id is None else f"{document_id}:{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
