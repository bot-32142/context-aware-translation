from __future__ import annotations

import io

import pytest
from PIL import Image

from context_aware_translation.documents.content.ocr_content import (
    MergedOCRContent,
    parse_ocr_json,
)
from context_aware_translation.documents.content.ocr_items import (
    BlankItem,
    ChapterItem,
    CoverItem,
    ImageItem,
    ListItem,
    ParagraphItem,
    TableItem,
    TocItem,
)
from context_aware_translation.utils.compression_marker import COMPRESSED_LINE_SENTINEL

# ============================================================================
# parse_ocr_json Tests
# ============================================================================


class TestParseOcrJson:
    def test_parse_cover_page_with_image(self):
        data = {"page_type": "cover"}
        image_bytes = b"fake_image_data"
        page_type, items = parse_ocr_json(data, image_bytes)

        assert page_type == "cover"
        assert len(items) == 1
        assert isinstance(items[0], CoverItem)
        assert items[0].image_bytes == image_bytes

    def test_parse_cover_page_without_image(self):
        data = {"page_type": "cover"}
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "cover"
        assert len(items) == 0

    def test_parse_toc_page_with_image(self):
        data = {"page_type": "toc"}
        image_bytes = b"fake_image_data"
        page_type, items = parse_ocr_json(data, image_bytes)

        assert page_type == "toc"
        assert len(items) == 1
        assert isinstance(items[0], TocItem)

    def test_parse_toc_page_without_image(self):
        data = {"page_type": "toc"}
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "toc"
        assert len(items) == 0

    def test_parse_blank_page_with_image(self):
        data = {"page_type": "blank"}
        image_bytes = b"fake_image_data"
        page_type, items = parse_ocr_json(data, image_bytes)

        assert page_type == "blank"
        assert len(items) == 1
        assert isinstance(items[0], BlankItem)

    def test_parse_blank_page_without_image(self):
        data = {"page_type": "blank"}
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "blank"
        assert len(items) == 0

    def test_parse_content_page_with_paragraphs(self):
        data = {
            "page_type": "content",
            "content": [
                {"type": "paragraph", "text": "First paragraph"},
                {"type": "paragraph", "text": "Second paragraph"},
            ],
        }
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "content"
        assert len(items) == 2
        assert isinstance(items[0], ParagraphItem)
        assert items[0].text == "First paragraph"
        assert isinstance(items[1], ParagraphItem)
        assert items[1].text == "Second paragraph"

    def test_parse_content_page_with_chapter(self):
        data = {
            "page_type": "content",
            "content": [
                {"type": "chapter", "text": "Chapter 1"},
                {"type": "paragraph", "text": "Introduction text"},
            ],
        }
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "content"
        assert len(items) == 2
        assert isinstance(items[0], ChapterItem)
        assert items[0].text == "Chapter 1"
        assert isinstance(items[1], ParagraphItem)

    def test_parse_content_page_with_list(self):
        data = {
            "page_type": "content",
            "content": [
                {"type": "list", "items": ["Item 1", "Item 2", "Item 3"]},
            ],
        }
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "content"
        assert len(items) == 1
        assert isinstance(items[0], ListItem)
        assert items[0].items == ["Item 1", "Item 2", "Item 3"]

    def test_parse_content_page_with_table(self):
        data = {
            "page_type": "content",
            "content": [
                {"type": "table", "text": "| A | B |\n| 1 | 2 |", "caption": "Table 1"},
            ],
        }
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "content"
        assert len(items) == 1
        assert isinstance(items[0], TableItem)
        assert items[0].text == "| A | B |\n| 1 | 2 |"
        assert items[0].caption == "Table 1"

    def test_parse_content_page_with_image(self):
        data = {
            "page_type": "content",
            "content": [
                {
                    "type": "image",
                    "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                    "caption": "Figure 1",
                },
            ],
        }
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "content"
        assert len(items) == 1
        assert isinstance(items[0], ImageItem)
        assert items[0].caption == "Figure 1"

    def test_parse_content_page_empty_content(self):
        data = {"page_type": "content", "content": []}
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "content"
        assert len(items) == 0

    def test_parse_unknown_page_type_with_content(self):
        data = {
            "page_type": "unknown_type",
            "content": [
                {"type": "paragraph", "text": "Some text"},
            ],
        }
        page_type, items = parse_ocr_json(data, None)

        # Unknown types default to content parsing
        assert page_type == "unknown_type"
        assert len(items) == 1
        assert isinstance(items[0], ParagraphItem)

    def test_parse_missing_page_type_raises(self):
        data = {"content": []}
        with pytest.raises(ValueError, match="Missing required field: 'page_type'"):
            parse_ocr_json(data, None)

    def test_parse_invalid_page_type_raises(self):
        data = {"page_type": 123}  # Not a string
        with pytest.raises(ValueError, match="Invalid page_type: expected str, got int"):
            parse_ocr_json(data, None)

    def test_parse_content_with_invalid_content_field_raises(self):
        data = {"page_type": "content", "content": "not a list"}
        with pytest.raises(ValueError, match="Invalid content: expected list, got str"):
            parse_ocr_json(data, None)

    def test_parse_unknown_type_with_invalid_content_raises(self):
        data = {"page_type": "unknown", "content": 123}
        with pytest.raises(ValueError, match="Invalid content: expected list, got int"):
            parse_ocr_json(data, None)

    def test_parse_content_page_default_content_empty_list(self):
        # When content field is missing, it defaults to []
        data = {"page_type": "content"}
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "content"
        assert len(items) == 0

    def test_parse_complex_content_page(self):
        data = {
            "page_type": "content",
            "content": [
                {"type": "chapter", "text": "Chapter 1"},
                {"type": "paragraph", "text": "Introduction"},
                {"type": "list", "items": ["Point 1", "Point 2"]},
                {"type": "table", "text": "| A | B |"},
                {
                    "type": "image",
                    "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
                },
            ],
        }
        page_type, items = parse_ocr_json(data, None)

        assert page_type == "content"
        assert len(items) == 5
        assert isinstance(items[0], ChapterItem)
        assert isinstance(items[1], ParagraphItem)
        assert isinstance(items[2], ListItem)
        assert isinstance(items[3], TableItem)
        assert isinstance(items[4], ImageItem)

    def test_page_level_continues_from_previous_normalized_to_first_item(self):
        """Page-level continues_from_previous should propagate to the first content item."""
        data = {
            "page_type": "content",
            "continues_from_previous": True,
            "content": [
                {"type": "paragraph", "text": "Continued text"},
                {"type": "paragraph", "text": "Next paragraph"},
            ],
        }
        _, items = parse_ocr_json(data, None)

        assert len(items) == 2
        assert items[0].continues_from_previous is True
        assert items[1].continues_from_previous is False

    def test_page_level_continues_to_next_normalized_to_last_item(self):
        """Page-level continues_to_next should propagate to the last content item."""
        data = {
            "page_type": "content",
            "continues_to_next": True,
            "content": [
                {"type": "paragraph", "text": "First paragraph"},
                {"type": "paragraph", "text": "Text that continues..."},
            ],
        }
        _, items = parse_ocr_json(data, None)

        assert len(items) == 2
        assert items[0].continues_to_next is False
        assert items[1].continues_to_next is True

    def test_page_level_both_continuation_flags(self):
        """Both page-level flags should propagate to first and last items respectively."""
        data = {
            "page_type": "content",
            "continues_from_previous": True,
            "continues_to_next": True,
            "content": [
                {"type": "paragraph", "text": "Continued from prev"},
                {"type": "section", "text": "Section"},
                {"type": "paragraph", "text": "Continues to next"},
            ],
        }
        _, items = parse_ocr_json(data, None)

        assert len(items) == 3
        assert items[0].continues_from_previous is True
        # SectionItem doesn't have continues_to_next, so the last paragraph should NOT
        # get it since it's not the last item — the section is a middle item.
        # Actually items[-1] is the last paragraph which does have the attr.
        assert items[2].continues_to_next is True

    def test_page_level_single_item_gets_both_flags(self):
        """A single content item should receive both page-level flags."""
        data = {
            "page_type": "content",
            "continues_from_previous": True,
            "continues_to_next": True,
            "content": [
                {"type": "paragraph", "text": "Middle of a long passage"},
            ],
        }
        _, items = parse_ocr_json(data, None)

        assert len(items) == 1
        assert items[0].continues_from_previous is True
        assert items[0].continues_to_next is True

    def test_page_level_flags_ignored_for_empty_content(self):
        """Page-level flags on empty content should not cause errors."""
        data = {
            "page_type": "content",
            "continues_from_previous": True,
            "content": [],
        }
        _, items = parse_ocr_json(data, None)
        assert len(items) == 0

    def test_page_level_flags_skipped_for_items_without_attr(self):
        """Page-level flags should be skipped if the target item lacks the attribute."""
        data = {
            "page_type": "content",
            "continues_from_previous": True,
            "content": [
                {"type": "section", "text": "A Section Heading"},
            ],
        }
        _, items = parse_ocr_json(data, None)
        assert len(items) == 1
        assert not hasattr(items[0], "continues_from_previous")


# ============================================================================
# MergedOCRContent Tests
# ============================================================================


class TestMergedOCRContent:
    def test_creation_empty(self):
        content = MergedOCRContent(elements=[])
        assert content.elements == []

    def test_creation_with_elements(self):
        elem1 = ParagraphItem(text="Para 1")
        elem2 = ParagraphItem(text="Para 2")
        content = MergedOCRContent(elements=[elem1, elem2])
        assert len(content.elements) == 2
        assert content.elements[0] is elem1
        assert content.elements[1] is elem2

    def test_get_texts_empty(self):
        content = MergedOCRContent(elements=[])
        assert content.get_texts() == []

    def test_get_texts_single_paragraph(self):
        content = MergedOCRContent(elements=[ParagraphItem(text="Hello world")])
        assert content.get_texts() == ["Hello world"]

    def test_get_texts_multiple_paragraphs(self):
        content = MergedOCRContent(
            elements=[
                ParagraphItem(text="First paragraph"),
                ParagraphItem(text="Second paragraph"),
            ]
        )
        assert content.get_texts() == ["First paragraph", "Second paragraph"]

    def test_get_texts_chapter_multiline(self):
        content = MergedOCRContent(elements=[ChapterItem(text="Chapter 1\nThe Beginning")])
        assert content.get_texts() == ["Chapter 1", "The Beginning"]

    def test_get_texts_list_item(self):
        content = MergedOCRContent(elements=[ListItem(items=["Item 1", "Item 2", "Item 3"])])
        assert content.get_texts() == ["Item 1", "Item 2", "Item 3"]

    def test_get_texts_mixed_elements(self):
        content = MergedOCRContent(
            elements=[
                ChapterItem(text="Chapter 1"),
                ParagraphItem(text="Introduction"),
                ListItem(items=["Point 1", "Point 2"]),
            ]
        )
        assert content.get_texts() == ["Chapter 1", "Introduction", "Point 1", "Point 2"]

    def test_get_texts_with_blank_items(self):
        content = MergedOCRContent(
            elements=[
                ParagraphItem(text="Before blank"),
                BlankItem(),
                ParagraphItem(text="After blank"),
            ]
        )
        # BlankItem returns empty list
        assert content.get_texts() == ["Before blank", "After blank"]

    def test_set_texts_single_paragraph(self):
        content = MergedOCRContent(elements=[ParagraphItem(text="Hello")])
        translations = ["你好"]
        pos = content.set_texts(translations)

        assert pos == 1
        assert content.elements[0].translated_lines == ["你好"]

    def test_set_texts_multiple_paragraphs(self):
        content = MergedOCRContent(
            elements=[
                ParagraphItem(text="First"),
                ParagraphItem(text="Second"),
            ]
        )
        translations = ["第一", "第二"]
        pos = content.set_texts(translations)

        assert pos == 2
        assert content.elements[0].translated_lines == ["第一"]
        assert content.elements[1].translated_lines == ["第二"]

    def test_set_texts_chapter_multiline(self):
        content = MergedOCRContent(elements=[ChapterItem(text="Chapter 1\nThe Beginning")])
        translations = ["第一章", "开始"]
        pos = content.set_texts(translations)

        assert pos == 2
        assert content.elements[0].translated_lines == ["第一章", "开始"]

    def test_set_texts_list_item(self):
        content = MergedOCRContent(elements=[ListItem(items=["Item 1", "Item 2"])])
        translations = ["项目1", "项目2"]
        pos = content.set_texts(translations)

        assert pos == 2
        assert content.elements[0].translated_lines == ["项目1", "项目2"]

    def test_set_texts_mixed_elements(self):
        content = MergedOCRContent(
            elements=[
                ChapterItem(text="Chapter 1"),
                ParagraphItem(text="Intro"),
                ListItem(items=["A", "B"]),
            ]
        )
        translations = ["第一章", "介绍", "甲", "乙"]
        pos = content.set_texts(translations)

        assert pos == 4
        assert content.elements[0].translated_lines == ["第一章"]
        assert content.elements[1].translated_lines == ["介绍"]
        assert content.elements[2].translated_lines == ["甲", "乙"]

    def test_set_texts_wrong_count_raises(self):
        content = MergedOCRContent(
            elements=[
                ParagraphItem(text="First"),
                ParagraphItem(text="Second"),
            ]
        )
        translations = ["Only one"]  # Need 2

        with pytest.raises(ValueError, match="Expected 2 translations, got 1"):
            content.set_texts(translations)

    def test_set_texts_too_many_translations_raises(self):
        content = MergedOCRContent(elements=[ParagraphItem(text="One")])
        translations = ["一", "二"]  # Need only 1

        with pytest.raises(ValueError, match="Expected 1 translations, got 2"):
            content.set_texts(translations)

    def test_set_texts_empty_content(self):
        content = MergedOCRContent(elements=[])
        translations = []
        pos = content.set_texts(translations)
        assert pos == 0

    def test_to_markdown_empty(self, tmp_path):
        content = MergedOCRContent(elements=[])
        result = content.to_markdown(tmp_path)
        assert result == ""

    def test_to_markdown_single_paragraph(self, tmp_path):
        content = MergedOCRContent(elements=[ParagraphItem(text="Hello")])
        content.set_texts(["你好"])
        result = content.to_markdown(tmp_path)
        assert result == "你好"

    def test_to_markdown_skips_compressed_paragraph_placeholder(self, tmp_path):
        content = MergedOCRContent(
            elements=[
                ParagraphItem(text="First"),
                ParagraphItem(text="Second"),
            ]
        )
        content.set_texts([COMPRESSED_LINE_SENTINEL, "第二"])
        result = content.to_markdown(tmp_path)
        assert result == "第二"

    def test_to_markdown_multiple_paragraphs(self, tmp_path):
        content = MergedOCRContent(
            elements=[
                ParagraphItem(text="First"),
                ParagraphItem(text="Second"),
            ]
        )
        content.set_texts(["第一", "第二"])
        result = content.to_markdown(tmp_path)
        assert result == "第一\n\n第二"

    def test_to_markdown_chapter(self, tmp_path):
        content = MergedOCRContent(
            elements=[
                ChapterItem(text="Chapter 1"),
                ParagraphItem(text="Text"),
            ]
        )
        content.set_texts(["第一章", "文本"])
        result = content.to_markdown(tmp_path, insert_new_page_before_chapter=False)
        assert result == "# 第一章\n\n文本"

    def test_to_markdown_chapter_with_newpage(self, tmp_path):
        content = MergedOCRContent(
            elements=[
                ChapterItem(text="Chapter 1"),
                ParagraphItem(text="Text"),
            ]
        )
        content.set_texts(["第一章", "文本"])
        result = content.to_markdown(tmp_path, insert_new_page_before_chapter=True)
        assert result == "\\newpage\n# 第一章\n\n文本"

    def test_to_markdown_list(self, tmp_path):
        content = MergedOCRContent(elements=[ListItem(items=["Item 1", "Item 2"])])
        content.set_texts(["项目1", "项目2"])
        result = content.to_markdown(tmp_path)
        assert result == "- 项目1\n- 项目2"

    def test_to_markdown_table(self, tmp_path):
        content = MergedOCRContent(elements=[TableItem(text="| A | B |", caption="Table 1")])
        content.set_texts(["| 甲 | 乙 |", "表格1"])
        result = content.to_markdown(tmp_path)
        assert "| 甲 | 乙 |" in result
        assert "Table: 表格1" in result

    def test_to_markdown_with_cover(self, tmp_path):
        # Create test image
        img = Image.new("RGB", (100, 100), color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        content = MergedOCRContent(
            elements=[
                CoverItem(image_bytes=buffer.getvalue()),
                ParagraphItem(text="Text"),
            ]
        )
        content.set_texts(["文本"])
        result = content.to_markdown(tmp_path)

        # CoverItem outputs YAML frontmatter for pandoc epub cover
        assert "cover-image:" in result
        assert "文本" in result

    def test_to_markdown_with_blank_items(self, tmp_path):
        content = MergedOCRContent(
            elements=[
                ParagraphItem(text="Before"),
                BlankItem(),
                ParagraphItem(text="After"),
            ]
        )
        content.set_texts(["之前", "之后"])
        result = content.to_markdown(tmp_path)

        # BlankItem renders as empty string but still creates separator
        assert "之前" in result
        assert "之后" in result

    def test_from_raw_ocr_single_page(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {"type": "paragraph", "text": "First paragraph"},
                        ],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        assert len(content.elements) == 1
        assert isinstance(content.elements[0], ParagraphItem)
        assert content.elements[0].text == "First paragraph"

    def test_from_raw_ocr_multiple_pages(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [{"type": "paragraph", "text": "Page 1"}],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [{"type": "paragraph", "text": "Page 2"}],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        assert len(content.elements) == 2
        assert content.elements[0].text == "Page 1"
        assert content.elements[1].text == "Page 2"

    def test_from_raw_ocr_with_cover(self):
        img = Image.new("RGB", (100, 100), color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        pages = [
            ([{"page_type": "cover"}], image_bytes),
            (
                [
                    {
                        "page_type": "content",
                        "content": [{"type": "paragraph", "text": "Content"}],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        assert len(content.elements) == 2
        assert isinstance(content.elements[0], CoverItem)
        assert isinstance(content.elements[1], ParagraphItem)

    def test_from_raw_ocr_with_blank_pages(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [{"type": "paragraph", "text": "Page 1"}],
                    }
                ],
                None,
            ),
            ([{"page_type": "blank"}], b"blank_image"),
            (
                [
                    {
                        "page_type": "content",
                        "content": [{"type": "paragraph", "text": "Page 3"}],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        assert len(content.elements) == 3
        assert isinstance(content.elements[0], ParagraphItem)
        assert isinstance(content.elements[1], BlankItem)
        assert isinstance(content.elements[2], ParagraphItem)

    def test_from_raw_ocr_merge_paragraph_continuation(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "First part",
                                "continues_to_next": True,
                            }
                        ],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "Second part",
                                "continues_from_previous": True,
                            }
                        ],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        # Should merge into single paragraph
        assert len(content.elements) == 1
        assert isinstance(content.elements[0], ParagraphItem)
        assert content.elements[0].text == "First partSecond part"

    def test_from_raw_ocr_merge_list_continuation(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "list",
                                "items": ["Item 1"],
                                "continues_to_next": True,
                            }
                        ],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "list",
                                "items": ["Item 2"],
                                "continues_from_previous": True,
                            }
                        ],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        # Should merge into single list
        assert len(content.elements) == 1
        assert isinstance(content.elements[0], ListItem)
        assert content.elements[0].items == ["Item 1", "Item 2"]

    def test_from_raw_ocr_merge_table_continuation(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "table",
                                "text": "| A | B |",
                                "continues_to_next": True,
                            }
                        ],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "table",
                                "text": "| 1 | 2 |",
                                "caption": "Table 1",
                                "continues_from_previous": True,
                            }
                        ],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        # Should merge into single table
        assert len(content.elements) == 1
        assert isinstance(content.elements[0], TableItem)
        assert content.elements[0].text == "| A | B |\n| 1 | 2 |"
        assert content.elements[0].caption == "Table 1"

    def test_from_raw_ocr_merge_with_page_level_continuation_flags(self):
        """Page-level continuation flags should be normalized and enable merging."""
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "continues_to_next": True,
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "First part",
                            }
                        ],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "continues_from_previous": True,
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "Second part",
                            }
                        ],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        # Should merge into single paragraph despite flags being at page level
        assert len(content.elements) == 1
        assert isinstance(content.elements[0], ParagraphItem)
        assert content.elements[0].text == "First partSecond part"

    def test_from_raw_ocr_merge_mixed_page_and_item_level_flags(self):
        """Merging should work when one page uses page-level and the other item-level flags."""
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "continues_to_next": True,
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "First part",
                            }
                        ],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "Second part",
                                "continues_from_previous": True,
                            }
                        ],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        # Should merge even with mixed flag placement
        assert len(content.elements) == 1
        assert isinstance(content.elements[0], ParagraphItem)
        assert content.elements[0].text == "First partSecond part"

    def test_from_raw_ocr_no_merge_without_continuation_flags(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [{"type": "paragraph", "text": "First"}],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [{"type": "paragraph", "text": "Second"}],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        # Should NOT merge
        assert len(content.elements) == 2

    def test_from_raw_ocr_no_merge_different_types(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "Para",
                                "continues_to_next": True,
                            }
                        ],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "list",
                                "items": ["Item"],
                                "continues_from_previous": True,
                            }
                        ],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        # Should NOT merge different types
        assert len(content.elements) == 2
        assert isinstance(content.elements[0], ParagraphItem)
        assert isinstance(content.elements[1], ListItem)

    def test_from_raw_ocr_three_way_merge(self):
        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "Part1",
                                "continues_to_next": True,
                            }
                        ],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "Part2",
                                "continues_from_previous": True,
                                "continues_to_next": True,
                            }
                        ],
                    }
                ],
                None,
            ),
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "paragraph",
                                "text": "Part3",
                                "continues_from_previous": True,
                            }
                        ],
                    }
                ],
                None,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        # Should merge all three
        assert len(content.elements) == 1
        assert content.elements[0].text == "Part1Part2Part3"

    def test_from_raw_ocr_empty_pages(self):
        pages = []
        content = MergedOCRContent.from_raw_ocr(pages)
        assert len(content.elements) == 0

    def test_from_raw_ocr_prepares_image_items(self):
        # Create test image
        img = Image.new("RGB", (100, 100), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        pages = [
            (
                [
                    {
                        "page_type": "content",
                        "content": [
                            {
                                "type": "image",
                                "bbox": {"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5},
                                "caption": "Test",
                            }
                        ],
                    }
                ],
                image_bytes,
            ),
        ]
        content = MergedOCRContent.from_raw_ocr(pages)

        assert len(content.elements) == 1
        assert isinstance(content.elements[0], ImageItem)
        # prepare() should have extracted image bytes
        assert content.elements[0].image_bytes is not None

    def test_implements_protocol(self, tmp_path):
        # Original minimal test
        content = MergedOCRContent(elements=[])

        assert hasattr(content, "get_texts")
        assert hasattr(content, "set_texts")
        assert hasattr(content, "to_markdown")

        texts = content.get_texts()
        assert isinstance(texts, list)

        markdown = content.to_markdown(tmp_path)
        assert isinstance(markdown, str)
