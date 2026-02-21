from __future__ import annotations

COMPRESSED_LINE_SENTINEL = "__CAT_COMPRESSED_LINE__9f7d2e7cbf5443fdb8d85f15f17ea4a8__"


def is_compressed_line(value: str) -> bool:
    """Return True when *value* is the synthetic compressed-line placeholder."""
    return value == COMPRESSED_LINE_SENTINEL


def decode_compressed_line(value: str) -> str:
    """Map compressed-line placeholders back to an empty rendered line."""
    return "" if is_compressed_line(value) else value


def decode_compressed_lines(values: list[str]) -> list[str]:
    """Decode all compressed placeholders in a list of translated lines."""
    return [decode_compressed_line(value) for value in values]
