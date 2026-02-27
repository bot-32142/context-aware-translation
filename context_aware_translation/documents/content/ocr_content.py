from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from context_aware_translation.documents.content.ocr_items import (
    BlankItem,
    CoverItem,
    OCRItem,
    RenderContext,
    TocItem,
    ocr_item_from_dict,
)

logger = logging.getLogger(__name__)


class SinglePageOCRContent:
    """OCR content for a single page without cross-page merging.

    Used for editing OCR text in the review view where we need to:
    1. Extract texts from a single page's OCR JSON
    2. Update texts in place
    3. Serialize back to OCR JSON format
    """

    def __init__(self, page_type: str, items: list[OCRItem]):
        self.page_type = page_type
        self.items = items

    @classmethod
    def from_ocr_json(cls, ocr_data: list[dict]) -> SinglePageOCRContent:
        """Create from raw OCR JSON (list of page dicts).

        Args:
            ocr_data: List of page dicts from OCR (typically just one page)

        Returns:
            SinglePageOCRContent with parsed items (no merging)
        """
        all_items: list[OCRItem] = []
        page_type = "content"

        for page_dict in ocr_data:
            page_type, items = parse_ocr_json(page_dict, None)
            all_items.extend(items)

        return cls(page_type=page_type, items=all_items)

    def get_texts(self) -> list[str]:
        """Extract all translatable texts in order."""
        texts: list[str] = []
        for item in self.items:
            texts.extend(item.get_texts())
        return texts

    def set_texts(self, new_texts: list[str]) -> None:
        """Update texts using consume_translations.

        Args:
            new_texts: List of new text values in same order as get_texts()

        Raises:
            ValueError: If text count doesn't match
        """
        expected = sum(len(item.get_texts()) for item in self.items)
        if len(new_texts) != expected:
            raise ValueError(f"Expected {expected} texts, got {len(new_texts)}")

        pos = 0
        for item in self.items:
            pos = item.consume_translations(new_texts, pos)

    def to_json(self) -> list[dict]:
        """Serialize back to OCR JSON format.

        Returns:
            List containing a single page dict with updated content
        """
        content = [item.to_json() for item in self.items if item.to_json()]
        return [
            {
                "page_type": self.page_type,
                "content": content,
            }
        ]


def parse_ocr_json(
    data: dict[str, Any],
    source_image_bytes: bytes | None,
) -> tuple[str, list[OCRItem]]:
    """Parse OCR API response JSON into (page_type, items) tuple.

    Extracts page type and content items from raw OCR JSON, handling special page types
    (cover, toc, blank) and regular content pages.

    Args:
        data: Raw OCR API response dictionary
        source_image_bytes: Optional image bytes for special page types
        page_number: Page number (tracked by caller, not returned)

    Returns:
        Tuple of (page_type, items_list) where:
        - page_type: str ("cover", "toc", "blank", or "content")
        - items_list: list[OCRItem] containing parsed content

    Raises:
        ValueError: If JSON structure is invalid (missing page_type, invalid content, etc.)
    """
    # Validate and extract page_type
    page_type = data.get("page_type")
    if page_type is None:
        raise ValueError("Missing required field: 'page_type'")
    if not isinstance(page_type, str):
        raise ValueError(f"Invalid page_type: expected str, got {type(page_type).__name__}")

    content_data = data.get("content", [])

    # Parse items based on page type
    items: list[OCRItem]
    if page_type == "cover":
        items = [CoverItem(image_bytes=source_image_bytes)] if source_image_bytes else []
    elif page_type == "toc":
        items = [TocItem()] if source_image_bytes else []
    elif page_type == "blank":
        items = [BlankItem()] if source_image_bytes else []
    elif page_type == "content":
        # Validate content field for content pages
        if not isinstance(content_data, list):
            raise ValueError(f"Invalid content: expected list, got {type(content_data).__name__}")
        items = [ocr_item_from_dict(item) for item in content_data]
    else:
        # Unknown page type defaults to content parsing
        if not isinstance(content_data, list):
            raise ValueError(f"Invalid content: expected list, got {type(content_data).__name__}")
        items = [ocr_item_from_dict(item) for item in content_data]

    return (page_type, items)


@dataclass
class MergedOCRContent:
    elements: list[OCRItem]

    def get_texts(self) -> list[str]:
        result: list[str] = []
        for elem in self.elements:
            result.extend(elem.get_texts())
        return result

    def set_texts(self, translations: list[str]) -> int:
        expected = sum(len(element.get_texts()) for element in self.elements)
        if len(translations) != expected:
            raise ValueError(f"Expected {expected} translations, got {len(translations)}")

        pos = 0
        for element in self.elements:
            pos = element.consume_translations(translations, pos)
        return pos

    def to_markdown(
        self,
        image_dir: Path,
        insert_new_page_before_chapter: bool = False,
        strip_llm_artifacts: bool = True,
    ) -> str:
        lines: list[str] = []
        ctx = RenderContext(
            image_dir=image_dir,
            insert_new_page_before_chapter=insert_new_page_before_chapter,
            strip_llm_artifacts=strip_llm_artifacts,
        )

        for elem in self.elements:
            chunk = elem.to_markdown(ctx)
            if not chunk:
                continue
            lines.extend(part for part in chunk.split("\n\n") if part)

        return "\n\n".join(lines)

    @classmethod
    def from_raw_ocr(cls, pages: list[tuple[list[dict], bytes | None]]) -> MergedOCRContent:
        """Create MergedOCRContent from raw OCR JSON data.

        Args:
            pages: List of (page_list, source_image_bytes) tuples.
                   page_list is a list of page dicts from OCR.

        Returns:
            MergedOCRContent with merged cross-page continuations.
        """
        elements: list[OCRItem] = []
        pending: OCRItem | None = None

        for page_list, img_bytes in pages:
            for page_json in page_list:
                _, items = parse_ocr_json(page_json, img_bytes)
                page_context = SimpleNamespace(source_image_bytes=img_bytes)

                for item in items:
                    item.prepare(page_context)

                    if pending and pending.merge_continuation(item):
                        continue

                    if pending:
                        elements.append(pending)
                    pending = item

        if pending:
            elements.append(pending)

        return cls(elements=elements)
