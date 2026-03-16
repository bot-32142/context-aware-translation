from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase

from typing import cast

# Disable tokenizer parallelism to avoid warnings when process is forked
# (e.g., when using uvx or multiprocessing)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Lazy-load tokenizer (cache instance to avoid reloading)
_tokenizer_cache: dict[str, object] = {}


def _get_bundled_tokenizer_dir() -> Path:
    """Get the bundled tokenizer directory, handling PyInstaller bundles."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "context_aware_translation" / "resources" / "tokenizers" / "deepseek-v3"
    return Path(__file__).resolve().parent.parent / "resources" / "tokenizers" / "deepseek-v3"


# Default tokenizer identifier
DEFAULT_TOKENIZER = "deepseek-v3"

# Mapping from API model names to tokenizer identifiers
API_TO_TOKENIZER_MAP: dict[str, str] = {
    "deepseek-reasoner": DEFAULT_TOKENIZER,
    "deepseek-chat": DEFAULT_TOKENIZER,
    "deepseek-coder": DEFAULT_TOKENIZER,
    "deepseek-ai/DeepSeek-V3.2": DEFAULT_TOKENIZER,
    # Add more mappings as needed
}


def _get_tokenizer_name(api_model_name: str) -> str:
    """
    Convert API model name to HuggingFace tokenizer name.

    Args:
        api_model_name: API model name (e.g., "deepseek-reasoner")

    Returns:
        HuggingFace tokenizer name
    """
    # If it's already a HuggingFace model name (contains '/'), use it directly
    if "/" in api_model_name:
        return api_model_name

    # Check if we have a mapping
    if api_model_name in API_TO_TOKENIZER_MAP:
        return API_TO_TOKENIZER_MAP[api_model_name]

    # Default fallback
    return DEFAULT_TOKENIZER


def get_tokenizer(model_name: str = DEFAULT_TOKENIZER) -> PreTrainedTokenizerBase:
    """
    Get or create a cached tokenizer instance.

    Args:
        model_name: The API model name or tokenizer identifier.
                    If it's an API model name (e.g., "deepseek-reasoner"), it will be
                    mapped to the appropriate tokenizer.

    Returns:
        Tokenizer instance
    """
    # Convert API model name to tokenizer name if needed
    tokenizer_name = _get_tokenizer_name(model_name)

    if tokenizer_name not in _tokenizer_cache:
        from transformers import AutoTokenizer

        try:
            if tokenizer_name == DEFAULT_TOKENIZER and _get_bundled_tokenizer_dir().is_dir():
                _tokenizer_cache[tokenizer_name] = AutoTokenizer.from_pretrained(
                    str(_get_bundled_tokenizer_dir()), local_files_only=True
                )
            else:
                _tokenizer_cache[tokenizer_name] = AutoTokenizer.from_pretrained(tokenizer_name)
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Failed to load tokenizer '{tokenizer_name}' ({e}). "
                f"Falling back to default tokenizer '{DEFAULT_TOKENIZER}'."
            )
            if DEFAULT_TOKENIZER not in _tokenizer_cache:
                _tokenizer_cache[DEFAULT_TOKENIZER] = AutoTokenizer.from_pretrained(
                    str(_get_bundled_tokenizer_dir()), local_files_only=True
                )
            _tokenizer_cache[tokenizer_name] = _tokenizer_cache[DEFAULT_TOKENIZER]

    return cast("PreTrainedTokenizerBase", _tokenizer_cache[tokenizer_name])


def chunk_text_by_tokens(
    text: str,
    max_token_size: int,
    overlap_tokens: int = 100,
    tokenizer_name: str = DEFAULT_TOKENIZER,
) -> list[str]:
    """
    Split text into chunks using transformers tokenizer with sliding window overlap.

    Args:
        text: The text to chunk
        max_token_size: Maximum number of tokens per chunk
        overlap_tokens: Number of overlapping tokens between consecutive chunks
        tokenizer_name: Name of the tokenizer model to use

    Returns:
        List of chunk text strings

    Raises:
        ValueError: If overlap_tokens >= max_token_size (would cause infinite loop)
    """
    if not text or not text.strip():
        return []

    if overlap_tokens >= max_token_size:
        raise ValueError(f"overlap_tokens ({overlap_tokens}) must be less than max_token_size ({max_token_size})")

    tokenizer = get_tokenizer(tokenizer_name)
    tokens = tokenizer.encode(text, add_special_tokens=False)

    if len(tokens) <= max_token_size:
        return [text.strip()]

    chunks: list[str] = []
    for start in range(0, len(tokens), max_token_size - overlap_tokens):
        end = min(start + max_token_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = tokenizer.decode(chunk_tokens, skip_special_tokens=True)
        chunks.append(chunk_text.strip())

    return chunks
