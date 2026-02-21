from __future__ import annotations

from collections import deque
from collections.abc import Generator
from typing import Any

from semchunk.semchunk import chunkerify
from transformers import PreTrainedTokenizer


def merge(token_counts: list[int], ends: list[int], chunk_size: int) -> list[int]:
    """Merge small chunks to reach target chunk size."""
    new_ends = []
    q: deque[tuple[int, int]] = deque()
    q.extend(zip(token_counts, ends, strict=True))
    if not q:
        return []

    cur: tuple[int, int] | None = (q[0][0], q.popleft()[1])
    while len(q) > 0 and cur is not None:
        if cur[0] + q[0][0] < chunk_size:
            cur = (cur[0] + q[0][0], q.popleft()[1])
        else:
            new_ends.append(cur[1])
            cur = (q[0][0], q.popleft()[1]) if len(q) > 0 else None
    if cur is not None:
        new_ends.append(cur[1])
    return new_ends


def chunker_with_tokens(chunker: Any, tokenizer: PreTrainedTokenizer, text: str) -> tuple[list[int], list[int]]:
    """
    Split text into chunks and return token counts and end offsets.

    Returns:
        Tuple of (token_counts, end_offsets)
    """
    chunks, offsets = chunker(text, offsets=True)
    token_counts = [len(tokenizer.encode(chunk)) for chunk in chunks]
    ends = [end for start, end in offsets]
    return token_counts, ends


def line_batched_semantic_chunker(
    file_content_str: str,
    tokenizer: PreTrainedTokenizer,
    start_offset: int = 0,
    chunk_size: int = 3000,
    batch_size: int = 35000,
) -> Generator[tuple[str, int, int], None, None]:
    """
    Semantically chunk text with batching for large files.

    Args:
        file_content_str: Full file content as string
        tokenizer: Tokenizer instance
        start_offset: Byte offset to start from (for resuming)
        chunk_size: Target chunk size in tokens
        batch_size: Batch size for processing (in characters)

    Yields:
        Tuples of (chunk_text, start_offset, end_offset)
    """
    chunker = chunkerify(tokenizer, chunk_size=int(chunk_size / 2))
    last_processed = start_offset

    while last_processed < len(file_content_str):
        batch_content = file_content_str[last_processed : min(len(file_content_str), last_processed + batch_size)]
        token_counts, ends = chunker_with_tokens(chunker, tokenizer, batch_content)

        # Merge chunks
        ends = merge(token_counts, ends, chunk_size)

        # Process this batch of chunks
        last_processed_in_batch = 0
        absolute_batch_start_offset = last_processed

        for idx, end_in_batch in enumerate(ends):
            if len(ends) > 1 and idx == len(ends) - 1:
                # Skip last chunk (will be processed in next batch)
                break
            # semantic chunker may not include trailing whitespace/characters in the last chunk, so we need to advance to the end of the batch
            if ends[-1] == end_in_batch and ends[-1] < len(batch_content):
                end_in_batch = len(batch_content)
            yield (
                batch_content[last_processed_in_batch:end_in_batch],
                absolute_batch_start_offset + last_processed_in_batch,
                absolute_batch_start_offset + end_in_batch,
            )
            last_processed_in_batch = end_in_batch

        last_processed += last_processed_in_batch
