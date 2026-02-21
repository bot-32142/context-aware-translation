"""Tests for markdown_escape utility module.

This module tests the LLM output cleaning functions:
1. LLM artifact stripping (padding tokens, special tokens)
2. LaTeX math cleaning (unsupported commands)
"""

from context_aware_translation.utils.markdown_escape import (
    clean_latex_math,
    clean_llm_output,
    escape_markdown_text,
    strip_llm_artifacts,
)


class TestStripLlmArtifacts:
    """Tests for strip_llm_artifacts function."""

    def test_strip_pad_token(self):
        assert strip_llm_artifacts("<pad>text<pad>") == "text"

    def test_strip_sequence_tokens(self):
        assert strip_llm_artifacts("<s>Beginning</s>") == "Beginning"

    def test_strip_unk_token(self):
        assert strip_llm_artifacts("Text<unk>here") == "Texthere"

    def test_strip_eos_bos_tokens(self):
        assert strip_llm_artifacts("<bos>Start<eos>") == "Start"

    def test_strip_bert_style_tokens(self):
        assert strip_llm_artifacts("[CLS]Hello[SEP]World[SEP]") == "HelloWorld"

    def test_strip_pad_bert_style(self):
        assert strip_llm_artifacts("[PAD][PAD]Text[PAD]") == "Text"

    def test_strip_mask_token(self):
        assert strip_llm_artifacts("Word[MASK]Word") == "WordWord"

    def test_strip_unk_bert_style(self):
        assert strip_llm_artifacts("[UNK]Unknown") == "Unknown"

    def test_strip_gpt_endoftext(self):
        assert strip_llm_artifacts("Text<|endoftext|>") == "Text"

    def test_strip_gpt_startoftext(self):
        assert strip_llm_artifacts("<|startoftext|>Beginning") == "Beginning"

    def test_strip_gpt_pad(self):
        assert strip_llm_artifacts("<|pad|>Padded") == "Padded"

    def test_case_insensitive(self):
        assert strip_llm_artifacts("<PAD>text<Pad>") == "text"
        assert strip_llm_artifacts("[cls]text[CLS]") == "text"

    def test_multiple_artifact_types(self):
        assert strip_llm_artifacts("<s>[CLS]Hello<pad>World</s>[SEP]") == "HelloWorld"

    def test_custom_patterns(self):
        custom = [r"<custom>"]
        assert strip_llm_artifacts("<custom>text", patterns=custom) == "text"

    def test_empty_string(self):
        assert strip_llm_artifacts("") == ""

    def test_no_artifacts(self):
        assert strip_llm_artifacts("clean text") == "clean text"


class TestCleanLatexMath:
    """Tests for clean_latex_math function."""

    def test_hfill_to_tag(self):
        """Replace \\hfill (N) with \\tag{N}."""
        result = clean_latex_math(r"x^2 \hfill (1)")
        assert r"\tag{1}" in result
        assert r"\hfill" not in result

    def test_remove_hfill(self):
        result = clean_latex_math(r"\hfill x^2")
        assert r"\hfill" not in result
        assert "x^2" in result

    def test_remove_vfill(self):
        result = clean_latex_math(r"\vfill x^2")
        assert r"\vfill" not in result

    def test_remove_centering(self):
        result = clean_latex_math(r"\centering x^2")
        assert r"\centering" not in result

    def test_remove_noindent(self):
        result = clean_latex_math(r"\noindent x^2")
        assert r"\noindent" not in result

    def test_remove_spacing_commands(self):
        result = clean_latex_math(r"\smallskip x \medskip y \bigskip z")
        assert r"\smallskip" not in result
        assert r"\medskip" not in result
        assert r"\bigskip" not in result

    def test_remove_hspace(self):
        result = clean_latex_math(r"x \hspace{1cm} y")
        assert r"\hspace" not in result

    def test_remove_vspace(self):
        result = clean_latex_math(r"x \vspace{1cm} y")
        assert r"\vspace" not in result

    def test_remove_phantom(self):
        result = clean_latex_math(r"x \phantom{abc} y")
        assert r"\phantom" not in result

    def test_remove_mbox(self):
        result = clean_latex_math(r"x \mbox{text} y")
        assert r"\mbox" not in result

    def test_remove_rule(self):
        result = clean_latex_math(r"x \rule{1cm}{2cm} y")
        assert r"\rule" not in result

    def test_preserve_valid_commands(self):
        """Valid LaTeX commands should be preserved."""
        result = clean_latex_math(r"\frac{1}{2} + \sqrt{x}")
        assert r"\frac{1}{2}" in result
        assert r"\sqrt{x}" in result

    def test_clean_double_spaces(self):
        result = clean_latex_math("x  +  y")
        assert "  " not in result

    def test_strip_whitespace(self):
        result = clean_latex_math("  x^2  ")
        assert result == "x^2"


class TestCleanLlmOutput:
    """Tests for clean_llm_output function."""

    def test_strips_artifacts(self):
        result = clean_llm_output("<pad>Hello World<pad>")
        assert result == "Hello World"
        assert "pad" not in result

    def test_cleans_math(self):
        result = clean_llm_output(r"Formula: $x \hfill y$")
        assert r"\hfill" not in result
        assert "$x" in result

    def test_cleans_display_math(self):
        result = clean_llm_output(r"$$\centering x^2$$")
        assert r"\centering" not in result
        assert "$$" in result

    def test_preserves_valid_math(self):
        result = clean_llm_output(r"The equation $E=mc^2$ is famous")
        assert r"$E=mc^2$" in result

    def test_empty_string(self):
        assert clean_llm_output("") == ""

    def test_whitespace_only(self):
        assert clean_llm_output("   ") == ""

    def test_only_artifacts(self):
        assert clean_llm_output("<pad><s></s>") == ""

    def test_strips_trailing_whitespace(self):
        result = clean_llm_output("line1   \nline2   ")
        assert "   " not in result

    def test_disable_artifact_stripping(self):
        result = clean_llm_output("<pad>text", strip_artifacts=False)
        assert "<pad>" in result

    def test_disable_math_cleaning(self):
        result = clean_llm_output(r"$\hfill x$", clean_math=False)
        assert r"\hfill" in result

    def test_combined_artifacts_and_math(self):
        result = clean_llm_output(r"<pad>The formula $x \hfill (1)$ is<eos>")
        assert "pad" not in result
        assert "eos" not in result
        assert r"\tag{1}" in result

    def test_preserves_markdown_formatting(self):
        """Markdown formatting passes through unchanged."""
        result = clean_llm_output("This is **bold** and *italic*")
        assert "**bold**" in result
        assert "*italic*" in result

    def test_preserves_links(self):
        result = clean_llm_output("See [docs](https://example.com)")
        assert "[docs](https://example.com)" in result

    def test_preserves_code(self):
        result = clean_llm_output("Use `code` here")
        assert "`code`" in result

    def test_preserves_special_chars(self):
        """Special characters pass through - LLM should escape if needed."""
        result = clean_llm_output("Use [brackets] and *asterisks*")
        assert "[brackets]" in result
        assert "*asterisks*" in result

    def test_preserves_unicode(self):
        result = clean_llm_output("中文 日本語 한국어")
        assert "中文" in result
        assert "日本語" in result

    def test_preserves_emoji(self):
        result = clean_llm_output("Hello 👋 World 🌍")
        assert "👋" in result
        assert "🌍" in result


class TestEscapeMarkdownTextBackwardsCompat:
    """Tests for backwards compatibility of escape_markdown_text."""

    def test_strips_artifacts(self):
        result = escape_markdown_text("<pad>Hello<pad>")
        assert result == "Hello"

    def test_cleans_math(self):
        result = escape_markdown_text(r"$\hfill x$")
        assert r"\hfill" not in result

    def test_preserve_pandoc_formats_ignored(self):
        """The preserve_pandoc_formats param is ignored but accepted."""
        result1 = escape_markdown_text("**bold**", preserve_pandoc_formats=True)
        result2 = escape_markdown_text("**bold**", preserve_pandoc_formats=False)
        # Both should pass through unchanged now
        assert "**bold**" in result1
        assert "**bold**" in result2

    def test_strip_artifacts_flag(self):
        result = escape_markdown_text("<pad>text", strip_llm_artifacts_flag=False)
        assert "<pad>" in result

    def test_empty_string(self):
        assert escape_markdown_text("") == ""

    def test_whitespace_only(self):
        assert escape_markdown_text("   ") == ""
