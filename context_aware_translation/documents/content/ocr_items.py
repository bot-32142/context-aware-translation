from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from PIL import Image

from context_aware_translation.utils.compression_marker import (
    decode_compressed_lines,
    is_compressed_line,
)
from context_aware_translation.utils.markdown_escape import clean_llm_output


class OCRItem(Protocol):
    """Protocol for OCR content items that participate in the translation pipeline.

    Pipeline flow:
    1. OCR Extraction: Raw JSON parsed into OCRItem objects
    2. Merge Continuations: Cross-page content merged via merge_continuation()
    3. Extract Texts: get_texts() collects all translatable strings
    4. Translate: External LLM translates the flat list
    5. Distribute Translations: consume_translations() assigns translations back to items
    6. Render: to_markdown() outputs final formatted text

    Key design patterns:
    - Flat list translation: All items return flat list[str] to avoid reshaping data
    - pos cursor: consume_translations() uses sequential cursor to distribute translations
    - Cross-page merging: Items with continuation flags merge before translation
    - Resource extraction: prepare() extracts images/resources before processing
    """

    def get_texts(self) -> list[str]:
        """Extract all translatable text from this item as a flat list.

        Called during Stage 3 (Extract Texts) to collect all strings needing translation.

        Returns:
            Flat list of strings in order. Each string will be translated 1:1.

        Examples:
            ChapterItem(text="Chapter 1\\nThe Beginning") → ["Chapter 1", "The Beginning"]
            ParagraphItem(text="Hello world") → ["Hello world"]
            ListItem(items=["A", "B"]) → ["A", "B"]
            ImageItem(embedded_text="Text", caption="Caption") → ["Text", "Caption"]
            CoverItem() → [] (no translatable text)
        """
        ...

    def consume_translations(self, translations: list[str], pos: int) -> int:
        """Assign translated strings to this item using the pos cursor pattern.

        Called during Stage 5 (Distribute Translations) in a loop over all items.

        Args:
            translations: Flat list of all translated strings (for all items in the document)
            pos: Starting position/cursor in translations list for this item

        Returns:
            New position after consuming this item's translations (pos + consumed_count).
            Next item starts at the returned position.

        Pattern:
            The pos parameter acts as a cursor into the flat translations list.
            Each item consumes len(get_texts()) translations starting at pos,
            then returns pos + consumed_count for the next item.

        Example:
            translations = ["第一章", "开始", "你好世界"]

            # First item (ChapterItem with 2 lines)
            pos = item1.consume_translations(translations, 0)
            # item1.translated_lines = ["第一章", "开始"]
            # returns 2

            # Second item (ParagraphItem with 1 line)
            pos = item2.consume_translations(translations, 2)
            # item2.translated_lines = ["你好世界"]
            # returns 3
        """
        ...

    def merge_continuation(self, other: OCRItem) -> bool:
        """Attempt to merge split content from adjacent pages.

        Called during Stage 2 (Merge Continuations) when processing multi-page documents.
        Items marked with continues_to_next=True and continues_from_previous=True are merged.

        Args:
            other: Next item to potentially merge into this item

        Returns:
            True if merge succeeded (other absorbed into self), False otherwise

        Behavior by item type:
            - ChapterItem, SectionItem, SubsectionItem: Always False (never merge)
            - ParagraphItem: Merge if self.continues_to_next and other.continues_from_previous
            - ListItem: Same as ParagraphItem, extends items list
            - TableItem: Merges rows and updates caption from other
            - ImageItem, CoverItem, TocItem, BlankItem: Always False

        Example:
            # Page 1 ends mid-paragraph
            item1 = ParagraphItem(text="First part", continues_to_next=True)

            # Page 2 continues
            item2 = ParagraphItem(text="Second part", continues_from_previous=True)

            result = item1.merge_continuation(item2)  # True
            # item1.text = "First partSecond part"
            # item1.continues_to_next = item2.continues_to_next
            # If both have translations, they're concatenated
        """
        ...

    def to_markdown(self, ctx: RenderContext) -> str:
        """Render this item to Pandoc-compatible markdown.

        Called during Stage 6 (Render) after translations have been applied.

        Args:
            ctx: Rendering context with image_dir for saving images and formatting flags

        Returns:
            Markdown string representation with translations

        Raises:
            ValueError: If translated_lines is None (translation not applied)

        Behavior by item type:
            - ChapterItem: "# translated_text" (with optional \\newpage)
            - SectionItem: "## translated_text"
            - SubsectionItem: "### translated_text"
            - ParagraphItem: "translated_text"
            - ListItem: "- item1\\n- item2\\n..."
            - ImageItem: Saves image to disk, returns "![caption](path)"
            - TableItem: "table_markdown\\n\\nTable: caption"
            - CoverItem: Saves cover image, returns "![Cover](path)"
            - TocItem, BlankItem: ""

        Example:
            item = ChapterItem(text="Chapter 1", translated_lines=["第一章"])
            ctx = RenderContext(image_dir=Path("/tmp"), insert_new_page_before_chapter=True)
            markdown = item.to_markdown(ctx)
            # "\\\\newpage\\n# 第一章"
        """
        ...

    def prepare(self, page: object) -> None:
        """Extract resources from the page before processing.

        Called during Stage 2 (Merge Continuations) before merge_continuation().
        Used to extract images and other page-specific resources.

        Args:
            page: SimpleNamespace with source_image_bytes attribute (full page image)

        Behavior by item type:
            - ImageItem: Crops image using bbox, stores in self.image_bytes
            - CoverItem: Stores full page image in self.image_bytes
            - All other items: No-op

        Example:
            item = ImageItem(bbox=BoundingBox(x=0.0, y=0.0, width=0.5, height=0.5))
            page = SimpleNamespace(source_image_bytes=full_page_png_bytes)

            item.prepare(page)
            # item.image_bytes now contains cropped 50% of page image
        """
        ...

    def to_json(self) -> dict[str, Any]:
        """Serialize this item back to JSON-compatible dict.

        Returns the item in the same format as the original OCR JSON,
        with text fields updated to current values (original or translated).

        Returns:
            Dict matching the OCR JSON schema for this item type.
        """
        ...


@dataclass
class RenderContext:
    image_dir: Path
    insert_new_page_before_chapter: bool
    strip_llm_artifacts: bool = True
    use_original_images: bool = False
    first_cover_rendered: bool = False  # Tracks if first cover has been rendered


def _decoded_lines(lines: list[str] | None) -> list[str] | None:
    if lines is None:
        return None
    return decode_compressed_lines(lines)


def _has_non_compressed_line(lines: list[str]) -> bool:
    return any(not is_compressed_line(line) for line in lines)


def _drop_compressed_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if not is_compressed_line(line)]


@dataclass
class BoundingBox:
    x: float
    y: float
    width: float
    height: float

    def crop_from_image(self, image_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        left = int(self.x * w)
        top = int(self.y * h)
        right = int((self.x + self.width) * w)
        bottom = int((self.y + self.height) * h)

        cropped = img.crop((left, top, right, bottom))

        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BoundingBox:
        return cls(x=d["x"], y=d["y"], width=d["width"], height=d["height"])


@dataclass
class ChapterItem(OCRItem):
    text: str
    translated_lines: list[str] | None = None

    def get_texts(self) -> list[str]:
        return self.text.splitlines()

    def consume_translations(self, translations: list[str], pos: int) -> int:
        lines = self.text.splitlines()
        self.translated_lines = translations[pos : pos + len(lines)]
        return pos + len(lines)

    def to_markdown(self, ctx: RenderContext) -> str:
        if self.translated_lines is None:
            raise ValueError("Cannot render markdown without translations. Call set_texts() first.")
        if not _has_non_compressed_line(self.translated_lines):
            return ""
        translated_lines = _drop_compressed_lines(self.translated_lines)
        res = ""
        if ctx.insert_new_page_before_chapter:
            res = "\\newpage\n"
        escaped_text = clean_llm_output(
            "  ".join(translated_lines),
            strip_artifacts=ctx.strip_llm_artifacts,
        )
        return res + f"# {escaped_text}"

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        translated_lines = _decoded_lines(self.translated_lines)
        text = "\n".join(translated_lines) if translated_lines else self.text
        return {"type": "chapter", "text": text}


@dataclass
class SectionItem(OCRItem):
    text: str
    translated_lines: list[str] | None = None

    def get_texts(self) -> list[str]:
        return self.text.splitlines()

    def consume_translations(self, translations: list[str], pos: int) -> int:
        lines = self.text.splitlines()
        self.translated_lines = translations[pos : pos + len(lines)]
        return pos + len(lines)

    def to_markdown(self, ctx: RenderContext) -> str:
        if self.translated_lines is None:
            raise ValueError("Cannot render markdown without translations.")
        if not _has_non_compressed_line(self.translated_lines):
            return ""
        translated_lines = _drop_compressed_lines(self.translated_lines)
        escaped_text = clean_llm_output(
            "  ".join(translated_lines),
            strip_artifacts=ctx.strip_llm_artifacts,
        )
        return f"## {escaped_text}"

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        translated_lines = _decoded_lines(self.translated_lines)
        text = "\n".join(translated_lines) if translated_lines else self.text
        return {"type": "section", "text": text}


@dataclass
class SubsectionItem(OCRItem):
    text: str
    translated_lines: list[str] | None = None

    def get_texts(self) -> list[str]:
        return self.text.splitlines()

    def consume_translations(self, translations: list[str], pos: int) -> int:
        lines = self.text.splitlines()
        self.translated_lines = translations[pos : pos + len(lines)]
        return pos + len(lines)

    def to_markdown(self, ctx: RenderContext) -> str:
        if self.translated_lines is None:
            raise ValueError("Cannot render markdown without translations. Call set_texts() first.")
        if not _has_non_compressed_line(self.translated_lines):
            return ""
        translated_lines = _drop_compressed_lines(self.translated_lines)
        escaped_text = clean_llm_output(
            "  ".join(translated_lines),
            strip_artifacts=ctx.strip_llm_artifacts,
        )
        return f"### {escaped_text}"

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        translated_lines = _decoded_lines(self.translated_lines)
        text = "\n".join(translated_lines) if translated_lines else self.text
        return {"type": "subsection", "text": text}


@dataclass
class ParagraphItem(OCRItem):
    text: str
    continues_from_previous: bool = False
    continues_to_next: bool = False
    translated_lines: list[str] | None = None

    def get_texts(self) -> list[str]:
        return self.text.splitlines()

    def consume_translations(self, translations: list[str], pos: int) -> int:
        lines = self.text.splitlines()
        self.translated_lines = translations[pos : pos + len(lines)]
        return pos + len(lines)

    def to_markdown(self, ctx: RenderContext) -> str:
        if self.translated_lines is None:
            raise ValueError("Cannot render markdown without translations. Call set_texts() first.")
        if not _has_non_compressed_line(self.translated_lines):
            return ""
        translated_lines = _drop_compressed_lines(self.translated_lines)
        joined = "\n".join(translated_lines)
        if not joined and translated_lines:
            # Preserve true empty source lines (not compression markers).
            return "\n"
        return clean_llm_output(
            joined,
            strip_artifacts=ctx.strip_llm_artifacts,
        )

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        if not isinstance(other, ParagraphItem):
            return False
        if self.continues_to_next and other.continues_from_previous:
            self.text += other.text
            self.continues_to_next = other.continues_to_next
            if self.translated_lines is not None and other.translated_lines is not None:
                self.translated_lines.extend(other.translated_lines)
            return True
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        translated_lines = _decoded_lines(self.translated_lines)
        text = "\n".join(translated_lines) if translated_lines else self.text
        result: dict[str, Any] = {"type": "paragraph", "text": text}
        if self.continues_from_previous:
            result["continues_from_previous"] = True
        if self.continues_to_next:
            result["continues_to_next"] = True
        return result


@dataclass
class ListItem(OCRItem):
    items: list[str]
    continues_from_previous: bool = False
    continues_to_next: bool = False
    translated_lines: list[str] | None = None

    def get_texts(self) -> list[str]:
        result = []
        for item in self.items:
            result.extend(item.splitlines())
        return result

    def consume_translations(self, translations: list[str], pos: int) -> int:
        total_lines = sum(len(item.splitlines()) for item in self.items)
        self.translated_lines = translations[pos : pos + total_lines]
        return pos + total_lines

    def to_markdown(self, ctx: RenderContext) -> str:
        if self.translated_lines is None:
            raise ValueError("Cannot render markdown without translations. Call set_texts() first.")

        # Reconstruct items from flattened translated lines using original item line counts
        result_parts = []
        pos = 0
        for item in self.items:
            count = len(item.splitlines())
            item_lines_raw = self.translated_lines[pos : pos + count]
            pos += count
            if not _has_non_compressed_line(item_lines_raw):
                continue
            item_lines = _drop_compressed_lines(item_lines_raw)

            # Join lines back together, escape the whole item, then add list formatting
            item_text = "\n".join(item_lines)
            escaped = clean_llm_output(item_text, strip_artifacts=ctx.strip_llm_artifacts)

            # First line gets "- ", continuation lines get "  " indent for proper markdown list
            lines = escaped.splitlines()
            formatted_lines = []
            for i, line in enumerate(lines):
                if i == 0:
                    formatted_lines.append(f"- {line}")
                else:
                    formatted_lines.append(f"  {line}")
            result_parts.append("\n".join(formatted_lines))

        return "\n".join(result_parts)

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        if not isinstance(other, ListItem):
            return False
        if self.continues_to_next and other.continues_from_previous:
            if self.translated_lines and other.translated_lines:
                self.translated_lines.extend(other.translated_lines)
            self.items.extend(other.items)
            self.continues_to_next = other.continues_to_next
            return True
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        # Reconstruct items from translated_lines if available
        if self.translated_lines:
            items = []
            pos = 0
            for item in self.items:
                count = len(item.splitlines())
                translated_item_lines = _decoded_lines(self.translated_lines[pos : pos + count]) or []
                items.append("\n".join(translated_item_lines))
                pos += count
        else:
            items = self.items

        result: dict[str, Any] = {"type": "list", "items": items}
        if self.continues_from_previous:
            result["continues_from_previous"] = True
        if self.continues_to_next:
            result["continues_to_next"] = True
        return result


@dataclass
class ImageItem(OCRItem):
    bbox: BoundingBox
    caption: str | None = None
    embedded_text: str | None = None
    continues_from_previous: bool = False
    continues_to_next: bool = False
    translated_lines: list[str] | None = None
    embedded_translated_lines: list[str] | None = None
    image_bytes: bytes | None = None
    reembedded_image_bytes: bytes | None = None

    def get_texts(self) -> list[str]:
        result: list[str] = []
        if self.embedded_text:
            result.extend(self.embedded_text.splitlines())
        if self.caption:
            result.extend(self.caption.splitlines())
        return result

    def consume_translations(self, translations: list[str], pos: int) -> int:
        if self.embedded_text:
            size = len(self.embedded_text.splitlines())
            self.embedded_translated_lines = translations[pos : pos + size]
            pos += size
        if self.caption:
            size = len(self.caption.splitlines())
            self.translated_lines = translations[pos : pos + size]
            pos += size
        return pos

    def to_markdown(self, ctx: RenderContext) -> str:
        # Check if we have translatable content but no translations
        if self.caption and self.translated_lines is None:
            raise ValueError("Cannot render markdown without translations. Call set_texts() first.")

        # Default export prefers reembedded images, but some export flows keep the original asset bytes.
        if ctx.use_original_images or self.reembedded_image_bytes is None:
            image_data = self.image_bytes
        else:
            image_data = self.reembedded_image_bytes

        if not ctx.image_dir or image_data is None:
            raise Exception("Image not found. This is a bug. Please report it.")

        img_name = f"ocr_{uuid4().hex}.png"
        img_path = Path(ctx.image_dir) / img_name
        img_path.write_bytes(image_data)

        # Build caption from translated lines if they exist
        escaped_caption = ""
        if self.translated_lines is not None and _has_non_compressed_line(self.translated_lines):
            translated_lines = _drop_compressed_lines(self.translated_lines)
            escaped_caption = "<br/>".join(
                clean_llm_output(line, strip_artifacts=ctx.strip_llm_artifacts) for line in translated_lines
            )

        return f"![{escaped_caption}]({str(img_path)})"

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        return False

    def prepare(self, page: object) -> None:
        if self.bbox is not None:
            source_bytes = getattr(page, "source_image_bytes", None)
            if source_bytes is not None:
                self.image_bytes = self.bbox.crop_from_image(source_bytes)

    def needs_reembedding(self) -> bool:
        """Check if this item has embedded text that needs reembedding."""
        return bool(self.embedded_text and self.embedded_text.strip())

    def get_embedded_translation(self) -> str | None:
        """Get the translated embedded text as a single string."""
        if self.embedded_translated_lines:
            return "\n".join(_decoded_lines(self.embedded_translated_lines) or [])
        return None

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "image",
            "bbox": {"x": self.bbox.x, "y": self.bbox.y, "width": self.bbox.width, "height": self.bbox.height},
        }
        # Use translated values if available
        if self.embedded_text:
            embedded = (
                "\n".join(_decoded_lines(self.embedded_translated_lines) or [])
                if self.embedded_translated_lines
                else self.embedded_text
            )
            result["embedded_text"] = embedded
        if self.caption:
            caption = "\n".join(_decoded_lines(self.translated_lines) or []) if self.translated_lines else self.caption
            result["caption"] = caption
        if self.continues_from_previous:
            result["continues_from_previous"] = True
        if self.continues_to_next:
            result["continues_to_next"] = True
        return result


@dataclass
class TableItem(OCRItem):
    text: str
    caption: str | None = None
    continues_from_previous: bool = False
    continues_to_next: bool = False
    translated_lines: list[str] | None = None
    translated_caption: list[str] | None = None

    def get_texts(self) -> list[str]:
        res = self.text.splitlines()
        if self.caption:
            res.extend(self.caption.splitlines())
        return res

    def consume_translations(self, translations: list[str], pos: int) -> int:
        size = len(self.text.splitlines())
        self.translated_lines = translations[pos : pos + size]
        pos = pos + size
        if self.caption:
            size = len(self.caption.splitlines())
            self.translated_caption = translations[pos : pos + size]
            pos = pos + size
        return pos

    def to_markdown(self, ctx: RenderContext) -> str:
        if self.translated_lines is None:
            raise ValueError("Cannot render markdown without translations. Call set_texts() first.")
        has_text = _has_non_compressed_line(self.translated_lines)
        has_caption = bool(self.translated_caption and _has_non_compressed_line(self.translated_caption))
        if not has_text and not has_caption:
            return ""
        translated_lines = _drop_compressed_lines(self.translated_lines) if has_text else []
        res = "\n".join(translated_lines)
        if self.translated_caption and _has_non_compressed_line(self.translated_caption):
            translated_caption = _drop_compressed_lines(self.translated_caption)
            escaped_caption = clean_llm_output(
                "  ".join(translated_caption),
                strip_artifacts=ctx.strip_llm_artifacts,
            )
            res += f"\n\nTable: {escaped_caption}"
        return res

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        if not isinstance(other, TableItem):
            return False
        if self.continues_to_next and other.continues_from_previous:
            self.caption = other.caption
            if self.translated_lines and other.translated_lines:
                self.translated_lines.extend(other.translated_lines)
            if other.translated_caption:
                self.translated_caption = other.translated_caption
            self.text += "\n" + other.text
            self.continues_to_next = other.continues_to_next
            return True
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        text = "\n".join(_decoded_lines(self.translated_lines) or []) if self.translated_lines else self.text
        result: dict[str, Any] = {"type": "table", "text": text}
        if self.caption:
            caption = (
                "\n".join(_decoded_lines(self.translated_caption) or []) if self.translated_caption else self.caption
            )
            result["caption"] = caption
        if self.continues_from_previous:
            result["continues_from_previous"] = True
        if self.continues_to_next:
            result["continues_to_next"] = True
        return result


@dataclass
class QuoteItem(OCRItem):
    text: str
    continues_from_previous: bool = False
    continues_to_next: bool = False
    translated_lines: list[str] | None = None

    def get_texts(self) -> list[str]:
        return self.text.splitlines()

    def consume_translations(self, translations: list[str], pos: int) -> int:
        size = len(self.text.splitlines())
        self.translated_lines = translations[pos : pos + size]
        return pos + size

    def to_markdown(self, ctx: RenderContext) -> str:
        if self.translated_lines is None:
            raise ValueError("Cannot render markdown without translations. Call set_texts() first.")
        if not _has_non_compressed_line(self.translated_lines):
            return ""
        translated_lines = _drop_compressed_lines(self.translated_lines)
        joined = "\n".join(translated_lines)
        if not joined and translated_lines:
            # Preserve true empty source lines (not compression markers).
            return "\n"
        escaped_text = clean_llm_output(
            joined,
            strip_artifacts=ctx.strip_llm_artifacts,
        )
        # Each line in a blockquote needs "> " prefix
        lines = escaped_text.splitlines()
        return "\n".join(f"> {line}" for line in lines)

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        if not isinstance(other, QuoteItem):
            return False
        if self.continues_to_next and other.continues_from_previous:
            self.text += other.text
            if self.translated_lines and other.translated_lines:
                self.translated_lines.extend(other.translated_lines)
            self.continues_to_next = other.continues_to_next
            return True
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        text = "\n".join(_decoded_lines(self.translated_lines) or []) if self.translated_lines else self.text
        result: dict[str, Any] = {"type": "quote", "text": text}
        if self.continues_from_previous:
            result["continues_from_previous"] = True
        if self.continues_to_next:
            result["continues_to_next"] = True
        return result


@dataclass
class CoverItem(OCRItem):
    image_bytes: bytes | None = None

    def get_texts(self) -> list[str]:
        return []

    def consume_translations(self, translations: list[str], pos: int) -> int:  # noqa: ARG002
        return pos

    def to_markdown(self, ctx: RenderContext) -> str:
        """Output cover image. First cover becomes YAML frontmatter, others are full-page images."""
        if not ctx.image_dir or self.image_bytes is None:
            return ""
        img_name = f"cover_{uuid4().hex}.png"
        img_path = Path(ctx.image_dir) / img_name
        img_path.write_bytes(self.image_bytes)

        if not ctx.first_cover_rendered:
            # First cover: YAML frontmatter for pandoc epub export
            ctx.first_cover_rendered = True
            return f"---\ncover-image: {img_path}\n---"
        else:
            # Subsequent covers: render as full-page image with page break
            return f"\\newpage\n\n![Cover]({img_path})"

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        # CoverItem doesn't have serializable content in OCR JSON
        # It's derived from page_type="cover", not from content items
        return {}


@dataclass
class TocItem(OCRItem):
    def get_texts(self) -> list[str]:
        return []

    def consume_translations(self, translations: list[str], pos: int) -> int:  # noqa: ARG002
        return pos

    def to_markdown(self, ctx: RenderContext) -> str:  # noqa: ARG002
        return ""

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        # TocItem doesn't have serializable content in OCR JSON
        return {}


@dataclass
class BlankItem(OCRItem):
    def get_texts(self) -> list[str]:
        return []

    def consume_translations(self, translations: list[str], pos: int) -> int:  # noqa: ARG002
        return pos

    def to_markdown(self, ctx: RenderContext) -> str:  # noqa: ARG002
        return ""

    def merge_continuation(self, other: OCRItem) -> bool:  # noqa: ARG002
        return False

    def prepare(self, page: object) -> None:
        pass

    def to_json(self) -> dict[str, Any]:
        # BlankItem doesn't have serializable content in OCR JSON
        return {}


def ocr_item_from_dict(data: dict[str, object]) -> OCRItem:
    item_type = data.get("type")
    if not isinstance(item_type, str):
        raise ValueError("OCR item missing 'type'")
    try:
        factory = _ITEM_REGISTRY[item_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported OCR item type: {item_type}") from exc
    return factory(data)


def _coerce_str_required(value: object) -> str:
    if isinstance(value, str):
        return value
    raise Exception("Invalid JSON format.")


def _coerce_str_optional(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise Exception("Invalid JSON format.")


def _coerce_list_str_required(value: object) -> list[str]:
    if isinstance(value, list):
        items = cast(list[object], value)
        if all(isinstance(item, str) for item in items):
            return cast(list[str], items)
    raise Exception("Invalid JSON format.")


def _coerce_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    else:
        raise Exception("Invalid JSON format.")


def _coerce_bbox(value: object) -> BoundingBox:
    if isinstance(value, dict):
        return BoundingBox.from_dict(cast(dict[str, object], value))
    raise Exception("Invalid JSON format.")


def _chapter_factory(data: dict[str, object]) -> ChapterItem:
    return ChapterItem(
        text=_coerce_str_required(data.get("text")),
    )


def _section_factory(data: dict[str, object]) -> SectionItem:
    return SectionItem(
        text=_coerce_str_required(data.get("text")),
    )


def _subsection_factory(data: dict[str, object]) -> SubsectionItem:
    return SubsectionItem(
        text=_coerce_str_required(data.get("text")),
    )


def _paragraph_factory(data: dict[str, object]) -> ParagraphItem:
    return ParagraphItem(
        text=_coerce_str_required(data.get("text")),
        continues_from_previous=_coerce_bool(data.get("continues_from_previous"), default=False),
        continues_to_next=_coerce_bool(data.get("continues_to_next"), default=False),
    )


def _list_factory(data: dict[str, object]) -> ListItem:
    items = _coerce_list_str_required(data.get("items"))
    return ListItem(
        items=items,
        continues_from_previous=_coerce_bool(data.get("continues_from_previous"), default=False),
        continues_to_next=_coerce_bool(data.get("continues_to_next"), default=False),
    )


def _image_factory(data: dict[str, object]) -> ImageItem:
    return ImageItem(
        bbox=_coerce_bbox(data.get("bbox")),
        caption=_coerce_str_optional(data.get("caption")),
        embedded_text=_coerce_str_optional(data.get("embedded_text")),
        continues_from_previous=_coerce_bool(data.get("continues_from_previous"), default=False),
        continues_to_next=_coerce_bool(data.get("continues_to_next"), default=False),
    )


def _table_factory(data: dict[str, object]) -> TableItem:
    return TableItem(
        text=_coerce_str_required(data.get("text")),
        caption=_coerce_str_optional(data.get("caption")),
        continues_from_previous=_coerce_bool(data.get("continues_from_previous"), default=False),
        continues_to_next=_coerce_bool(data.get("continues_to_next"), default=False),
    )


def _quote_factory(data: dict[str, object]) -> QuoteItem:
    return QuoteItem(
        text=_coerce_str_required(data.get("text")),
        continues_from_previous=_coerce_bool(data.get("continues_from_previous"), default=False),
        continues_to_next=_coerce_bool(data.get("continues_to_next"), default=False),
    )


def _cover_factory(_: dict[str, object]) -> CoverItem:
    return CoverItem()


def _toc_factory(_: dict[str, object]) -> TocItem:
    return TocItem()


def _blank_factory(_: dict[str, object]) -> BlankItem:
    return BlankItem()


_ITEM_REGISTRY: dict[str, Callable[[dict[str, object]], OCRItem]] = {
    "chapter": _chapter_factory,
    "section": _section_factory,
    "subsection": _subsection_factory,
    "paragraph": _paragraph_factory,
    "list": _list_factory,
    "image": _image_factory,
    "table": _table_factory,
    "quote": _quote_factory,
    "cover": _cover_factory,
    "toc": _toc_factory,
    "blank": _blank_factory,
}
