from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from context_aware_translation.documents.content.ocr_items import (
    BlankItem,
    BoundingBox,
    ChapterItem,
    CoverItem,
    ImageItem,
    ListItem,
    ParagraphItem,
    QuoteItem,
    RenderContext,
    SectionItem,
    SubsectionItem,
    TableItem,
    TocItem,
    _blank_factory,
    _chapter_factory,
    _coerce_bbox,
    _coerce_bool,
    _coerce_list_str_required,
    _coerce_str_optional,
    _coerce_str_required,
    _cover_factory,
    _image_factory,
    _list_factory,
    _paragraph_factory,
    _quote_factory,
    _section_factory,
    _subsection_factory,
    _table_factory,
    _toc_factory,
    ocr_item_from_dict,
)
from context_aware_translation.utils.compression_marker import COMPRESSED_LINE_SENTINEL

# ============================================================================
# BoundingBox Tests
# ============================================================================


class TestBoundingBox:
    def test_bounding_box_creation(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        assert bbox.x == 0.1
        assert bbox.y == 0.2
        assert bbox.width == 0.3
        assert bbox.height == 0.4

    def test_from_dict(self):
        data = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        bbox = BoundingBox.from_dict(data)
        assert bbox.x == 0.1
        assert bbox.y == 0.2
        assert bbox.width == 0.3
        assert bbox.height == 0.4

    def test_crop_from_image(self):
        # Create a simple 100x100 test image
        img = Image.new("RGB", (100, 100), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        # Create bbox for top-left quarter
        bbox = BoundingBox(x=0.0, y=0.0, width=0.5, height=0.5)
        cropped_bytes = bbox.crop_from_image(image_bytes)

        # Verify cropped image
        cropped_img = Image.open(io.BytesIO(cropped_bytes))
        assert cropped_img.size == (50, 50)

    def test_crop_from_image_partial(self):
        # Create a 200x200 test image
        img = Image.new("RGB", (200, 200), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        # Crop middle section
        bbox = BoundingBox(x=0.25, y=0.25, width=0.5, height=0.5)
        cropped_bytes = bbox.crop_from_image(image_bytes)

        cropped_img = Image.open(io.BytesIO(cropped_bytes))
        assert cropped_img.size == (100, 100)


# ============================================================================
# ChapterItem Tests
# ============================================================================


class TestChapterItem:
    def test_creation(self):
        item = ChapterItem(text="Chapter 1")
        assert item.text == "Chapter 1"
        assert item.translated_lines is None

    def test_get_texts_single_line(self):
        item = ChapterItem(text="Chapter 1")
        assert item.get_texts() == ["Chapter 1"]

    def test_get_texts_multiline(self):
        item = ChapterItem(text="Chapter 1\nThe Beginning")
        assert item.get_texts() == ["Chapter 1", "The Beginning"]

    def test_consume_translations(self):
        item = ChapterItem(text="Chapter 1\nThe Beginning")
        translations = ["第一章", "开始", "extra"]
        pos = item.consume_translations(translations, 0)
        assert pos == 2
        assert item.translated_lines == ["第一章", "开始"]

    def test_consume_translations_with_offset(self):
        item = ChapterItem(text="Chapter 1")
        translations = ["ignore", "第一章", "extra"]
        pos = item.consume_translations(translations, 1)
        assert pos == 2
        assert item.translated_lines == ["第一章"]

    def test_to_markdown_without_newpage(self):
        item = ChapterItem(text="Chapter 1")
        item.translated_lines = ["第一章"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "# 第一章"

    def test_to_markdown_with_newpage(self):
        item = ChapterItem(text="Chapter 1")
        item.translated_lines = ["第一章"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=True)
        result = item.to_markdown(ctx)
        assert result == "\\newpage\n# 第一章"

    def test_to_markdown_multiline(self):
        item = ChapterItem(text="Chapter 1\nThe Beginning")
        item.translated_lines = ["第一章", "开始"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "# 第一章  开始"

    def test_to_markdown_returns_empty_for_compressed_placeholder(self):
        item = ChapterItem(text="Chapter 1")
        item.translated_lines = [COMPRESSED_LINE_SENTINEL]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        assert item.to_markdown(ctx) == ""

    def test_to_markdown_raises_without_translations(self):
        item = ChapterItem(text="Chapter 1")
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        with pytest.raises(ValueError, match="Cannot render markdown without translations"):
            item.to_markdown(ctx)

    def test_merge_continuation_returns_false(self):
        item1 = ChapterItem(text="Chapter 1")
        item2 = ChapterItem(text="Chapter 2")
        assert item1.merge_continuation(item2) is False

    def test_prepare_does_nothing(self):
        item = ChapterItem(text="Chapter 1")
        page = SimpleNamespace()
        item.prepare(page)  # Should not raise


# ============================================================================
# SectionItem Tests
# ============================================================================


class TestSectionItem:
    def test_creation(self):
        item = SectionItem(text="Section 1.1")
        assert item.text == "Section 1.1"

    def test_get_texts(self):
        item = SectionItem(text="Section 1.1\nIntroduction")
        assert item.get_texts() == ["Section 1.1", "Introduction"]

    def test_consume_translations(self):
        item = SectionItem(text="Section 1.1")
        translations = ["第1.1节"]
        pos = item.consume_translations(translations, 0)
        assert pos == 1
        assert item.translated_lines == ["第1.1节"]

    def test_to_markdown(self):
        item = SectionItem(text="Section 1.1")
        item.translated_lines = ["第1.1节"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "## 第1.1节"

    def test_to_markdown_raises_without_translations(self):
        item = SectionItem(text="Section 1.1")
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        with pytest.raises(ValueError, match="Cannot render markdown without translations"):
            item.to_markdown(ctx)

    def test_merge_continuation_returns_false(self):
        item1 = SectionItem(text="Section 1")
        item2 = SectionItem(text="Section 2")
        assert item1.merge_continuation(item2) is False


# ============================================================================
# SubsectionItem Tests
# ============================================================================


class TestSubsectionItem:
    def test_creation(self):
        item = SubsectionItem(text="Subsection 1.1.1")
        assert item.text == "Subsection 1.1.1"

    def test_get_texts(self):
        item = SubsectionItem(text="Subsection 1.1.1")
        assert item.get_texts() == ["Subsection 1.1.1"]

    def test_consume_translations(self):
        item = SubsectionItem(text="Subsection 1.1.1")
        translations = ["第1.1.1小节"]
        pos = item.consume_translations(translations, 0)
        assert pos == 1
        assert item.translated_lines == ["第1.1.1小节"]

    def test_to_markdown(self):
        item = SubsectionItem(text="Subsection 1.1.1")
        item.translated_lines = ["第1.1.1小节"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "### 第1.1.1小节"

    def test_merge_continuation_returns_false(self):
        item1 = SubsectionItem(text="Subsection 1")
        item2 = SubsectionItem(text="Subsection 2")
        assert item1.merge_continuation(item2) is False


# ============================================================================
# ParagraphItem Tests
# ============================================================================


class TestParagraphItem:
    def test_creation(self):
        item = ParagraphItem(text="This is a paragraph.")
        assert item.text == "This is a paragraph."

    def test_get_texts_returns_single_item(self):
        item = ParagraphItem(text="This is a paragraph.")
        assert item.get_texts() == ["This is a paragraph."]

    def test_consume_translations(self):
        item = ParagraphItem(text="This is a paragraph.")
        translations = ["这是一个段落。"]
        pos = item.consume_translations(translations, 0)
        assert pos == 1
        assert item.translated_lines == ["这是一个段落。"]

    def test_to_markdown(self):
        item = ParagraphItem(text="This is a paragraph.")
        item.translated_lines = ["这是一个段落。"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "这是一个段落。"

    def test_to_markdown_raises_without_translations(self):
        item = ParagraphItem(text="This is a paragraph.")
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        with pytest.raises(ValueError, match="Cannot render markdown without translations"):
            item.to_markdown(ctx)

    def test_merge_continuation_success(self):
        item1 = ParagraphItem(text="First part", continues_to_next=True)
        item2 = ParagraphItem(text="Second part", continues_from_previous=True)
        assert item1.merge_continuation(item2) is True
        assert item1.text == "First partSecond part"
        assert item1.continues_to_next is False

    def test_merge_continuation_with_translations(self):
        item1 = ParagraphItem(text="First part", continues_to_next=True)
        item1.translated_lines = ["第一部分"]
        item2 = ParagraphItem(text="Second part", continues_from_previous=True)
        item2.translated_lines = ["第二部分"]
        assert item1.merge_continuation(item2) is True
        assert item1.translated_lines == ["第一部分", "第二部分"]

    def test_merge_continuation_preserves_continues_to_next(self):
        item1 = ParagraphItem(text="First", continues_to_next=True)
        item2 = ParagraphItem(text="Second", continues_from_previous=True, continues_to_next=True)
        assert item1.merge_continuation(item2) is True
        assert item1.continues_to_next is True

    def test_merge_continuation_fails_without_flags(self):
        item1 = ParagraphItem(text="First part", continues_to_next=False)
        item2 = ParagraphItem(text="Second part", continues_from_previous=True)
        assert item1.merge_continuation(item2) is False

    def test_merge_continuation_fails_wrong_type(self):
        item1 = ParagraphItem(text="Paragraph", continues_to_next=True)
        item2 = ChapterItem(text="Chapter")
        assert item1.merge_continuation(item2) is False


# ============================================================================
# ListItem Tests
# ============================================================================


class TestListItem:
    def test_creation(self):
        item = ListItem(items=["Item 1", "Item 2"])
        assert item.items == ["Item 1", "Item 2"]

    def test_get_texts(self):
        item = ListItem(items=["Item 1", "Item 2", "Item 3"])
        assert item.get_texts() == ["Item 1", "Item 2", "Item 3"]

    def test_consume_translations(self):
        item = ListItem(items=["Item 1", "Item 2"])
        translations = ["项目1", "项目2", "extra"]
        pos = item.consume_translations(translations, 0)
        assert pos == 2
        assert item.translated_lines == ["项目1", "项目2"]

    def test_to_markdown(self):
        item = ListItem(items=["Item 1", "Item 2"])
        item.translated_lines = ["项目1", "项目2"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "- 项目1\n- 项目2"

    def test_to_markdown_skips_list_entry_for_compressed_placeholder(self):
        item = ListItem(items=["Item 1", "Item 2"])
        item.translated_lines = ["项目1", COMPRESSED_LINE_SENTINEL]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        assert item.to_markdown(ctx) == "- 项目1"

    def test_to_markdown_raises_without_translations(self):
        item = ListItem(items=["Item 1"])
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        with pytest.raises(ValueError, match="Cannot render markdown without translations"):
            item.to_markdown(ctx)

    def test_merge_continuation_success(self):
        item1 = ListItem(items=["Item 1"], continues_to_next=True)
        item1.translated_lines = ["项目1"]
        item2 = ListItem(items=["Item 2"], continues_from_previous=True)
        item2.translated_lines = ["项目2"]
        assert item1.merge_continuation(item2) is True
        assert item1.items == ["Item 1", "Item 2"]
        assert item1.translated_lines == ["项目1", "项目2"]
        assert item1.continues_to_next is False

    def test_merge_continuation_preserves_continues_to_next(self):
        item1 = ListItem(items=["Item 1"], continues_to_next=True)
        item1.translated_lines = ["项目1"]
        item2 = ListItem(items=["Item 2"], continues_from_previous=True, continues_to_next=True)
        item2.translated_lines = ["项目2"]
        assert item1.merge_continuation(item2) is True
        assert item1.continues_to_next is True

    def test_merge_continuation_fails_without_flags(self):
        item1 = ListItem(items=["Item 1"], continues_to_next=False)
        item2 = ListItem(items=["Item 2"], continues_from_previous=True)
        assert item1.merge_continuation(item2) is False

    def test_merge_continuation_fails_wrong_type(self):
        item1 = ListItem(items=["Item 1"], continues_to_next=True)
        item2 = ParagraphItem(text="Paragraph", continues_from_previous=True)
        assert item1.merge_continuation(item2) is False


# ============================================================================
# ImageItem Tests
# ============================================================================


class TestImageItem:
    def test_creation(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, caption="Figure 1")
        assert item.bbox == bbox
        assert item.caption == "Figure 1"
        assert item.embedded_text is None

    def test_get_texts_with_caption_only(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, caption="Figure 1\nA diagram")
        assert item.get_texts() == ["Figure 1", "A diagram"]

    def test_get_texts_with_embedded_text_only(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, embedded_text="Text in image\nLine 2")
        assert item.get_texts() == ["Text in image", "Line 2"]

    def test_get_texts_with_both(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, embedded_text="Embedded", caption="Caption")
        assert item.get_texts() == ["Embedded", "Caption"]

    def test_consume_translations_with_both(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, embedded_text="Embedded\nText", caption="Caption\nLine2")
        translations = ["嵌入", "文本", "标题", "第二行"]
        pos = item.consume_translations(translations, 0)
        assert pos == 4
        assert item.embedded_translated_lines == ["嵌入", "文本"]
        assert item.translated_lines == ["标题", "第二行"]

    def test_consume_translations_caption_only(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, caption="Caption")
        translations = ["标题"]
        pos = item.consume_translations(translations, 0)
        assert pos == 1
        assert item.embedded_translated_lines is None
        assert item.translated_lines == ["标题"]

    def test_get_embedded_translation_decodes_compressed_placeholder(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, embedded_text="A")
        item.embedded_translated_lines = [COMPRESSED_LINE_SENTINEL]
        assert item.get_embedded_translation() == ""

    def test_to_markdown(self, tmp_path):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, caption="Figure 1")
        item.translated_lines = ["图1"]

        # Create test image
        img = Image.new("RGB", (50, 50), color="green")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        item.image_bytes = buffer.getvalue()

        ctx = RenderContext(image_dir=tmp_path, insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)

        # Verify markdown format and image saved
        assert result.startswith("![图1](")
        assert result.endswith(".png)")

        # Check image file was created
        image_files = list(tmp_path.glob("ocr_*.png"))
        assert len(image_files) == 1

    def test_to_markdown_multiline_caption(self, tmp_path):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, caption="Figure 1\nDescription")
        item.translated_lines = ["图1", "描述"]

        img = Image.new("RGB", (50, 50), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        item.image_bytes = buffer.getvalue()

        ctx = RenderContext(image_dir=tmp_path, insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)

        assert "图1<br/>描述" in result

    def test_to_markdown_raises_without_translations(self, tmp_path):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, caption="Figure 1")
        ctx = RenderContext(image_dir=tmp_path, insert_new_page_before_chapter=False)
        with pytest.raises(ValueError, match="Cannot render markdown without translations"):
            item.to_markdown(ctx)

    def test_to_markdown_raises_without_image_bytes(self, tmp_path):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item = ImageItem(bbox=bbox, caption="Figure 1")
        item.translated_lines = ["图1"]
        ctx = RenderContext(image_dir=tmp_path, insert_new_page_before_chapter=False)
        with pytest.raises(Exception, match="Image not found"):
            item.to_markdown(ctx)

    def test_prepare_extracts_image_from_page(self):
        # Create test image
        img = Image.new("RGB", (100, 100), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        bbox = BoundingBox(x=0.0, y=0.0, width=0.5, height=0.5)
        item = ImageItem(bbox=bbox, caption="Test")

        page = SimpleNamespace(source_image_bytes=image_bytes)
        item.prepare(page)

        assert item.image_bytes is not None
        # Verify it's valid image data
        cropped_img = Image.open(io.BytesIO(item.image_bytes))
        assert cropped_img.size == (50, 50)

    def test_prepare_without_source_bytes(self):
        bbox = BoundingBox(x=0.0, y=0.0, width=0.5, height=0.5)
        item = ImageItem(bbox=bbox, caption="Test")
        page = SimpleNamespace()
        item.prepare(page)
        assert item.image_bytes is None

    def test_merge_continuation_returns_false(self):
        bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
        item1 = ImageItem(bbox=bbox, caption="Fig 1", continues_to_next=True)
        item2 = ImageItem(bbox=bbox, caption="Fig 2", continues_from_previous=True)
        assert item1.merge_continuation(item2) is False


# ============================================================================
# TableItem Tests
# ============================================================================


class TestTableItem:
    def test_creation(self):
        item = TableItem(text="| A | B |\n| 1 | 2 |", caption="Table 1")
        assert item.text == "| A | B |\n| 1 | 2 |"
        assert item.caption == "Table 1"

    def test_get_texts_with_caption(self):
        item = TableItem(text="| A | B |", caption="Table 1\nResults")
        assert item.get_texts() == ["| A | B |", "Table 1", "Results"]

    def test_get_texts_without_caption(self):
        item = TableItem(text="| A | B |\n| 1 | 2 |")
        assert item.get_texts() == ["| A | B |", "| 1 | 2 |"]

    def test_consume_translations(self):
        item = TableItem(text="| A | B |", caption="Table 1")
        translations = ["| 甲 | 乙 |", "表格1"]
        pos = item.consume_translations(translations, 0)
        assert pos == 2
        assert item.translated_lines == ["| 甲 | 乙 |"]
        assert item.translated_caption == ["表格1"]

    def test_consume_translations_without_caption(self):
        item = TableItem(text="| A | B |")
        translations = ["| 甲 | 乙 |"]
        pos = item.consume_translations(translations, 0)
        assert pos == 1
        assert item.translated_lines == ["| 甲 | 乙 |"]
        assert item.translated_caption is None

    def test_to_markdown_with_caption(self):
        item = TableItem(text="| A | B |", caption="Table 1")
        item.translated_lines = ["| 甲 | 乙 |"]
        item.translated_caption = ["表格1"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "| 甲 | 乙 |\n\nTable: 表格1"

    def test_to_markdown_without_caption(self):
        item = TableItem(text="| A | B |")
        item.translated_lines = ["| 甲 | 乙 |"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "| 甲 | 乙 |"

    def test_to_markdown_raises_without_translations(self):
        item = TableItem(text="| A | B |")
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        with pytest.raises(ValueError, match="Cannot render markdown without translations"):
            item.to_markdown(ctx)

    def test_merge_continuation_success(self):
        item1 = TableItem(text="| A | B |", continues_to_next=True)
        item1.translated_lines = ["| 甲 | 乙 |"]
        item2 = TableItem(text="| 1 | 2 |", caption="Table 1", continues_from_previous=True)
        item2.translated_lines = ["| 1 | 2 |"]
        item2.translated_caption = ["表格1"]
        assert item1.merge_continuation(item2) is True
        assert item1.text == "| A | B |\n| 1 | 2 |"
        assert item1.caption == "Table 1"
        assert item1.translated_lines == ["| 甲 | 乙 |", "| 1 | 2 |"]
        assert item1.translated_caption == ["表格1"]
        assert item1.continues_to_next is False

    def test_merge_continuation_preserves_continues_to_next(self):
        item1 = TableItem(text="| A |", continues_to_next=True)
        item1.translated_lines = ["| 甲 |"]
        item2 = TableItem(text="| B |", continues_from_previous=True, continues_to_next=True)
        item2.translated_lines = ["| 乙 |"]
        assert item1.merge_continuation(item2) is True
        assert item1.continues_to_next is True

    def test_merge_continuation_fails_without_flags(self):
        item1 = TableItem(text="| A |", continues_to_next=False)
        item2 = TableItem(text="| B |", continues_from_previous=True)
        assert item1.merge_continuation(item2) is False

    def test_merge_continuation_fails_wrong_type(self):
        item1 = TableItem(text="| A |", continues_to_next=True)
        item2 = ParagraphItem(text="Para", continues_from_previous=True)
        assert item1.merge_continuation(item2) is False


# ============================================================================
# QuoteItem Tests
# ============================================================================


class TestQuoteItem:
    def test_creation(self):
        item = QuoteItem(text="Famous quote")
        assert item.text == "Famous quote"

    def test_get_texts(self):
        item = QuoteItem(text="Line 1\nLine 2")
        assert item.get_texts() == ["Line 1", "Line 2"]

    def test_consume_translations(self):
        item = QuoteItem(text="Quote line 1\nQuote line 2")
        translations = ["引用第一行", "引用第二行"]
        pos = item.consume_translations(translations, 0)
        assert pos == 2
        assert item.translated_lines == ["引用第一行", "引用第二行"]

    def test_to_markdown(self):
        item = QuoteItem(text="Quote")
        item.translated_lines = ["引用"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == "> 引用"

    def test_to_markdown_multiline(self):
        item = QuoteItem(text="Quote\nLine 2")
        item.translated_lines = ["引用", "第二行"]
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        # Each line in blockquote needs "> " prefix for proper markdown
        assert result == "> 引用\n> 第二行"

    def test_to_markdown_raises_without_translations(self):
        item = QuoteItem(text="Quote")
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        with pytest.raises(ValueError, match="Cannot render markdown without translations"):
            item.to_markdown(ctx)

    def test_merge_continuation_success(self):
        # QuoteItems merge when continuation flags are set
        item1 = QuoteItem(text="First", continues_to_next=True)
        item1.translated_lines = ["第一"]
        item2 = QuoteItem(text="Second", continues_from_previous=True)
        item2.translated_lines = ["第二"]
        assert item1.merge_continuation(item2) is True
        assert item1.text == "FirstSecond"
        assert item1.translated_lines == ["第一", "第二"]


# ============================================================================
# CoverItem Tests
# ============================================================================


class TestCoverItem:
    def test_creation(self):
        item = CoverItem()
        assert item.image_bytes is None

    def test_creation_with_image(self):
        item = CoverItem(image_bytes=b"fake_image_data")
        assert item.image_bytes == b"fake_image_data"

    def test_get_texts_returns_empty(self):
        item = CoverItem()
        assert item.get_texts() == []

    def test_consume_translations_returns_same_pos(self):
        item = CoverItem()
        pos = item.consume_translations(["ignored"], 5)
        assert pos == 5

    def test_to_markdown(self, tmp_path):
        img = Image.new("RGB", (100, 100), color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        item = CoverItem(image_bytes=buffer.getvalue())
        ctx = RenderContext(image_dir=tmp_path, insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)

        # CoverItem outputs YAML frontmatter for pandoc epub cover
        assert result.startswith("---\ncover-image:")
        assert result.endswith("---")

        # Verify image was saved with cover_ prefix
        image_files = list(tmp_path.glob("cover_*.png"))
        assert len(image_files) == 1

    def test_to_markdown_returns_empty_without_image_bytes(self, tmp_path):
        item = CoverItem()
        ctx = RenderContext(image_dir=tmp_path, insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == ""

    def test_merge_continuation_returns_false(self):
        item1 = CoverItem()
        item2 = CoverItem()
        assert item1.merge_continuation(item2) is False

    def test_prepare_does_nothing(self):
        item = CoverItem()
        page = SimpleNamespace()
        item.prepare(page)  # Should not raise

    def test_multiple_covers_first_is_yaml_rest_are_images(self, tmp_path):
        """Test that only first cover is YAML frontmatter, rest are page-break images."""
        img = Image.new("RGB", (100, 100), color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        cover1 = CoverItem(image_bytes=image_bytes)
        cover2 = CoverItem(image_bytes=image_bytes)
        cover3 = CoverItem(image_bytes=image_bytes)

        ctx = RenderContext(image_dir=tmp_path, insert_new_page_before_chapter=False)

        # First cover should be YAML frontmatter
        result1 = cover1.to_markdown(ctx)
        assert result1.startswith("---\ncover-image:")
        assert result1.endswith("---")
        assert ctx.first_cover_rendered is True

        # Second cover should be page-break + image
        result2 = cover2.to_markdown(ctx)
        assert result2.startswith("\\newpage")
        assert "![Cover](" in result2
        assert "---" not in result2

        # Third cover should also be page-break + image
        result3 = cover3.to_markdown(ctx)
        assert result3.startswith("\\newpage")
        assert "![Cover](" in result3

        # Verify all images were saved
        image_files = list(tmp_path.glob("cover_*.png"))
        assert len(image_files) == 3


# ============================================================================
# TocItem Tests
# ============================================================================


class TestTocItem:
    def test_get_texts_returns_empty(self):
        item = TocItem()
        assert item.get_texts() == []

    def test_consume_translations_returns_same_pos(self):
        item = TocItem()
        pos = item.consume_translations(["ignored"], 3)
        assert pos == 3

    def test_to_markdown_returns_empty(self):
        item = TocItem()
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == ""

    def test_merge_continuation_returns_false(self):
        item1 = TocItem()
        item2 = TocItem()
        assert item1.merge_continuation(item2) is False

    def test_prepare_does_nothing(self):
        item = TocItem()
        page = SimpleNamespace()
        item.prepare(page)


# ============================================================================
# BlankItem Tests
# ============================================================================


class TestBlankItem:
    def test_get_texts_returns_empty(self):
        item = BlankItem()
        assert item.get_texts() == []

    def test_consume_translations_returns_same_pos(self):
        item = BlankItem()
        pos = item.consume_translations(["ignored"], 7)
        assert pos == 7

    def test_to_markdown_returns_empty(self):
        item = BlankItem()
        ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=False)
        result = item.to_markdown(ctx)
        assert result == ""

    def test_merge_continuation_returns_false(self):
        item1 = BlankItem()
        item2 = BlankItem()
        assert item1.merge_continuation(item2) is False

    def test_prepare_does_nothing(self):
        item = BlankItem()
        page = SimpleNamespace()
        item.prepare(page)


# ============================================================================
# Factory Functions Tests
# ============================================================================


class TestFactoryFunctions:
    def test_chapter_factory(self):
        data = {"type": "chapter", "text": "Chapter 1", "continues_from_previous": True}
        item = _chapter_factory(data)
        assert isinstance(item, ChapterItem)
        assert item.text == "Chapter 1"

    def test_section_factory(self):
        data = {"type": "section", "text": "Section 1", "continues_to_next": True}
        item = _section_factory(data)
        assert isinstance(item, SectionItem)
        assert item.text == "Section 1"

    def test_subsection_factory(self):
        data = {"type": "subsection", "text": "Subsection 1"}
        item = _subsection_factory(data)
        assert isinstance(item, SubsectionItem)
        assert item.text == "Subsection 1"

    def test_paragraph_factory(self):
        data = {"type": "paragraph", "text": "Para\nwith\nnewlines"}
        item = _paragraph_factory(data)
        assert isinstance(item, ParagraphItem)
        # Newlines are preserved for code blocks and other multi-line content
        assert item.text == "Para\nwith\nnewlines"

    def test_list_factory(self):
        data = {"type": "list", "items": ["Item 1", "Item 2"]}
        item = _list_factory(data)
        assert isinstance(item, ListItem)
        assert item.items == ["Item 1", "Item 2"]

    def test_image_factory(self):
        data = {
            "type": "image",
            "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            "caption": "Figure 1",
            "embedded_text": "Text in image",
        }
        item = _image_factory(data)
        assert isinstance(item, ImageItem)
        assert item.caption == "Figure 1"
        assert item.embedded_text == "Text in image"
        assert item.bbox.x == 0.1

    def test_table_factory(self):
        data = {"type": "table", "text": "| A | B |", "caption": "Table 1"}
        item = _table_factory(data)
        assert isinstance(item, TableItem)
        assert item.text == "| A | B |"
        assert item.caption == "Table 1"

    def test_quote_factory(self):
        data = {"type": "quote", "text": "Quote text"}
        item = _quote_factory(data)
        assert isinstance(item, QuoteItem)
        assert item.text == "Quote text"

    def test_cover_factory(self):
        item = _cover_factory({})
        assert isinstance(item, CoverItem)

    def test_toc_factory(self):
        item = _toc_factory({})
        assert isinstance(item, TocItem)

    def test_blank_factory(self):
        item = _blank_factory({})
        assert isinstance(item, BlankItem)


# ============================================================================
# ocr_item_from_dict Tests
# ============================================================================


class TestOcrItemFromDict:
    def test_creates_chapter_item(self):
        data = {"type": "chapter", "text": "Chapter 1"}
        item = ocr_item_from_dict(data)
        assert isinstance(item, ChapterItem)
        assert item.text == "Chapter 1"

    def test_creates_paragraph_item(self):
        data = {"type": "paragraph", "text": "Paragraph text"}
        item = ocr_item_from_dict(data)
        assert isinstance(item, ParagraphItem)
        assert item.text == "Paragraph text"

    def test_creates_list_item(self):
        data = {"type": "list", "items": ["A", "B"]}
        item = ocr_item_from_dict(data)
        assert isinstance(item, ListItem)
        assert item.items == ["A", "B"]

    def test_creates_image_item(self):
        data = {"type": "image", "bbox": {"x": 0, "y": 0, "width": 1, "height": 1}}
        item = ocr_item_from_dict(data)
        assert isinstance(item, ImageItem)

    def test_creates_table_item(self):
        data = {"type": "table", "text": "| A |"}
        item = ocr_item_from_dict(data)
        assert isinstance(item, TableItem)

    def test_creates_cover_item(self):
        data = {"type": "cover"}
        item = ocr_item_from_dict(data)
        assert isinstance(item, CoverItem)

    def test_raises_for_missing_type(self):
        data = {"text": "No type field"}
        with pytest.raises(ValueError, match="missing 'type'"):
            ocr_item_from_dict(data)

    def test_raises_for_invalid_type_value(self):
        data = {"type": 123}  # Not a string
        with pytest.raises(ValueError, match="missing 'type'"):
            ocr_item_from_dict(data)

    def test_raises_for_unsupported_type(self):
        data = {"type": "unknown_type"}
        with pytest.raises(ValueError, match="Unsupported OCR item type: unknown_type"):
            ocr_item_from_dict(data)


# ============================================================================
# Coercion Helper Tests
# ============================================================================


class TestCoercionHelpers:
    def test_coerce_str_required_success(self):
        assert _coerce_str_required("hello") == "hello"

    def test_coerce_str_required_raises_for_none(self):
        with pytest.raises(Exception, match="Invalid JSON format"):
            _coerce_str_required(None)

    def test_coerce_str_required_raises_for_int(self):
        with pytest.raises(Exception, match="Invalid JSON format"):
            _coerce_str_required(123)

    def test_coerce_str_optional_success(self):
        assert _coerce_str_optional("hello") == "hello"
        assert _coerce_str_optional(None) is None

    def test_coerce_str_optional_raises_for_int(self):
        with pytest.raises(Exception, match="Invalid JSON format"):
            _coerce_str_optional(123)

    def test_coerce_list_str_required_success(self):
        assert _coerce_list_str_required(["a", "b"]) == ["a", "b"]

    def test_coerce_list_str_required_raises_for_none(self):
        with pytest.raises(Exception, match="Invalid JSON format"):
            _coerce_list_str_required(None)

    def test_coerce_list_str_required_raises_for_mixed_types(self):
        with pytest.raises(Exception, match="Invalid JSON format"):
            _coerce_list_str_required(["a", 123])

    def test_coerce_bool_with_true(self):
        assert _coerce_bool(True) is True

    def test_coerce_bool_with_false(self):
        assert _coerce_bool(False) is False

    def test_coerce_bool_with_none_uses_default(self):
        assert _coerce_bool(None, default=False) is False
        assert _coerce_bool(None, default=True) is True

    def test_coerce_bool_raises_for_string(self):
        with pytest.raises(Exception, match="Invalid JSON format"):
            _coerce_bool("true")

    def test_coerce_bbox_success(self):
        data = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        bbox = _coerce_bbox(data)
        assert isinstance(bbox, BoundingBox)
        assert bbox.x == 0.1
        assert bbox.y == 0.2

    def test_coerce_bbox_raises_for_non_dict(self):
        with pytest.raises(Exception, match="Invalid JSON format"):
            _coerce_bbox("not a dict")
