"""Markdown cleanup utility for Pandoc-safe text output.

This module provides functions to clean LLM output for Pandoc processing:
1. Strip LLM artifacts (padding tokens, special tokens, etc.)
2. Clean unsupported LaTeX commands from math content

Markdown escaping is intentionally NOT done here - instruct your LLM to
escape special characters when it doesn't intend markdown formatting.
"""

from __future__ import annotations

import re

# Configurable list of LLM artifacts to strip
LLM_ARTIFACT_PATTERNS: list[str] = [
    # Sequence tokens (common across many models)
    r"<pad>",
    r"</pad>",
    r"<s>",
    r"</s>",
    r"<unk>",
    r"<mask>",
    r"<eos>",
    r"<bos>",
    # BERT-style tokens
    r"\[PAD\]",
    r"\[CLS\]",
    r"\[SEP\]",
    r"\[MASK\]",
    r"\[UNK\]",
    # GPT-style tokens (if leaked)
    r"<\|endoftext\|>",
    r"<\|startoftext\|>",
    r"<\|pad\|>",
]

# LaTeX commands that are invalid in math mode or unsupported in epub
_UNSUPPORTED_LATEX_SIMPLE = [
    r"\\hfill",
    r"\\vfill",
    r"\\centering",
    r"\\raggedright",
    r"\\raggedleft",
    r"\\noindent",
    r"\\par",
    r"\\newline",
    r"\\linebreak",
    r"\\pagebreak",
    r"\\smallskip",
    r"\\medskip",
    r"\\bigskip",
]

# Commands with single argument: \command{...} or \command[...]{...}
_UNSUPPORTED_LATEX_ONE_ARG = [
    r"\\hspace\*?",
    r"\\vspace\*?",
    r"\\phantom",
    r"\\hphantom",
    r"\\vphantom",
    r"\\mbox",
    r"\\makebox",
    r"\\framebox",
]

# Commands with two arguments: \command{...}{...}
_UNSUPPORTED_LATEX_TWO_ARGS = [
    r"\\rule",
    r"\\raisebox",
]

# Pattern to match math regions: $...$ or $$...$$
_MATH_PATTERN = re.compile(r"(\$\$[\s\S]+?\$\$|\$(?!\s)[^\$]+?(?<!\s)\$(?!\$))")


def clean_latex_math(math_content: str) -> str:
    """Clean unsupported LaTeX commands from math content.

    Args:
        math_content: LaTeX math content (without $ delimiters)

    Returns:
        Cleaned math content with unsupported commands removed/fixed
    """
    result = math_content

    # Replace \hfill (N) with \tag{N} for equation numbering
    result = re.sub(r"\\hfill\s*\((\d+)\)", r"\\tag{\1}", result)

    # Remove simple unsupported commands
    for cmd in _UNSUPPORTED_LATEX_SIMPLE:
        result = re.sub(cmd + r"\b", "", result)

    # Remove commands with one argument: \command[opt]{arg} or \command{arg}
    for cmd in _UNSUPPORTED_LATEX_ONE_ARG:
        result = re.sub(cmd + r"(?:\[[^\]]*\])?\{[^}]*\}", "", result)

    # Remove commands with two arguments: \command{arg1}{arg2}
    for cmd in _UNSUPPORTED_LATEX_TWO_ARGS:
        result = re.sub(cmd + r"(?:\[[^\]]*\])?\{[^}]*\}\{[^}]*\}", "", result)

    # Clean up double spaces
    result = re.sub(r"  +", " ", result)

    return result.strip()


def strip_llm_artifacts(text: str, patterns: list[str] | None = None) -> str:
    """Remove known LLM artifacts from text.

    Args:
        text: Input text potentially containing LLM artifacts
        patterns: Optional custom list of regex patterns to strip.
                  Defaults to LLM_ARTIFACT_PATTERNS.

    Returns:
        Text with all matching artifacts removed
    """
    if patterns is None:
        patterns = LLM_ARTIFACT_PATTERNS

    result = text
    for pattern in patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    return result


def _clean_math_regions(text: str) -> str:
    """Find math regions and clean unsupported LaTeX commands in them.

    Args:
        text: Text potentially containing $...$ or $$...$$ math regions

    Returns:
        Text with math content cleaned
    """

    def clean_match(match: re.Match[str]) -> str:
        math_str = match.group(0)
        if math_str.startswith("$$"):
            # Display math: $$...$$
            inner = math_str[2:-2]
            cleaned = clean_latex_math(inner)
            return f"$${cleaned}$$"
        else:
            # Inline math: $...$
            inner = math_str[1:-1]
            cleaned = clean_latex_math(inner)
            return f"${cleaned}$"

    return _MATH_PATTERN.sub(clean_match, text)


def clean_llm_output(
    text: str,
    strip_artifacts: bool = True,
    clean_math: bool = True,
) -> str:
    """Clean LLM output for Pandoc processing.

    This function:
    1. Strips LLM artifacts (padding tokens, special tokens)
    2. Cleans unsupported LaTeX commands from math regions

    It does NOT escape markdown special characters - instruct your LLM
    to handle escaping when it doesn't intend markdown formatting.

    Args:
        text: Raw LLM output text
        strip_artifacts: If True, remove LLM tokens like <pad>, [CLS], etc.
        clean_math: If True, clean unsupported LaTeX in $...$ and $$...$$ regions

    Returns:
        Cleaned text ready for Pandoc
    """
    if not text:
        return text

    result = text

    if strip_artifacts:
        result = strip_llm_artifacts(result)

    if not result.strip():
        return ""

    if clean_math:
        result = _clean_math_regions(result)

    # Strip trailing whitespace from lines
    result = "\n".join(line.rstrip() for line in result.split("\n"))

    return result.rstrip()
