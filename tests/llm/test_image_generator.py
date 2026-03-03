from __future__ import annotations

from context_aware_translation.config import ImageReembeddingConfig
from context_aware_translation.llm.image_generator import BaseImageGenerator, build_text_replacements


def test_build_text_replacements_uses_line_mapping_when_line_counts_match() -> None:
    replacements = build_text_replacements("行1\n行2", "Line 1\nLine 2")
    assert replacements == [("行1", "Line 1"), ("行2", "Line 2")]


def test_build_text_replacements_pads_missing_lines_when_counts_mismatch() -> None:
    replacements = build_text_replacements("行1\n行2", "Merged line")
    assert replacements == [("行1", "Merged line"), ("行2", "")]


def test_build_text_replacements_pads_original_when_translation_has_extra_lines() -> None:
    replacements = build_text_replacements("行1", "Line 1\nLine 2")
    assert replacements == [("行1", "Line 1"), ("", "Line 2")]


def test_build_prompt_contains_json_mapping() -> None:
    generator = BaseImageGenerator(ImageReembeddingConfig(api_key="k", base_url="u", model="m"))
    prompt = generator._build_prompt([("原文A", "译文A"), ("原文B", "译文B")])

    assert "Text replacement mapping" in prompt
    assert '"original": "原文A"' in prompt
    assert '"translated": "译文A"' in prompt
    assert '"index": 1' in prompt
