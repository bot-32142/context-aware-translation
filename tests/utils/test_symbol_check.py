from __future__ import annotations

from context_aware_translation.utils.symbol_check import symbol_only


def test_symbol_only_punctuation():
    """Test that punctuation-only strings return True."""
    assert symbol_only("!@#$%") is True
    assert symbol_only(".,;:") is True
    assert symbol_only("()[]{}") is True
    assert symbol_only("+-*/=") is True


def test_symbol_only_whitespace():
    """Test that whitespace-only strings return True."""
    assert symbol_only("   ") is True
    assert symbol_only("\t\n") is True
    assert symbol_only(" \n\r\t") is True


def test_symbol_only_letters():
    """Test that strings with letters return False."""
    assert symbol_only("Hello") is False
    assert symbol_only("abc") is False
    assert symbol_only("Hello World") is False


def test_symbol_only_numbers():
    """Test that strings with numbers return False."""
    assert symbol_only("123") is False
    assert symbol_only("42") is False
    assert symbol_only("0") is False


def test_symbol_only_mixed():
    """Test that strings with letters/numbers mixed with symbols return False."""
    assert symbol_only("Hello!") is False
    assert symbol_only("123!") is False
    assert symbol_only("a@b") is False
    assert symbol_only("1+2=3") is False


def test_symbol_only_unicode_letters():
    """Test that Unicode letters return False."""
    assert symbol_only("こんにちは") is False  # Japanese
    assert symbol_only("你好") is False  # Chinese
    assert symbol_only("مرحبا") is False  # Arabic
    assert symbol_only("Привет") is False  # Cyrillic


def test_symbol_only_unicode_numbers():
    """Test that Unicode numbers return False."""
    assert symbol_only("一二三") is False  # Chinese numerals
    assert symbol_only("①②③") is False  # Circled numbers


def test_symbol_only_unicode_symbols():
    """Test that Unicode-only symbols return True."""
    assert symbol_only("※★☆") is True
    assert symbol_only("→←↑↓") is True
    assert symbol_only("【】「」") is True


def test_symbol_only_empty_string():
    """Test that empty string returns False."""
    assert symbol_only("") is False


def test_symbol_only_single_character():
    """Test single character inputs."""
    assert symbol_only("a") is False
    assert symbol_only("1") is False
    assert symbol_only("!") is True
    assert symbol_only("@") is True
    assert symbol_only(" ") is True


def test_symbol_only_emoji():
    """Test that emoji (which are typically symbols) return True."""
    # Emoji are typically in symbol categories
    assert symbol_only("😀🎉") is True
    assert symbol_only("👍") is True


def test_symbol_only_mixed_unicode():
    """Test mixed Unicode content."""
    assert symbol_only("Hello!") is False
    assert symbol_only("123→") is False  # Has number
    assert symbol_only("→←↑↓") is True  # Only arrows
