from __future__ import annotations

from context_aware_translation.utils.hard_wrap import unwrap_hard_wrapped_text


def test_unwrap_hard_wrapped_text_merges_prose_paragraphs() -> None:
    text = (
        "After a long conversation with the harbor master,\n"
        "Captain Leclere left Naples in a state of agitation;\n"
        "twenty-four hours later the fever took him."
    )

    assert unwrap_hard_wrapped_text(text) == (
        "After a long conversation with the harbor master, "
        "Captain Leclere left Naples in a state of agitation; "
        "twenty-four hours later the fever took him."
    )


def test_unwrap_hard_wrapped_text_preserves_list_blocks() -> None:
    text = "- first item\n- second item\n- third item"

    assert unwrap_hard_wrapped_text(text) == text


def test_unwrap_hard_wrapped_text_preserves_short_poetry_like_lines() -> None:
    text = "Roses are red\nViolets are blue\nSoft winds are singing"

    assert unwrap_hard_wrapped_text(text) == text


def test_unwrap_hard_wrapped_text_dehyphenates_words() -> None:
    text = "An impro-\nvised example with a dehy-\nphenated word."

    assert unwrap_hard_wrapped_text(text) == "An improvised example with a dehyphenated word."
