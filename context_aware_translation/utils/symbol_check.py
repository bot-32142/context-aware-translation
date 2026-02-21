from __future__ import annotations

import unicodedata


def symbol_only(text: str) -> bool:
    """
    Check if text contains only symbols (no letters, numbers, or characters from major writing systems).

    Returns True if the text contains only punctuation, symbols, or other non-alphanumeric characters.

    Args:
        text: The text to check

    Returns:
        True if text contains only symbols, False otherwise
    """
    if not text:
        return False

    for char in text:
        category = unicodedata.category(char)
        # Check if character is a letter, number, or from major writing systems
        if category.startswith("L"):  # Letter (includes all scripts: Latin, CJK, Arabic, etc.)
            return False
        if category.startswith("N"):  # Number
            return False

    return True
