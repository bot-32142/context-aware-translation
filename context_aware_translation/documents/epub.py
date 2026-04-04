"""EPUB document type for the context-aware translation pipeline.

Supports importing EPUB files, extracting text from XHTML chapters,
running OCR on embedded images, translating content, and exporting
to EPUB (structure-preserving member patching) or selected pandoc-converted
formats (md/docx/html).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import posixpath
import re
import xml.etree.ElementTree as _ET
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import unquote

import defusedxml.ElementTree as DefusedET

from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import Document
from context_aware_translation.documents.epub_container import (
    EpubItem,
    TocEntry,
    patch_epub_members,
    read_epub,
)
from context_aware_translation.documents.epub_support.container_model import DC_NS, OPF_NS
from context_aware_translation.documents.epub_support.nav_ops import (
    apply_nav_label_specs_to_document,
    apply_translated_toc_to_resources,
    deserialize_nav_label_specs,
    extract_nav_label_specs,
    replace_element_text_preserving_slots,
)
from context_aware_translation.documents.epub_support.slot_lines import (
    apply_toc_title_lines,
    consume_slot_texts_from_lines,
    flatten_slot_texts_to_lines,
    flatten_toc_title_lines,
    split_text_to_lines,
)
from context_aware_translation.documents.epub_support.xml_utils import (
    normalize_xml_header_for_utf8,
)
from context_aware_translation.documents.epub_xhtml_utils import (
    extract_heading_texts,
    extract_text_from_xhtml,
    flatten_annotationless_ruby_in_xhtml,
    inject_translations_into_xhtml,
)
from context_aware_translation.llm.epub_ocr import ocr_epub_images
from context_aware_translation.llm.image_generator import build_text_replacements, create_image_generator
from context_aware_translation.ui.constants import LANGUAGES as UI_LANGUAGE_PRESETS
from context_aware_translation.utils.compression_marker import decode_compressed_lines
from context_aware_translation.utils.image_utils import (
    compress_image_for_ocr,
    detect_mime_type,
    validate_image_bytes,
)
from context_aware_translation.utils.pandoc_export import export_pandoc_file

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig, OCRConfig, TranslatorConfig
    from context_aware_translation.llm.client import LLMClient
    from context_aware_translation.storage.repositories.document_repository import DocumentRepository

logger = logging.getLogger(__name__)

METADATA_PATH = "__epub_metadata__.json"
ORIGINAL_ARCHIVE_PATH = "__epub_original__.epub"
NAV_LABEL_SPECS_KEY = "nav_label_specs"
NAV_TRANSLATABLE_TYPES = frozenset({"page-list", "landmarks"})
IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".tiff",
        ".tif",
        ".jp2",
        ".j2k",
        ".jpf",
        ".jpx",
        ".jpm",
    }
)
FONT_EXTENSIONS = frozenset({".otf", ".ttf", ".woff", ".woff2"})
CHAPTER_MIME_TYPES = frozenset({"application/xhtml+xml", "text/html"})
NON_OCR_IMAGE_MIME_TYPES = frozenset({"image/svg+xml"})
XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
XML_DECL_ENCODING_RE = re.compile(rb"^\s*<\?xml[^>]*encoding\s*=\s*['\"]([^'\"]+)['\"]", flags=re.IGNORECASE)
XML_HEADER_RE = re.compile(
    r"((?:\s*<\?xml[^?]*\?>\s*)?(?:\s*<!DOCTYPE[^>]*>\s*)?)",
    flags=re.IGNORECASE | re.DOTALL,
)
CSS_CHARSET_RE = re.compile(r"^(\ufeff?\s*@charset\s+)(['\"])[^'\"]*\2(\s*;)", flags=re.IGNORECASE)
CSS_CHARSET_CAPTURE_RE = re.compile(r"^\ufeff?\s*@charset\s+(['\"])([^'\"]+)\1\s*;", flags=re.IGNORECASE)
BCP47_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
VISIBLE_TOC_FILENAME_RE = re.compile(r"(?:^|[^a-z0-9])(toc|nav|contents)(?:[^a-z0-9]|$)")
VISIBLE_TOC_HEADING_HINTS = frozenset({"contents", "table of contents", "toc", "目次", "目录", "目錄"})
HORIZONTAL_LTR_EXPORT_STYLE_ID = "cat-horizontal-ltr-export"
HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE = "data-cat-horizontal-ltr-toc"
HORIZONTAL_LTR_EXPORT_STYLESHEET = (
    f"/* {HORIZONTAL_LTR_EXPORT_STYLE_ID} */\n"
    "html, body {\n"
    "  direction: ltr !important;\n"
    "  writing-mode: horizontal-tb !important;\n"
    "  -epub-writing-mode: horizontal-tb !important;\n"
    "  -webkit-writing-mode: horizontal-tb !important;\n"
    "  text-orientation: mixed !important;\n"
    "  -epub-text-orientation: mixed !important;\n"
    "  -webkit-text-orientation: mixed !important;\n"
    "}\n"
    "body, body * {\n"
    "  direction: inherit !important;\n"
    "  writing-mode: inherit !important;\n"
    "  -epub-writing-mode: inherit !important;\n"
    "  -webkit-writing-mode: inherit !important;\n"
    "  text-orientation: mixed !important;\n"
    "  -epub-text-orientation: mixed !important;\n"
    "  -webkit-text-orientation: mixed !important;\n"
    "}\n"
    "nav ol, nav ul {\n"
    "  margin: 0 !important;\n"
    "  padding: 0 0 0 1.25em !important;\n"
    "}\n"
    "nav li {\n"
    "  display: block !important;\n"
    "  list-style: none !important;\n"
    "  margin: 0 0 0.75em !important;\n"
    "  padding: 0 !important;\n"
    "}\n"
    "nav a, nav span {\n"
    "  display: block !important;\n"
    "  margin: 0 !important;\n"
    "  padding: 0 !important;\n"
    "}\n"
    "h1, h2, h3, h4, h5, h6,\n"
    "nav, nav * {\n"
    "  width: auto !important;\n"
    "  height: auto !important;\n"
    "  inline-size: auto !important;\n"
    "  block-size: auto !important;\n"
    "  max-width: none !important;\n"
    "  max-height: none !important;\n"
    "  min-width: 0 !important;\n"
    "  min-height: 0 !important;\n"
    "  overflow: visible !important;\n"
    "  position: static !important;\n"
    "  inset: auto !important;\n"
    "  left: auto !important;\n"
    "  right: auto !important;\n"
    "  top: auto !important;\n"
    "  bottom: auto !important;\n"
    "  float: none !important;\n"
    "  clear: none !important;\n"
    "  transform: none !important;\n"
    "  clip: auto !important;\n"
    "  clip-path: none !important;\n"
    "  text-indent: 0 !important;\n"
    "  white-space: normal !important;\n"
    "  line-height: 1.4 !important;\n"
    "}\n"
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] div,\n'
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] p,\n'
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] a,\n'
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] span {{\n'
    "  width: auto !important;\n"
    "  height: auto !important;\n"
    "  inline-size: auto !important;\n"
    "  block-size: auto !important;\n"
    "  max-width: none !important;\n"
    "  max-height: none !important;\n"
    "  min-width: 0 !important;\n"
    "  min-height: 0 !important;\n"
    "  overflow: visible !important;\n"
    "  position: static !important;\n"
    "  inset: auto !important;\n"
    "  left: auto !important;\n"
    "  right: auto !important;\n"
    "  top: auto !important;\n"
    "  bottom: auto !important;\n"
    "  float: none !important;\n"
    "  clear: none !important;\n"
    "  transform: none !important;\n"
    "  clip: auto !important;\n"
    "  clip-path: none !important;\n"
    "  margin-left: 0 !important;\n"
    "  margin-right: 0 !important;\n"
    "  padding-left: 0 !important;\n"
    "  padding-right: 0 !important;\n"
    "  text-indent: 0 !important;\n"
    "  white-space: normal !important;\n"
    "}\n"
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] div,\n'
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] p,\n'
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] a {{\n'
    "  padding-top: 0 !important;\n"
    "  padding-bottom: 0 !important;\n"
    "}\n"
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] div {{\n'
    "  margin-top: 1.25em !important;\n"
    "  margin-bottom: 0 !important;\n"
    "}\n"
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] p {{\n'
    "  margin-bottom: 0.75em !important;\n"
    "}\n"
    f'body[{HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE}="1"] a {{\n'
    "  display: block !important;\n"
    "}\n"
)
HORIZONTAL_LTR_EXPORT_SVG_STYLESHEET = (
    f"/* {HORIZONTAL_LTR_EXPORT_STYLE_ID} */\n"
    "svg, svg * {\n"
    "  direction: ltr !important;\n"
    "  writing-mode: horizontal-tb !important;\n"
    "  -epub-writing-mode: horizontal-tb !important;\n"
    "  -webkit-writing-mode: horizontal-tb !important;\n"
    "  text-orientation: mixed !important;\n"
    "  -epub-text-orientation: mixed !important;\n"
    "  -webkit-text-orientation: mixed !important;\n"
    "}\n"
)
TARGET_LANGUAGE_TO_BCP47 = {
    "简体中文": "zh-Hans",
    "繁体中文": "zh-Hant",
    "西班牙语": "es",
    "英语": "en",
    "印地语": "hi",
    "阿拉伯语": "ar",
    "葡萄牙语": "pt",
    "孟加拉语": "bn",
    "俄语": "ru",
    "日语": "ja",
    "旁遮普语": "pa",
    "马拉地语": "mr",
    "泰卢固语": "te",
    "土耳其语": "tr",
    "泰米尔语": "ta",
    "马来语": "ms",
    "德语": "de",
    "韩语": "ko",
    "法语": "fr",
    "越南语": "vi",
    "乌尔都语": "ur",
    "波斯语": "fa",
    "意大利语": "it",
    "泰语": "th",
    "古吉拉特语": "gu",
    "波兰语": "pl",
    "卡纳达语": "kn",
    "印尼语": "id",
    "马拉雅拉姆语": "ml",
    "乌克兰语": "uk",
    "菲律宾语": "fil",
    "罗马尼亚语": "ro",
    "荷兰语": "nl",
    "斯瓦希里语": "sw",
    "希腊语": "el",
    "匈牙利语": "hu",
    "捷克语": "cs",
    "瑞典语": "sv",
    "保加利亚语": "bg",
    "希伯来语": "he",
    "丹麦语": "da",
    "芬兰语": "fi",
    "克罗地亚语": "hr",
    "斯洛伐克语": "sk",
    "挪威语": "no",
    "立陶宛语": "lt",
    "斯洛文尼亚语": "sl",
    "拉脱维亚语": "lv",
    "爱沙尼亚语": "et",
}


def _canonicalize_language_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().replace("（", "(").replace("）", ")")).casefold()


TARGET_LANGUAGE_LABEL_ALIASES = {
    _canonicalize_language_label(internal_name): internal_name for internal_name in TARGET_LANGUAGE_TO_BCP47
}
TARGET_LANGUAGE_LABEL_ALIASES.update(
    {_canonicalize_language_label(display_name): internal_name for display_name, internal_name in UI_LANGUAGE_PRESETS}
)


class EPUBDocument(Document):
    """Document for EPUB files.

    Stores XHTML chapters as text sources, images as image sources,
    and metadata/CSS/fonts as pre-marked sources that the pipeline skips.
    """

    document_type = "epub"
    supported_export_formats: tuple[str, ...] = ("epub", "md", "docx", "html", "txt")
    requires_ocr_config = True
    uses_translator_config = True
    ocr_required_for_translation = False  # EPUB text content is available without OCR
    supports_preserve_structure = False
    supports_multi_export = False
    supports_original_image_export = True

    def __init__(
        self,
        repo: DocumentRepository,
        document_id: int,
        ocr_config: OCRConfig | None = None,
        translator_config: TranslatorConfig | None = None,
    ) -> None:
        super().__init__(repo, document_id)
        self._ocr_config = ocr_config
        self._translator_config = translator_config
        self._translated_chapters: dict[int, str] = {}  # source_id -> translated XHTML
        self._translated_image_texts: dict[int, str] = {}
        self._translated_resource_images: dict[int, tuple[bytes, str]] = {}
        self._translated_toc: list[TocEntry] | None = None
        self._translated_nav_label_specs: list[dict[str, Any]] | None = None
        self._translated_metadata_title: str | None = None
        self._translation_target_language: str | None = None
        self._force_horizontal_ltr_export = False

    def set_translation_target_language(self, target_language: str | None) -> None:
        """Set target language hint used to update exported OPF dc:language."""
        if isinstance(target_language, str):
            cleaned = target_language.strip()
            self._translation_target_language = cleaned or None
            return
        self._translation_target_language = None

    def set_export_layout_preferences(self, *, force_horizontal_ltr: bool = False) -> None:
        """Set EPUB-specific export layout overrides."""
        self._force_horizontal_ltr_export = bool(force_horizontal_ltr)

    def _should_strip_epub_ruby(self) -> bool:
        """Whether EPUB ruby annotations should be omitted from translation/export text."""
        if self._translator_config is None:
            return True
        return bool(getattr(self._translator_config, "strip_epub_ruby", True))

    # =========================================================================
    # Source classification helpers
    # =========================================================================

    @staticmethod
    def _is_chapter_source(source: dict[str, Any]) -> bool:
        """True if this source is an XHTML chapter (not metadata, CSS, etc.)."""
        rp: str = source.get("relative_path", "")
        mime_type = str(source.get("mime_type", "") or "").lower()
        if source["source_type"] == "text" and rp != METADATA_PATH and mime_type in CHAPTER_MIME_TYPES:
            return True
        return bool(
            source["source_type"] == "text" and rp != METADATA_PATH and rp.endswith((".xhtml", ".html", ".htm"))
        )

    @staticmethod
    def _is_svg_text_source(source: dict[str, Any]) -> bool:
        if source["source_type"] != "text":
            return False
        rp: str = source.get("relative_path", "")
        if rp == METADATA_PATH:
            return False
        mime_type = str(source.get("mime_type", "") or "").lower()
        return mime_type == "image/svg+xml" or rp.lower().endswith(".svg")

    @classmethod
    def _is_slot_translatable_source(cls, source: dict[str, Any]) -> bool:
        return cls._is_chapter_source(source) or cls._is_svg_text_source(source)

    @staticmethod
    def _is_metadata_source(source: dict[str, Any]) -> bool:
        return source.get("relative_path") == METADATA_PATH

    @staticmethod
    def _is_original_archive_source(source: dict[str, Any]) -> bool:
        return source.get("relative_path") == ORIGINAL_ARCHIVE_PATH

    @staticmethod
    def _is_content_image(source: dict[str, Any]) -> bool:
        """True if this is a content image (not a font or other binary resource).

        Identifies content images by checking the file extension on relative_path.
        This is more reliable than checking is_ocr_completed, because after OCR
        completes, content images also have is_ocr_completed=1 (indistinguishable
        from fonts that were pre-marked).
        """
        if source["source_type"] != "image":
            return False
        mime_type = str(source.get("mime_type", "") or "").lower()
        if mime_type.startswith("image/") and mime_type not in NON_OCR_IMAGE_MIME_TYPES:
            return True
        rp = source.get("relative_path", "")
        _, ext = os.path.splitext(rp)
        return ext.lower() in IMAGE_EXTENSIONS

    @staticmethod
    def _is_raster_image_media_type(media_type: str) -> bool:
        mt = media_type.strip().lower()
        return mt.startswith("image/") and mt not in NON_OCR_IMAGE_MIME_TYPES

    @staticmethod
    def _build_epub_image_ocr_payload(embedded_text: str) -> dict[str, str]:
        text = embedded_text if isinstance(embedded_text, str) else str(embedded_text)
        return {"embedded_text": text}

    @staticmethod
    def _extract_embedded_text_from_legacy_ocr(raw_payload: Any) -> str:
        pages: list[dict[str, Any]] = []
        if isinstance(raw_payload, list):
            pages = [page for page in raw_payload if isinstance(page, dict)]
        elif isinstance(raw_payload, dict):
            pages = [raw_payload]
        else:
            return ""

        chunks: list[str] = []
        for page in pages:
            content = page.get("content", [])
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                if str(item.get("type", "")).strip().lower() != "image":
                    continue
                embedded_text = item.get("embedded_text")
                if isinstance(embedded_text, str) and embedded_text.strip():
                    chunks.append(embedded_text)

        return "\n".join(chunks)

    @classmethod
    def _extract_image_embedded_text(cls, source: dict[str, Any]) -> str:
        raw_ocr_json = source.get("ocr_json")
        if not raw_ocr_json:
            return ""

        source_path = str(source.get("relative_path", "unknown"))
        try:
            raw_payload = json.loads(raw_ocr_json)
        except Exception as e:
            raise ValueError(f"Invalid EPUB OCR payload for image '{source_path}': {e}") from e

        if isinstance(raw_payload, dict):
            embedded_text = raw_payload.get("embedded_text")
            if isinstance(embedded_text, str):
                return embedded_text

        return cls._extract_embedded_text_from_legacy_ocr(raw_payload)

    @classmethod
    def _extract_image_embedded_lines(cls, source: dict[str, Any]) -> list[str]:
        embedded_text = cls._extract_image_embedded_text(source)
        if not embedded_text:
            return []
        lines = embedded_text.splitlines()
        return lines if lines else [embedded_text]

    @staticmethod
    def _extract_declared_xml_encoding(payload: bytes) -> str | None:
        match = XML_DECL_ENCODING_RE.search(payload[:512])
        if not match:
            return None
        try:
            return match.group(1).decode("ascii", errors="ignore").strip() or None
        except Exception:
            return None

    @classmethod
    def _decode_xml_payload(cls, payload: bytes, *, resource_path: str, resource_kind: str) -> str:
        """Decode XML/XHTML/SVG payload honoring XML declaration when present."""
        declared_encoding = cls._extract_declared_xml_encoding(payload)
        candidates = ["utf-8"]
        if declared_encoding and declared_encoding.lower() not in {"utf-8", "utf8"}:
            candidates.append(declared_encoding)
        candidates.append("latin-1")

        last_error: UnicodeDecodeError | None = None
        for encoding in candidates:
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError as e:
                last_error = e

        logger.warning(
            "%s %s decode failed with utf-8/declared/latin-1, using replacement fallback",
            resource_kind,
            resource_path,
        )
        if last_error is not None:
            logger.debug("Last decode error for %s: %s", resource_path, last_error)
        return payload.decode("utf-8", errors="replace")

    @staticmethod
    def _normalize_xml_header_for_utf8(text: str) -> str:
        return normalize_xml_header_for_utf8(text)

    @staticmethod
    def _normalize_css_charset_for_utf8(text: str) -> str:
        return CSS_CHARSET_RE.sub(r'\1"utf-8"\3', text, count=1)

    @staticmethod
    def _extract_declared_css_charset(payload: bytes) -> str | None:
        probe = payload[:1024]
        if probe.startswith(b"\xef\xbb\xbf"):
            probe = probe[3:]
        try:
            probe_text = probe.decode("ascii", errors="ignore")
        except Exception:
            return None

        match = CSS_CHARSET_CAPTURE_RE.match(probe_text)
        if not match:
            return None

        charset = match.group(2).strip()
        return charset or None

    @classmethod
    def _decode_css_payload(cls, payload: bytes, *, resource_path: str) -> str:
        """Decode CSS payload honoring leading @charset when present."""
        declared_charset = cls._extract_declared_css_charset(payload)
        candidates = ["utf-8"]
        if declared_charset and declared_charset.lower() not in {"utf-8", "utf8"}:
            candidates.insert(0, declared_charset)
        candidates.append("latin-1")

        seen: set[str] = set()
        last_error: UnicodeDecodeError | None = None
        for encoding in candidates:
            normalized = encoding.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            try:
                return payload.decode(encoding)
            except LookupError:
                logger.warning("CSS '%s' declared unsupported charset '%s'; falling back", resource_path, encoding)
                continue
            except UnicodeDecodeError as e:
                last_error = e
                continue

        logger.warning("CSS %s decode failed with declared/utf-8/latin-1, using replacement fallback", resource_path)
        if last_error is not None:
            logger.debug("Last CSS decode error for %s: %s", resource_path, last_error)
        return payload.decode("utf-8", errors="replace")

    @classmethod
    def _local_tag(cls, tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    @staticmethod
    def _tag_namespace(tag: str) -> str | None:
        if tag.startswith("{") and "}" in tag:
            return tag[1:].split("}", 1)[0]
        return None

    @classmethod
    def _replace_css_property_values(cls, text: str, properties: tuple[str, ...], value: str) -> str:
        updated = text
        for property_name in properties:
            updated = re.sub(
                rf"(?i)({re.escape(property_name)}\s*:\s*)([^;{{}}]+)",
                rf"\1{value}",
                updated,
            )
        return updated

    @classmethod
    def _normalize_layout_css(cls, text: str) -> str:
        updated = cls._replace_css_property_values(
            text,
            ("writing-mode", "-epub-writing-mode", "-webkit-writing-mode"),
            "horizontal-tb",
        )
        updated = cls._replace_css_property_values(updated, ("direction",), "ltr")
        updated = cls._replace_css_property_values(
            updated,
            ("text-orientation", "-epub-text-orientation", "-webkit-text-orientation"),
            "mixed",
        )
        return updated

    @classmethod
    def _ensure_inline_style_property(cls, style: str, property_name: str, value: str) -> str:
        pattern = re.compile(rf"(?i)(^|;)(\s*){re.escape(property_name)}\s*:\s*[^;]+")

        def _repl(match: re.Match[str]) -> str:
            return f"{match.group(1)}{match.group(2)}{property_name}: {value}"

        if pattern.search(style):
            return pattern.sub(_repl, style)

        separator = "" if not style.strip() else ("" if style.rstrip().endswith(";") else ";")
        return f"{style.rstrip()}{separator} {property_name}: {value}".strip()

    @classmethod
    def _normalize_inline_style_for_horizontal_ltr(cls, style: str | None) -> str:
        normalized = cls._normalize_layout_css(style or "")
        for property_name, value in (
            ("direction", "ltr"),
            ("writing-mode", "horizontal-tb"),
            ("-epub-writing-mode", "horizontal-tb"),
            ("-webkit-writing-mode", "horizontal-tb"),
            ("text-orientation", "mixed"),
            ("-epub-text-orientation", "mixed"),
            ("-webkit-text-orientation", "mixed"),
        ):
            normalized = cls._ensure_inline_style_property(normalized, property_name, value)
        return normalized

    @staticmethod
    def _prepend_xml_header_if_needed(original_text: str, serialized_text: str) -> str:
        match = XML_HEADER_RE.match(original_text)
        if match is None:
            return serialized_text
        header = normalize_xml_header_for_utf8(match.group(1))
        if not header:
            return serialized_text
        return f"{header}{serialized_text}"

    @classmethod
    def _find_child_by_local_name(cls, parent: _ET.Element, local_name: str) -> _ET.Element | None:
        for child in list(parent):
            if cls._local_tag(child.tag) == local_name:
                return child
        return None

    @classmethod
    def _force_horizontal_ltr_css(cls, text: str) -> str:
        normalized = cls._normalize_layout_css(text)
        if HORIZONTAL_LTR_EXPORT_STYLE_ID in normalized:
            return normalized
        suffix = "\n" if normalized and not normalized.endswith("\n") else ""
        return f"{normalized}{suffix}\n{HORIZONTAL_LTR_EXPORT_STYLESHEET}"

    @classmethod
    def _force_horizontal_ltr_xml_text(cls, text: str, *, toc_document: bool = False) -> str:
        normalized_input = cls._normalize_xml_header_for_utf8(text)
        root = DefusedET.fromstring(normalized_input.encode("utf-8"))
        root_local_tag = cls._local_tag(root.tag)
        namespace = cls._tag_namespace(root.tag)

        for element in root.iter():
            style = element.get("style")
            if style is not None:
                element.set("style", cls._normalize_inline_style_for_horizontal_ltr(style))
            if element.get("dir") is not None:
                element.set("dir", "ltr")
            if cls._local_tag(element.tag) == "style" and element.text:
                element.text = cls._force_horizontal_ltr_css(element.text)

        if root_local_tag == "html":
            root.set("dir", "ltr")
            root.set("style", cls._normalize_inline_style_for_horizontal_ltr(root.get("style")))
            body = cls._find_child_by_local_name(root, "body")
            if body is not None:
                body.set("dir", "ltr")
                body.set("style", cls._normalize_inline_style_for_horizontal_ltr(body.get("style")))
                if toc_document:
                    body.set(HORIZONTAL_LTR_EXPORT_TOC_ATTRIBUTE, "1")
            head = cls._find_child_by_local_name(root, "head")
            if head is None:
                head_tag = f"{{{namespace}}}head" if namespace else "head"
                head = _ET.Element(head_tag)
                body = cls._find_child_by_local_name(root, "body")
                insert_at = list(root).index(body) if body is not None else 0
                root.insert(insert_at, head)
            style_tag = f"{{{namespace}}}style" if namespace else "style"
            override = next(
                (
                    child
                    for child in list(head)
                    if cls._local_tag(child.tag) == "style" and child.get("id") == HORIZONTAL_LTR_EXPORT_STYLE_ID
                ),
                None,
            )
            if override is None:
                override = _ET.SubElement(head, style_tag)
            override.set("id", HORIZONTAL_LTR_EXPORT_STYLE_ID)
            override.set("type", "text/css")
            override.text = HORIZONTAL_LTR_EXPORT_STYLESHEET
        elif root_local_tag == "svg":
            root.set("style", cls._normalize_inline_style_for_horizontal_ltr(root.get("style")))
            style_tag = f"{{{namespace}}}style" if namespace else "style"
            override = next(
                (
                    child
                    for child in list(root)
                    if cls._local_tag(child.tag) == "style" and child.get("id") == HORIZONTAL_LTR_EXPORT_STYLE_ID
                ),
                None,
            )
            if override is None:
                override = _ET.Element(style_tag)
                root.insert(0, override)
            override.set("id", HORIZONTAL_LTR_EXPORT_STYLE_ID)
            override.set("type", "text/css")
            override.text = HORIZONTAL_LTR_EXPORT_SVG_STYLESHEET

        serialized = _ET.tostring(root, encoding="unicode")
        return cls._prepend_xml_header_if_needed(normalized_input, serialized)

    @classmethod
    def _normalize_text_source_for_export(
        cls,
        source: dict[str, Any],
        text: str,
        *,
        force_horizontal_ltr: bool = False,
        toc_document: bool = False,
        flatten_annotationless_ruby: bool = False,
    ) -> str:
        mime_type = str(source.get("mime_type", "") or "").strip().lower()
        relative_path = str(source.get("relative_path", "") or "").strip().lower()
        css_like_path = relative_path.endswith(".css")
        xhtml_like_path = relative_path.endswith((".xhtml", ".html", ".htm"))
        xml_like_path = relative_path.endswith((".xhtml", ".html", ".htm", ".svg", ".xml", ".ncx", ".opf"))
        xhtml_like_mime = mime_type in CHAPTER_MIME_TYPES
        xml_like_mime = mime_type in {
            *CHAPTER_MIME_TYPES,
            "image/svg+xml",
            "application/x-dtbncx+xml",
            "application/oebps-package+xml",
            "application/xml",
            "text/xml",
        }

        if force_horizontal_ltr:
            if mime_type == "text/css" or css_like_path:
                text = cls._force_horizontal_ltr_css(text)
            elif xml_like_path or xml_like_mime or text.lstrip().startswith("<?xml"):
                text = cls._force_horizontal_ltr_xml_text(text, toc_document=toc_document)

        if flatten_annotationless_ruby and (xhtml_like_path or xhtml_like_mime):
            text = flatten_annotationless_ruby_in_xhtml(text)

        if mime_type == "text/css" or css_like_path:
            return cls._normalize_css_charset_for_utf8(text)
        if xml_like_path or xml_like_mime or text.lstrip().startswith("<?xml"):
            return cls._normalize_xml_header_for_utf8(text)
        return text

    @classmethod
    def _is_textual_asset_source(cls, source: dict[str, Any]) -> bool:
        mime_type = str(source.get("mime_type", "") or "").strip().lower()
        relative_path = str(source.get("relative_path", "") or "").strip().lower()
        if mime_type == "text/css" or relative_path.endswith(".css"):
            return True
        if relative_path.endswith((".xhtml", ".html", ".htm", ".svg", ".xml", ".ncx", ".opf")):
            return True
        return mime_type in {
            *CHAPTER_MIME_TYPES,
            "image/svg+xml",
            "application/x-dtbncx+xml",
            "application/oebps-package+xml",
            "application/xml",
            "text/xml",
        }

    @classmethod
    def _normalize_asset_payload_for_export(
        cls,
        source: dict[str, Any],
        *,
        force_horizontal_ltr: bool,
        toc_document: bool = False,
    ) -> bytes | None:
        if source["source_type"] != "asset" or not source.get("binary_content"):
            return None
        if not cls._is_textual_asset_source(source):
            return None

        payload = bytes(source["binary_content"])
        mime_type = str(source.get("mime_type", "") or "").strip().lower()
        relative_path = str(source.get("relative_path", "") or "").strip().lower()
        if mime_type == "text/css" or relative_path.endswith(".css"):
            decoded = cls._decode_css_payload(payload, resource_path=str(source.get("relative_path", "")))
        else:
            decoded = cls._decode_xml_payload(
                payload,
                resource_path=str(source.get("relative_path", "")),
                resource_kind="Asset resource",
            )
        normalized = cls._normalize_text_source_for_export(
            source,
            decoded,
            force_horizontal_ltr=force_horizontal_ltr,
            toc_document=toc_document,
        )
        return normalized.encode("utf-8")

    @staticmethod
    def _serialize_toc(entries: list[TocEntry]) -> list[dict[str, Any]]:
        """Serialize nested TOC entries into JSON-safe dictionaries."""
        serialized: list[dict[str, Any]] = []
        for entry in entries:
            record: dict[str, Any] = {"title": entry.title, "href": entry.href}
            if entry.children:
                record["children"] = EPUBDocument._serialize_toc(entry.children)
            serialized.append(record)
        return serialized

    @staticmethod
    def _deserialize_toc(entries: list[dict[str, Any]]) -> list[TocEntry]:
        """Deserialize JSON TOC dictionaries into nested TocEntry objects."""
        toc: list[TocEntry] = []
        for entry in entries:
            children_raw = entry.get("children", [])
            children = EPUBDocument._deserialize_toc(children_raw) if isinstance(children_raw, list) else None
            toc.append(
                TocEntry(
                    title=str(entry.get("title", "")),
                    href=str(entry.get("href", "")),
                    children=children if children else None,
                )
            )
        return toc

    @staticmethod
    def _split_text_to_lines(text: str) -> list[str]:
        return split_text_to_lines(text)

    @classmethod
    def _metadata_title_lines(cls, metadata_json: dict[str, Any]) -> list[str]:
        title = metadata_json.get("title")
        if not isinstance(title, str):
            return []
        if not title.strip():
            return []
        return cls._split_text_to_lines(title)

    @classmethod
    def _consume_metadata_title_lines(
        cls,
        metadata_json: dict[str, Any],
        lines: list[str],
        offset: int,
    ) -> tuple[str | None, int]:
        title_lines = cls._metadata_title_lines(metadata_json)
        if not title_lines:
            return None, offset
        count = len(title_lines)
        translated_title = "\n".join(lines[offset : offset + count])
        return translated_title, offset + count

    @staticmethod
    def _to_bcp47_language_tag(language: str | None) -> str | None:
        if not isinstance(language, str):
            return None
        cleaned = language.strip()
        if not cleaned:
            return None

        alias = TARGET_LANGUAGE_LABEL_ALIASES.get(_canonicalize_language_label(cleaned))
        if alias is not None:
            return TARGET_LANGUAGE_TO_BCP47[alias]

        mapped = TARGET_LANGUAGE_TO_BCP47.get(cleaned)
        if mapped:
            return mapped

        if not BCP47_CODE_RE.fullmatch(cleaned):
            return None

        parts = cleaned.split("-")
        normalized = [parts[0].lower()]
        for part in parts[1:]:
            if len(part) == 4 and part.isalpha():
                normalized.append(part.title())
            elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
                normalized.append(part.upper())
            else:
                normalized.append(part.lower())
        return "-".join(normalized)

    @staticmethod
    def _read_member_payload_from_archive(archive: bytes, member_path: str) -> bytes | None:
        normalized_path = member_path.strip().lstrip("/")
        if not normalized_path:
            return None
        try:
            with zipfile.ZipFile(BytesIO(archive), "r") as zf:
                return zf.read(normalized_path)
        except Exception:
            return None

    @classmethod
    def _patch_opf_metadata_payload(
        cls,
        payload: bytes,
        *,
        translated_title: str | None,
        translated_language_tag: str | None,
        force_horizontal_ltr: bool = False,
    ) -> bytes | None:
        if translated_title is None and translated_language_tag is None and not force_horizontal_ltr:
            return None

        try:
            root = DefusedET.fromstring(payload)
        except Exception:
            return None

        metadata_el = root.find(f"{{{OPF_NS}}}metadata")
        if metadata_el is None:
            return None

        changed = False
        if translated_title is not None:
            title_el = metadata_el.find(f"{{{DC_NS}}}title")
            if title_el is None:
                title_el = _ET.SubElement(metadata_el, f"{{{DC_NS}}}title")
            if (title_el.text or "") != translated_title:
                title_el.text = translated_title
                changed = True

        if translated_language_tag is not None:
            lang_el = metadata_el.find(f"{{{DC_NS}}}language")
            if lang_el is None:
                lang_el = _ET.SubElement(metadata_el, f"{{{DC_NS}}}language")
            if (lang_el.text or "").strip() != translated_language_tag:
                lang_el.text = translated_language_tag
                changed = True

        if force_horizontal_ltr:
            spine_el = root.find(f"{{{OPF_NS}}}spine")
            if spine_el is not None and (spine_el.get("page-progression-direction", "").strip().lower() != "ltr"):
                spine_el.set("page-progression-direction", "ltr")
                changed = True

        if not changed:
            return None

        return cast(bytes, _ET.tostring(root, encoding="utf-8", xml_declaration=True))

    @classmethod
    def _flatten_slot_texts_to_lines(cls, slot_texts: list[str]) -> list[str]:
        return flatten_slot_texts_to_lines(slot_texts)

    @classmethod
    def _consume_slot_texts_from_lines(
        cls,
        slot_templates: list[str],
        lines: list[str],
        offset: int,
    ) -> tuple[list[str], int]:
        return consume_slot_texts_from_lines(slot_templates, lines, offset)

    @classmethod
    def _flatten_toc_title_lines(cls, entries: list[TocEntry]) -> list[str]:
        return flatten_toc_title_lines(entries)

    @classmethod
    def _apply_toc_title_lines(
        cls,
        entries: list[TocEntry],
        lines: list[str],
        offset: int = 0,
    ) -> tuple[list[TocEntry], int]:
        return apply_toc_title_lines(entries, lines, offset)

    @classmethod
    def _extract_nav_label_specs(cls, resources: list[EpubItem]) -> list[dict[str, Any]]:
        return extract_nav_label_specs(
            resources,
            chapter_mime_types=CHAPTER_MIME_TYPES,
            nav_translatable_types=set(NAV_TRANSLATABLE_TYPES),
            xhtml_ns=XHTML_NS,
            epub_ns=EPUB_NS,
        )

    @staticmethod
    def _deserialize_nav_label_specs(entries: Any) -> list[dict[str, Any]]:
        return deserialize_nav_label_specs(entries, nav_translatable_types=set(NAV_TRANSLATABLE_TYPES))

    @classmethod
    def _apply_nav_label_specs_to_document(cls, content: bytes, specs: list[dict[str, Any]]) -> bytes | None:
        return apply_nav_label_specs_to_document(content, specs, xhtml_ns=XHTML_NS)

    @staticmethod
    def _apply_translated_toc_to_resources(resources: list[EpubItem], toc: list[TocEntry]) -> None:
        apply_translated_toc_to_resources(
            resources,
            toc,
            chapter_mime_types=set(CHAPTER_MIME_TYPES),
            xhtml_ns=XHTML_NS,
            epub_ns=EPUB_NS,
            ncx_ns=NCX_NS,
        )

    @staticmethod
    def _resolve_resource_href_to_source_path(href: str, base_path: str) -> str:
        """Resolve a local href against another EPUB source path."""
        path = unquote(href.split("#", 1)[0].split("?", 1)[0]).strip()
        if not path:
            return ""
        lower_path = path.lower()
        if path.startswith("//") or lower_path.startswith(("http://", "https://", "mailto:", "javascript:", "data:")):
            return ""

        normalized_base_path = str(base_path or "").strip().lstrip("/")
        base_dir = posixpath.dirname(normalized_base_path)
        if path.startswith("/"):
            resolved = posixpath.normpath(path)
        elif base_dir:
            resolved = posixpath.normpath(posixpath.join(base_dir, path))
        else:
            resolved = posixpath.normpath(path)
        if resolved in {"", "."}:
            return ""
        return resolved.lstrip("/")

    @staticmethod
    def _resolve_toc_href_to_source_path(href: str, package_path: str) -> str:
        """Resolve a TOC entry href to a source relative_path (zip path)."""
        return EPUBDocument._resolve_resource_href_to_source_path(href, package_path)

    @classmethod
    def _resolve_resource_href_to_target(
        cls,
        href: str,
        base_path: str,
    ) -> tuple[str, str]:
        source_path = cls._resolve_resource_href_to_source_path(href, base_path)
        raw_fragment = href.split("#", 1)[1] if "#" in href else ""
        fragment = unquote(raw_fragment).strip()

        if not source_path and fragment:
            source_path = str(base_path or "").strip().lstrip("/")
        if not source_path:
            return "", ""
        if not fragment:
            return source_path, source_path
        return source_path, f"{source_path}#{fragment}"

    @classmethod
    def _extract_visible_toc_document_paths(cls, metadata_json: dict[str, Any]) -> set[str]:
        package_path = str(metadata_json.get("package_path", "") or "").strip().lstrip("/")
        guide_xml = str(metadata_json.get("guide_xml", "") or "").strip()
        if not package_path or not guide_xml:
            return set()

        try:
            guide_root = DefusedET.fromstring(guide_xml.encode("utf-8"))
        except Exception:
            return set()

        toc_paths: set[str] = set()
        for reference in guide_root.iter():
            if cls._local_tag(reference.tag) != "reference":
                continue
            if str(reference.get("type", "") or "").strip().lower() != "toc":
                continue
            href = str(reference.get("href", "") or "").strip()
            if not href:
                continue
            resolved = cls._resolve_toc_href_to_source_path(href, package_path)
            if resolved:
                toc_paths.add(resolved)
        return toc_paths

    @classmethod
    def _looks_like_visible_toc_document(cls, text: str, *, relative_path: str = "") -> bool:
        try:
            normalized_input = cls._normalize_xml_header_for_utf8(text)
            root = DefusedET.fromstring(normalized_input.encode("utf-8"))
        except Exception:
            return False

        if cls._local_tag(root.tag) != "html":
            return False

        body = cls._find_child_by_local_name(root, "body")
        if body is None:
            return False

        anchor_count = 0
        anchor_text_length = 0
        has_nav = False
        heading_matches_toc = False
        for element in body.iter():
            local_tag = cls._local_tag(element.tag)
            if local_tag == "nav":
                has_nav = True
            elif local_tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                heading_text = cls._normalize_whitespace("".join(element.itertext())).casefold()
                if heading_text in VISIBLE_TOC_HEADING_HINTS:
                    heading_matches_toc = True

            if local_tag != "a":
                continue
            href = str(element.get("href", "") or "").strip()
            if not href or href.startswith(("http://", "https://", "mailto:", "javascript:", "#")):
                continue
            anchor_count += 1
            anchor_text_length += len(cls._normalize_whitespace("".join(element.itertext())))

        if anchor_count < 3:
            return False

        total_text_length = len(cls._normalize_whitespace(" ".join(body.itertext())))
        if total_text_length == 0:
            return False

        if anchor_text_length / total_text_length < 0.6:
            return False

        base_name = posixpath.splitext(posixpath.basename(relative_path.strip().lstrip("/")))[0].casefold()
        basename_looks_like_toc = "tableofcontents" in base_name or bool(VISIBLE_TOC_FILENAME_RE.search(base_name))
        return has_nav or heading_matches_toc or basename_looks_like_toc

    @classmethod
    def _infer_visible_toc_document_paths(cls, sources_sorted: list[dict[str, Any]]) -> set[str]:
        inferred_paths: set[str] = set()
        for source in sources_sorted:
            if not cls._is_chapter_source(source):
                continue
            relative_path = str(source.get("relative_path", "") or "").strip().lstrip("/")
            if not relative_path:
                continue
            text_content = source.get("text_content")
            if not isinstance(text_content, str) or not text_content.strip():
                continue
            if cls._looks_like_visible_toc_document(text_content, relative_path=relative_path):
                inferred_paths.add(relative_path)
        return inferred_paths

    @classmethod
    def _build_heading_translation_map(
        cls,
        sources_sorted: list[dict[str, Any]],
        translated_chapters: dict[int, str],
    ) -> dict[str, list[tuple[str, str]]]:
        """Build mapping: relative_path -> [(original_heading, translated_heading), ...].

        Only chapters where both original and translated XHTML produce the same
        number of headings are included (DOM structure is preserved by the
        injection step, so this should always hold).
        """
        heading_map: dict[str, list[tuple[str, str]]] = {}
        for source in sources_sorted:
            if not cls._is_chapter_source(source):
                continue
            rp = source.get("relative_path", "")
            if not rp:
                continue
            translated_xhtml = translated_chapters.get(source["source_id"])
            if translated_xhtml is None:
                continue
            orig_headings = extract_heading_texts(source["text_content"])
            trans_headings = extract_heading_texts(translated_xhtml)
            if orig_headings and len(orig_headings) == len(trans_headings):
                heading_map[rp] = list(zip(orig_headings, trans_headings, strict=True))
        return heading_map

    @classmethod
    def _extract_linked_image_source_paths(cls, source: dict[str, Any]) -> list[str]:
        text_content = source.get("text_content")
        if not isinstance(text_content, str) or not text_content.strip():
            return []

        try:
            root = DefusedET.fromstring(cls._normalize_xml_header_for_utf8(text_content).encode("utf-8"))
        except Exception:
            return []

        source_path = str(source.get("relative_path", "") or "").strip().lstrip("/")
        image_paths: list[str] = []
        seen: set[str] = set()
        for element in root.iter():
            if cls._local_tag(element.tag) not in {"img", "image"}:
                continue

            href = ""
            for attr_name in ("src", "href", "{http://www.w3.org/1999/xlink}href"):
                raw_value = element.get(attr_name)
                if raw_value:
                    href = str(raw_value).strip()
                    break
            if not href:
                continue

            resolved = cls._resolve_resource_href_to_source_path(href, source_path)
            if resolved and resolved not in seen:
                seen.add(resolved)
                image_paths.append(resolved)
        return image_paths

    @classmethod
    def _build_image_title_candidate_pairs(
        cls,
        original_lines: list[str],
        translated_lines: list[str],
    ) -> list[tuple[str, str]]:
        original_candidates = [cls._normalize_whitespace(line) for line in original_lines]
        translated_candidates = [cls._normalize_whitespace(line) for line in translated_lines]
        original_candidates = [line for line in original_candidates if line]
        translated_candidates = [line for line in translated_candidates if line]

        limit = min(len(original_candidates), len(translated_candidates), 4)
        if limit == 0:
            return []

        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for count in range(1, limit + 1):
            original_parts = original_candidates[:count]
            translated_parts = translated_candidates[:count]
            for separator in (" ", ""):
                original_title = separator.join(original_parts).strip()
                translated_title = separator.join(translated_parts).strip()
                normalized_original_title = cls._normalize_whitespace(original_title)
                if not original_title or not translated_title or normalized_original_title in seen:
                    continue
                seen.add(normalized_original_title)
                pairs.append((original_title, translated_title))
        return pairs

    @classmethod
    def _build_image_title_translation_map(
        cls,
        sources_sorted: list[dict[str, Any]],
        translated_image_texts: dict[int, str],
    ) -> dict[str, list[tuple[str, str]]]:
        source_by_path = {
            str(source.get("relative_path", "") or "").strip().lstrip("/"): source
            for source in sources_sorted
            if str(source.get("relative_path", "") or "").strip()
        }

        title_map: dict[str, list[tuple[str, str]]] = {}
        for source in sources_sorted:
            if not cls._is_chapter_source(source):
                continue

            relative_path = str(source.get("relative_path", "") or "").strip().lstrip("/")
            if not relative_path:
                continue

            pairs: list[tuple[str, str]] = []
            for image_path in cls._extract_linked_image_source_paths(source):
                image_source = source_by_path.get(image_path)
                if image_source is None or image_source["source_type"] != "image" or not image_source.get("ocr_json"):
                    continue

                translated_text = translated_image_texts.get(image_source["source_id"], "").strip()
                if not translated_text:
                    continue

                pairs.extend(
                    cls._build_image_title_candidate_pairs(
                        cls._extract_image_embedded_lines(image_source),
                        translated_text.splitlines(),
                    )
                )

            if not pairs:
                continue

            deduped_pairs: list[tuple[str, str]] = []
            seen: set[str] = set()
            for original_title, translated_title in pairs:
                normalized_title = cls._normalize_whitespace(original_title)
                if normalized_title in seen:
                    continue
                seen.add(normalized_title)
                deduped_pairs.append((original_title, translated_title))
            if deduped_pairs:
                title_map[relative_path] = deduped_pairs
        return title_map

    @classmethod
    def _merge_title_translation_maps(
        cls,
        *maps: dict[str, list[tuple[str, str]]],
    ) -> dict[str, list[tuple[str, str]]]:
        merged: dict[str, list[tuple[str, str]]] = {}
        for current_map in maps:
            for relative_path, pairs in current_map.items():
                existing = merged.setdefault(relative_path, [])
                seen = {cls._normalize_whitespace(original) for original, _translated in existing}
                for original_title, translated_title in pairs:
                    normalized_title = cls._normalize_whitespace(original_title)
                    if normalized_title in seen:
                        continue
                    existing.append((original_title, translated_title))
                    seen.add(normalized_title)
        return merged

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Collapse runs of whitespace into a single space and strip."""
        return " ".join(text.split())

    @classmethod
    def _sync_toc_with_title_map(
        cls,
        translated_toc: list[TocEntry],
        original_toc: list[TocEntry],
        title_map: dict[str, list[tuple[str, str]]],
        package_path: str,
    ) -> list[TocEntry]:
        """Replace translated TOC titles with synced chapter title translations where originals match.

        For each TOC entry whose original title matches a visible chapter title
        in its target chapter (after whitespace normalisation), the translated
        TOC title is replaced with the corresponding chapter-title translation.
        This keeps TOC labels aligned with both real XHTML headings and
        image-backed title pages without requiring a separate translation pass.
        """
        synced: list[TocEntry] = []
        for translated, original in zip(translated_toc, original_toc, strict=True):
            new_title = translated.title

            source_path = cls._resolve_toc_href_to_source_path(original.href, package_path)
            if source_path and source_path in title_map:
                norm_toc_title = cls._normalize_whitespace(original.title)
                for original_title, translated_title in title_map[source_path]:
                    if cls._normalize_whitespace(original_title) == norm_toc_title:
                        new_title = translated_title
                        break

            new_children = translated.children
            if translated.children and original.children:
                new_children = cls._sync_toc_with_title_map(
                    translated.children,
                    original.children,
                    title_map,
                    package_path,
                )

            synced.append(TocEntry(title=new_title, href=translated.href, children=new_children))
        return synced

    @classmethod
    def _build_toc_title_maps(
        cls,
        toc_entries: list[TocEntry],
        *,
        package_path: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        titles_by_target: dict[str, str] = {}
        unique_titles_by_source_path: dict[str, str] = {}
        duplicate_source_paths: set[str] = set()

        def walk(entries: list[TocEntry]) -> None:
            for entry in entries:
                source_path, target_key = cls._resolve_resource_href_to_target(entry.href, package_path)
                if target_key and target_key not in titles_by_target:
                    titles_by_target[target_key] = entry.title
                if source_path:
                    existing = unique_titles_by_source_path.get(source_path)
                    if existing is None:
                        unique_titles_by_source_path[source_path] = entry.title
                    elif existing != entry.title:
                        duplicate_source_paths.add(source_path)
                if entry.children:
                    walk(entry.children)

        walk(toc_entries)
        for source_path in duplicate_source_paths:
            unique_titles_by_source_path.pop(source_path, None)
        return titles_by_target, unique_titles_by_source_path

    @classmethod
    def _iter_internal_link_targets(
        cls,
        root: _ET.Element,
        *,
        document_path: str,
    ) -> list[tuple[_ET.Element, str, str]]:
        targets: list[tuple[_ET.Element, str, str]] = []
        for element in root.iter():
            if cls._local_tag(element.tag) != "a":
                continue

            href = str(element.get("href", "") or "").strip()
            if not href:
                continue

            source_path, target_key = cls._resolve_resource_href_to_target(href, document_path)
            if not source_path or not target_key:
                continue

            target_text = cls._normalize_whitespace("".join(element.itertext()))
            if not target_text:
                continue

            targets.append((element, source_path, target_key))
        return targets

    @classmethod
    def _sync_visible_toc_document_with_toc_titles(
        cls,
        *,
        translated_xhtml: str,
        document_path: str,
        toc_titles_by_target: dict[str, str],
        toc_titles_by_source_path: dict[str, str],
    ) -> str:
        if not toc_titles_by_target and not toc_titles_by_source_path:
            return translated_xhtml

        try:
            translated_root = DefusedET.fromstring(cls._normalize_xml_header_for_utf8(translated_xhtml).encode("utf-8"))
        except Exception:
            return translated_xhtml

        translated_links = cls._iter_internal_link_targets(translated_root, document_path=document_path)

        changed = False
        for translated_link, source_path, target_key in translated_links:
            translated_title = toc_titles_by_target.get(target_key)
            if translated_title is None:
                translated_title = toc_titles_by_source_path.get(source_path)
            if not translated_title:
                continue
            changed = replace_element_text_preserving_slots(translated_link, translated_title) or changed

        if not changed:
            return translated_xhtml

        serialized = _ET.tostring(translated_root, encoding="unicode")
        return cls._prepend_xml_header_if_needed(translated_xhtml, serialized)

    def _extract_source_slots(self, source: dict[str, Any]) -> list[str]:
        """Extract translatable text slots from XHTML/SVG text sources."""
        source_path = source.get("relative_path", "unknown")
        source_kind = "XHTML chapter" if self._is_chapter_source(source) else "SVG text source"
        try:
            return extract_text_from_xhtml(
                source["text_content"],
                strip_ruby_annotations=self._should_strip_epub_ruby(),
            )
        except Exception as e:
            raise ValueError(f"Invalid {source_kind} '{source_path}': {e}") from e

    # =========================================================================
    # Import
    # =========================================================================

    @classmethod
    def can_import(cls, path: Path) -> bool:
        """Check if path is an importable EPUB file."""
        if not path.exists():
            return False
        return path.is_file() and path.suffix.lower() == ".epub"

    @classmethod
    def do_import(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        """Import an EPUB file into the repository.

        Parses the EPUB, stores XHTML chapters as text sources, images as
        image sources, and metadata/CSS/fonts as pre-marked sources.

        Manages transactions internally (begin/commit/rollback).
        Skips EPUBs that have already been imported (exact archive-byte dedup).

        Args:
            repo: DocumentRepository for database operations.
            path: Path to EPUB file to import.

        Returns:
            Dict with "imported" and "skipped" counts.

        Raises:
            ValueError: If the EPUB file cannot be read.
        """
        raise_if_cancelled(cancel_check)
        try:
            book = read_epub(path)
        except Exception as e:
            raise ValueError(
                f"Failed to read EPUB file '{path.name}': {e}. "
                "The file may be malformed, DRM-protected, or not a valid EPUB."
            ) from e

        original_epub_bytes = path.read_bytes()
        raise_if_cancelled(cancel_check)
        if repo.source_exists_by_binary(original_epub_bytes):
            return {"imported": 0, "skipped": 1}

        # spine_items are already filtered (no nav) and in spine order
        spine_items = book.spine_items

        # Extract metadata for round-trip export and TOC translation support.
        metadata: dict[str, Any] = {
            "title": book.metadata.title,
            "author": book.metadata.authors,
            "language": book.metadata.language,
            "identifier": book.metadata.identifier,
            "spine": [item.item_id for item in spine_items],
            "package_path": book.package_path,
            "metadata_xml": book.metadata_xml,
            "guide_xml": book.guide_xml,
            "bindings_xml": book.bindings_xml,
            "collection_xml": book.collection_xml,
        }

        metadata["toc"] = cls._serialize_toc(book.toc)
        metadata[NAV_LABEL_SPECS_KEY] = cls._extract_nav_label_specs(book.resources)

        repo.begin()
        try:
            raise_if_cancelled(cancel_check)
            document_id = repo.insert_document("epub", auto_commit=False)
            seq = 0

            # Metadata source (sequence 0)
            repo.insert_document_source(
                document_id,
                seq,
                "text",
                relative_path=METADATA_PATH,
                text_content=json.dumps(metadata, ensure_ascii=False),
                is_text_added=True,
                is_ocr_completed=True,
                auto_commit=False,
            )
            seq += 1

            # Preserve original EPUB bytes for structure-preserving export.
            repo.insert_document_source(
                document_id,
                seq,
                "asset",
                relative_path=ORIGINAL_ARCHIVE_PATH,
                binary_content=original_epub_bytes,
                mime_type="application/epub+zip",
                is_text_added=True,
                is_ocr_completed=True,
                auto_commit=False,
            )
            seq += 1

            # XHTML chapters in spine order
            for item in spine_items:
                raise_if_cancelled(cancel_check)
                media_type = item.media_type.strip().lower()
                if media_type in CHAPTER_MIME_TYPES:
                    text_content = cls._decode_xml_payload(
                        item.content,
                        resource_path=item.file_name,
                        resource_kind="Chapter",
                    )

                    # Validate XHTML early so malformed chapters fail import.
                    try:
                        extract_text_from_xhtml(text_content)
                    except Exception as e:
                        raise ValueError(f"Invalid XHTML chapter '{item.file_name}': {e}") from e

                    repo.insert_document_source(
                        document_id,
                        seq,
                        "text",
                        relative_path=item.file_name,
                        text_content=text_content,
                        mime_type=item.media_type,
                        is_ocr_completed=True,  # Not an image
                        auto_commit=False,
                    )
                elif media_type == "image/svg+xml":
                    svg_content = cls._decode_xml_payload(
                        item.content,
                        resource_path=item.file_name,
                        resource_kind="Spine SVG",
                    )
                    repo.insert_document_source(
                        document_id,
                        seq,
                        "text",
                        relative_path=item.file_name,
                        text_content=svg_content,
                        mime_type=item.media_type,
                        is_text_added=False,
                        is_ocr_completed=True,
                        auto_commit=False,
                    )
                elif cls._is_raster_image_media_type(media_type):
                    validate_image_bytes(item.content, source_name=item.file_name)
                    repo.insert_document_source(
                        document_id,
                        seq,
                        "image",
                        relative_path=item.file_name,
                        binary_content=item.content,
                        mime_type=item.media_type,
                        auto_commit=False,
                    )
                else:
                    repo.insert_document_source(
                        document_id,
                        seq,
                        "asset",
                        relative_path=item.file_name,
                        binary_content=item.content,
                        mime_type=item.media_type,
                        is_text_added=True,
                        is_ocr_completed=True,
                        auto_commit=False,
                    )
                seq += 1

            # Resources: CSS, images, fonts, SVGs
            for item in book.resources:
                raise_if_cancelled(cancel_check)
                rp = item.file_name
                mt = item.media_type
                mt_lower = mt.strip().lower()
                item_properties = {token.strip().lower() for token in item.properties.split() if token.strip()}
                _, ext = os.path.splitext(rp)
                ext_lower = ext.lower()

                if (
                    mt_lower in CHAPTER_MIME_TYPES or ext_lower in {".xhtml", ".html", ".htm"}
                ) and "nav" not in item_properties:
                    text_content = cls._decode_xml_payload(
                        item.content,
                        resource_path=rp,
                        resource_kind="Non-spine XHTML",
                    )

                    try:
                        extract_text_from_xhtml(text_content)
                    except Exception as e:
                        raise ValueError(f"Invalid XHTML resource '{rp}': {e}") from e

                    repo.insert_document_source(
                        document_id,
                        seq,
                        "text",
                        relative_path=rp,
                        text_content=text_content,
                        mime_type=mt,
                        is_ocr_completed=True,
                        auto_commit=False,
                    )
                elif mt_lower == "text/css":
                    # CSS file
                    css_content = cls._decode_css_payload(item.content, resource_path=rp)

                    repo.insert_document_source(
                        document_id,
                        seq,
                        "text",
                        relative_path=rp,
                        text_content=css_content,
                        mime_type=mt,
                        is_text_added=True,
                        is_ocr_completed=True,
                        auto_commit=False,
                    )
                elif mt_lower == "image/svg+xml" or ext_lower == ".svg":
                    # SVG file (stored as text)
                    svg_content = cls._decode_xml_payload(
                        item.content,
                        resource_path=rp,
                        resource_kind="Resource SVG",
                    )

                    repo.insert_document_source(
                        document_id,
                        seq,
                        "text",
                        relative_path=rp,
                        text_content=svg_content,
                        mime_type=mt,
                        is_text_added=False,
                        is_ocr_completed=True,
                        auto_commit=False,
                    )
                elif (
                    ext_lower in FONT_EXTENSIONS
                    or mt_lower.startswith("font/")
                    or mt_lower
                    in {
                        "application/font-woff",
                        "application/font-sfnt",
                        "application/vnd.ms-opentype",
                        "application/x-font-opentype",
                        "application/x-font-ttf",
                    }
                ):
                    # Font file: preserve as binary asset, skip OCR/translation
                    repo.insert_document_source(
                        document_id,
                        seq,
                        "asset",
                        relative_path=rp,
                        binary_content=item.content,
                        mime_type=mt,
                        is_text_added=True,
                        is_ocr_completed=True,
                        auto_commit=False,
                    )
                elif cls._is_raster_image_media_type(mt) or ext_lower in IMAGE_EXTENSIONS:
                    # Content image: needs OCR
                    validate_image_bytes(item.content, source_name=rp)
                    repo.insert_document_source(
                        document_id,
                        seq,
                        "image",
                        relative_path=rp,
                        binary_content=item.content,
                        mime_type=mt,
                        auto_commit=False,
                    )
                else:
                    # Other binary resource: preserve, but do not expose as OCR image
                    logger.info(
                        "Skipping OCR for unknown image format: %s (extension: %s)",
                        rp,
                        ext_lower or "(none)",
                    )
                    repo.insert_document_source(
                        document_id,
                        seq,
                        "asset",
                        relative_path=rp,
                        binary_content=item.content,
                        mime_type=mt,
                        is_text_added=True,
                        is_ocr_completed=True,
                        auto_commit=False,
                    )
                seq += 1

            raise_if_cancelled(cancel_check)
            repo.commit()
        except Exception:
            repo.rollback()
            raise

        return {"imported": 1, "skipped": 0}

    # =========================================================================
    # OCR
    # =========================================================================

    def is_ocr_completed(self) -> bool:
        """Check if all image sources have been OCR'd."""
        sources_needing_ocr = self.repo.get_document_sources_needing_ocr(self.document_id)
        return len(sources_needing_ocr) == 0

    async def process_ocr(
        self,
        llm_client: LLMClient,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_item_processed: Callable[[], None] | None = None,
    ) -> int:
        """Run OCR on image resources and store embedded image text.

        Args:
            llm_client: LLM client for OCR processing.
            source_ids: Optional list of source IDs to process. If None, process all.
            cancel_check: Optional cooperative cancellation callback.

        Returns:
            Number of sources processed.
        """
        raise_if_cancelled(cancel_check)
        if self._ocr_config is None:
            raise ValueError("ocr_config is required for process_ocr")

        if source_ids is None:
            sources = self.repo.get_document_sources_needing_ocr(self.document_id)
        else:
            source_ids_set = frozenset(source_ids)
            sources = [
                source
                for source in self.repo.get_document_sources(self.document_id)
                if source["source_type"] == "image" and source["source_id"] in source_ids_set
            ]

        if not sources:
            return 0

        image_data = [
            (
                compress_image_for_ocr(s["binary_content"], self._ocr_config.ocr_dpi),
                s.get("mime_type", "image/png"),
                f"epub_image_{s['sequence_number']}",
            )
            for s in sources
        ]

        def persist_result(index: int, embedded_text: str) -> None:
            raise_if_cancelled(cancel_check)
            payload = self._build_epub_image_ocr_payload(embedded_text)
            self.repo.update_source_ocr(sources[index]["source_id"], json.dumps(payload, ensure_ascii=False))
            self.repo.update_source_ocr_completed(sources[index]["source_id"])
            if on_item_processed is not None:
                on_item_processed()
            raise_if_cancelled(cancel_check)

        if cancel_check is None:
            await ocr_epub_images(
                image_data,
                llm_client,
                self._ocr_config,
                on_result=persist_result,
            )
        else:
            await ocr_epub_images(
                image_data,
                llm_client,
                self._ocr_config,
                on_result=persist_result,
                cancel_check=cancel_check,
            )

        raise_if_cancelled(cancel_check)
        return len(sources)

    # =========================================================================
    # Text extraction / injection
    # =========================================================================

    def get_text(self) -> str:
        """Extract text from XHTML chapters and OCR'd images.

        Returns all chapter text blocks concatenated with newlines,
        followed by OCR text from any processed images.
        """
        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])

        texts: list[str] = []
        for source in sources_sorted:
            if self._is_slot_translatable_source(source):
                slot_texts = self._extract_source_slots(source)
                texts.extend(self._flatten_slot_texts_to_lines(slot_texts))
            elif source["source_type"] == "image" and source.get("ocr_json"):
                texts.extend(self._extract_image_embedded_lines(source))

        metadata_source = next((s for s in sources_sorted if self._is_metadata_source(s)), None)
        nav_label_specs: list[dict[str, Any]] = []
        if metadata_source is not None:
            try:
                metadata_json = json.loads(metadata_source["text_content"])
            except Exception:
                metadata_json = {}
            texts.extend(self._metadata_title_lines(metadata_json))
            toc_entries_json = metadata_json.get("toc", [])
            if isinstance(toc_entries_json, list):
                toc_entries = self._deserialize_toc(toc_entries_json)
                texts.extend(self._flatten_toc_title_lines(toc_entries))
            nav_label_specs = self._deserialize_nav_label_specs(metadata_json.get(NAV_LABEL_SPECS_KEY, []))
            for spec in nav_label_specs:
                texts.extend(self._split_text_to_lines(spec["text"]))

        return "\n".join(texts)

    def is_text_added(self) -> bool:
        """True if ALL sources have is_text_added=1."""
        sources = self.repo.get_document_sources(self.document_id)
        if not sources:
            return True
        return all(s["is_text_added"] == 1 for s in sources)

    def mark_text_added(self) -> None:
        """Mark ALL sources as text added."""
        self.repo.update_all_sources_text_added(self.document_id)

    def _count_total_expected_blocks(
        self,
        sources_sorted: list[dict[str, Any]],
        *,
        metadata_source: dict[str, Any] | None,
    ) -> tuple[int, list[TocEntry], list[dict[str, Any]]]:
        """Count text lines expected from get_text()/set_text() ordering."""
        total_expected_blocks = 0
        for source in sources_sorted:
            if self._is_slot_translatable_source(source):
                slot_texts = self._extract_source_slots(source)
                total_expected_blocks += len(self._flatten_slot_texts_to_lines(slot_texts))
            elif source["source_type"] == "image" and source.get("ocr_json"):
                total_expected_blocks += len(self._extract_image_embedded_lines(source))

        toc_entries: list[TocEntry] = []
        nav_label_specs: list[dict[str, Any]] = []
        if metadata_source is not None:
            try:
                metadata_json = json.loads(metadata_source["text_content"])
            except Exception:
                metadata_json = {}
            total_expected_blocks += len(self._metadata_title_lines(metadata_json))
            toc_entries_json = metadata_json.get("toc", [])
            if isinstance(toc_entries_json, list):
                toc_entries = self._deserialize_toc(toc_entries_json)
                total_expected_blocks += len(self._flatten_toc_title_lines(toc_entries))
            nav_label_specs = self._deserialize_nav_label_specs(metadata_json.get(NAV_LABEL_SPECS_KEY, []))
            total_expected_blocks += sum(len(self._split_text_to_lines(spec["text"])) for spec in nav_label_specs)

        return total_expected_blocks, toc_entries, nav_label_specs

    def set_image_texts_only(self, lines: list[str]) -> int:
        """Populate translated EPUB image OCR text without rebuilding chapter XHTML."""
        sources = self.repo.get_document_sources_without_binary(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])
        metadata_source = next((s for s in sources_sorted if self._is_metadata_source(s)), None)
        total_expected_blocks, _toc_entries, _nav_label_specs = self._count_total_expected_blocks(
            sources_sorted,
            metadata_source=metadata_source,
        )
        if len(lines) != total_expected_blocks:
            raise ValueError(
                f"EPUB image text line count mismatch: expected {total_expected_blocks} "
                f"blocks from XHTML extraction, got {len(lines)} translated lines."
            )

        rendered_lines = decode_compressed_lines(lines)
        self._translated_image_texts.clear()

        cursor = 0
        for source in sources_sorted:
            if self._is_slot_translatable_source(source):
                slot_texts = self._extract_source_slots(source)
                cursor += len(self._flatten_slot_texts_to_lines(slot_texts))
                continue

            if source["source_type"] != "image" or not source.get("ocr_json"):
                continue

            image_lines = self._extract_image_embedded_lines(source)
            num_blocks = len(image_lines)
            if num_blocks == 0:
                continue

            image_translations = rendered_lines[cursor : cursor + num_blocks]
            self._translated_image_texts[source["source_id"]] = "\n".join(image_translations)
            cursor += num_blocks

        return cursor

    async def set_text(
        self,
        lines: list[str],
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,  # noqa: ARG002
    ) -> int:
        """Distribute translated lines back into XHTML chapters.

        Args:
            lines: Translated text lines from the translation pipeline.
                Must match exactly the number of blocks returned by get_text().

        Returns:
            Number of lines consumed from the input.

        Raises:
            ValueError: If len(lines) does not match the expected block count.
        """
        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])
        self._translated_chapters.clear()
        self._translated_image_texts.clear()
        self._translated_resource_images.clear()
        self._translated_toc = None
        self._translated_nav_label_specs = None
        self._translated_metadata_title = None

        metadata_source = next((s for s in sources_sorted if self._is_metadata_source(s)), None)
        total_expected_blocks, toc_entries, nav_label_specs = self._count_total_expected_blocks(
            sources_sorted,
            metadata_source=metadata_source,
        )

        if len(lines) != total_expected_blocks:
            raise ValueError(
                f"EPUB set_text() line count mismatch: expected {total_expected_blocks} "
                f"blocks from XHTML extraction, got {len(lines)} translated lines."
            )
        rendered_lines = decode_compressed_lines(lines)

        # Second pass: inject translations
        cursor = 0
        for source in sources_sorted:
            if self._is_slot_translatable_source(source):
                slot_templates = self._extract_source_slots(source)
                num_lines = len(self._flatten_slot_texts_to_lines(slot_templates))
                if num_lines == 0:
                    continue

                slot_translations, cursor = self._consume_slot_texts_from_lines(slot_templates, rendered_lines, cursor)
                translated_xhtml, _ = inject_translations_into_xhtml(
                    source["text_content"],
                    slot_translations,
                    strip_ruby_annotations=self._should_strip_epub_ruby(),
                )
                self._translated_chapters[source["source_id"]] = translated_xhtml

            elif source["source_type"] == "image" and source.get("ocr_json"):
                image_lines = self._extract_image_embedded_lines(source)
                num_blocks = len(image_lines)
                if num_blocks == 0:
                    continue

                image_translations = rendered_lines[cursor : cursor + num_blocks]
                self._translated_image_texts[source["source_id"]] = "\n".join(image_translations)
                cursor += num_blocks

        if metadata_source is not None:
            try:
                metadata_json = json.loads(metadata_source["text_content"])
            except Exception:
                metadata_json = {}
            translated_title, cursor = self._consume_metadata_title_lines(metadata_json, rendered_lines, cursor)
            if translated_title is not None:
                self._translated_metadata_title = translated_title

        if toc_entries:
            translated_toc, cursor = self._apply_toc_title_lines(toc_entries, rendered_lines, cursor)
            self._translated_toc = translated_toc

        if nav_label_specs:
            translated_specs: list[dict[str, Any]] = []
            for spec in nav_label_specs:
                count = len(self._split_text_to_lines(spec["text"]))
                translated = dict(spec)
                translated["text"] = "\n".join(rendered_lines[cursor : cursor + count])
                translated_specs.append(translated)
                cursor += count
            self._translated_nav_label_specs = translated_specs

        # Load cached reembedded images from DB so export applies them without regeneration
        existing = self.repo.load_reembedded_images(self.document_id)
        for source in sources_sorted:
            if source["source_type"] != "image" or not source.get("binary_content"):
                continue
            source_id = int(source["source_id"])
            if source_id in existing:
                self._translated_resource_images[source_id] = existing[source_id]
            else:
                legacy_idx = source_id * 1_000_000
                if legacy_idx in existing:
                    self._translated_resource_images[source_id] = existing[legacy_idx]

        return cursor

    # =========================================================================
    # Export
    # =========================================================================

    def can_export(self, export_format: str) -> bool:
        """Check if this document can be exported to the given format."""
        return export_format.lower() in self.supported_export_formats

    @classmethod
    def export_merged(
        cls,
        documents: list[Document],
        export_format: str,
        output_path: Path,
        *,
        use_original_images: bool = False,
    ) -> None:
        """Export EPUB documents to file.

        EPUB documents are single-export only (supports_multi_export=False).
        For EPUB output, translated members are patched into the original
        archive while preserving package structure. For non-EPUB formats, the
        native EPUB is first exported to a temporary file, then converted via
        pandoc.

        Args:
            documents: List of EPUBDocument instances with set_text() already called.
            export_format: Output format (e.g., 'epub', 'md', 'docx', 'html', 'txt').
            output_path: Path to write the output file.
        """
        if not documents:
            raise ValueError("No documents to export")
        if len(documents) != 1:
            raise ValueError("EPUB export supports exactly one document at a time")

        fmt = export_format.lower()
        if fmt not in cls.supported_export_formats:
            supported = ", ".join(cls.supported_export_formats)
            raise ValueError(
                f"EPUB documents only support {supported} export formats. "
                f"Requested format '{export_format}' is not supported."
            )
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = documents[0]
        if not isinstance(doc, EPUBDocument):
            raise ValueError("Document must be an EPUBDocument instance")

        if fmt == "epub":
            cls._export_native_epub(doc, output_path, use_original_images=use_original_images)
            return

        with TemporaryDirectory(prefix="cat-epub-export-") as tmp_dir:
            intermediate_epub = Path(tmp_dir) / "intermediate.epub"
            cls._export_native_epub(
                doc,
                intermediate_epub,
                flatten_annotationless_ruby=doc._should_strip_epub_ruby(),
                use_original_images=use_original_images,
            )
            export_pandoc_file(intermediate_epub, output_path, fmt, "epub")

    @classmethod
    def _export_native_epub(
        cls,
        doc: EPUBDocument,
        output_path: Path,
        *,
        flatten_annotationless_ruby: bool = False,
        use_original_images: bool = False,
    ) -> None:
        """Export EPUB by patching translated members into the original archive."""
        sources = doc.repo.get_document_sources(doc.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])
        base_epub = cls._load_original_archive_payload(sources_sorted)
        persisted_reembedded = doc.repo.load_reembedded_images(doc.document_id)
        metadata_source = next((s for s in sources_sorted if cls._is_metadata_source(s)), None)
        if metadata_source is not None:
            try:
                metadata_json = json.loads(metadata_source["text_content"])
            except Exception:
                metadata_json = {}
        else:
            metadata_json = {}

        visible_toc_document_paths = cls._extract_visible_toc_document_paths(metadata_json)
        visible_toc_document_paths.update(cls._infer_visible_toc_document_paths(sources_sorted))

        package_path = str(metadata_json.get("package_path", ""))
        original_toc_json = metadata_json.get("toc", [])
        original_toc: list[TocEntry] = []
        if isinstance(original_toc_json, list) and original_toc_json:
            original_toc = cls._deserialize_toc(original_toc_json)

        title_map: dict[str, list[tuple[str, str]]] = {}
        if doc._translated_chapters or doc._translated_image_texts:
            heading_map = cls._build_heading_translation_map(sources_sorted, doc._translated_chapters)
            image_title_map = cls._build_image_title_translation_map(sources_sorted, doc._translated_image_texts)
            title_map = cls._merge_title_translation_maps(heading_map, image_title_map)

        toc_to_apply = doc._translated_toc
        if doc._translated_toc and original_toc and title_map:
            toc_to_apply = cls._sync_toc_with_title_map(
                doc._translated_toc,
                original_toc,
                title_map,
                package_path,
            )
        toc_titles_by_target, toc_titles_by_source_path = (
            cls._build_toc_title_maps(toc_to_apply, package_path=package_path)
            if toc_to_apply and package_path
            else ({}, {})
        )

        member_updates = cls._collect_member_updates(
            doc,
            sources_sorted,
            persisted_reembedded,
            visible_toc_document_paths=visible_toc_document_paths,
            toc_titles_by_target=toc_titles_by_target,
            toc_titles_by_source_path=toc_titles_by_source_path,
            flatten_annotationless_ruby=flatten_annotationless_ruby,
            use_original_images=use_original_images,
        )

        if doc._translated_toc:
            assert toc_to_apply is not None
            member_updates.update(
                cls._collect_toc_label_updates(
                    sources_sorted=sources_sorted,
                    existing_updates=member_updates,
                    translated_toc=toc_to_apply,
                )
            )
        if doc._translated_nav_label_specs:
            member_updates.update(
                cls._collect_nav_label_updates(
                    sources_sorted=sources_sorted,
                    existing_updates=member_updates,
                    translated_specs=doc._translated_nav_label_specs,
                )
            )

        package_path = str(metadata_json.get("package_path", "")).strip().lstrip("/")
        translated_language_tag = cls._to_bcp47_language_tag(doc._translation_target_language)
        if doc._translation_target_language and translated_language_tag is None:
            logger.warning(
                "Unknown translation target language '%s'; keeping original OPF dc:language",
                doc._translation_target_language,
            )

        if package_path:
            opf_payload = cls._read_member_payload_from_archive(base_epub, package_path)
            if opf_payload is not None:
                patched_opf = cls._patch_opf_metadata_payload(
                    opf_payload,
                    translated_title=doc._translated_metadata_title,
                    translated_language_tag=translated_language_tag,
                    force_horizontal_ltr=doc._force_horizontal_ltr_export,
                )
                if patched_opf is not None:
                    member_updates[package_path] = patched_opf

        output_path.write_bytes(patch_epub_members(base_epub, member_updates))

    @staticmethod
    def _load_original_archive_payload(sources_sorted: list[dict[str, Any]]) -> bytes:
        original_archive = next((s for s in sources_sorted if EPUBDocument._is_original_archive_source(s)), None)
        if original_archive is None or not original_archive.get("binary_content"):
            raise ValueError(
                "Original EPUB archive payload is missing; this document must be re-imported before EPUB export."
            )
        return bytes(original_archive["binary_content"])

    @classmethod
    def _collect_member_updates(
        cls,
        doc: EPUBDocument,
        sources_sorted: list[dict[str, Any]],
        persisted_reembedded: dict[int, tuple[bytes, str]],
        *,
        visible_toc_document_paths: set[str] | None = None,
        toc_titles_by_target: dict[str, str] | None = None,
        toc_titles_by_source_path: dict[str, str] | None = None,
        flatten_annotationless_ruby: bool = False,
        use_original_images: bool = False,
    ) -> dict[str, bytes]:
        updates: dict[str, bytes] = {}
        toc_document_paths = visible_toc_document_paths or set()
        synced_toc_titles_by_target = toc_titles_by_target or {}
        synced_toc_titles_by_source_path = toc_titles_by_source_path or {}
        for source in sources_sorted:
            if cls._is_metadata_source(source) or cls._is_original_archive_source(source):
                continue

            relative_path = str(source.get("relative_path", ""))
            if not relative_path:
                continue
            normalized_relative_path = relative_path.strip().lstrip("/")
            toc_document = normalized_relative_path in toc_document_paths

            if source["source_type"] == "text":
                translated = doc._translated_chapters.get(source["source_id"], source["text_content"])
                if toc_document and (synced_toc_titles_by_target or synced_toc_titles_by_source_path):
                    translated = cls._sync_visible_toc_document_with_toc_titles(
                        translated_xhtml=translated,
                        document_path=normalized_relative_path,
                        toc_titles_by_target=synced_toc_titles_by_target,
                        toc_titles_by_source_path=synced_toc_titles_by_source_path,
                    )
                translated = cls._normalize_text_source_for_export(
                    source,
                    translated,
                    force_horizontal_ltr=doc._force_horizontal_ltr_export,
                    toc_document=toc_document,
                    flatten_annotationless_ruby=flatten_annotationless_ruby,
                )
                updates[relative_path] = translated.encode("utf-8")
                continue

            if source["source_type"] == "asset":
                normalized_asset = cls._normalize_asset_payload_for_export(
                    source,
                    force_horizontal_ltr=doc._force_horizontal_ltr_export,
                    toc_document=toc_document,
                )
                if normalized_asset is not None:
                    updates[relative_path] = normalized_asset
                continue

            if source["source_type"] == "image" and source.get("binary_content"):
                payload = bytes(source["binary_content"])
                if not use_original_images and cls._is_content_image(source):
                    in_memory_translated = doc._translated_resource_images.get(source["source_id"])
                    if in_memory_translated is not None:
                        payload = in_memory_translated[0]
                    else:
                        persisted_translated = cls._compose_source_image_from_persisted_reembeds(
                            source, persisted_reembedded
                        )
                        if persisted_translated is not None:
                            payload = persisted_translated[0]
                updates[relative_path] = payload
        return updates

    @classmethod
    def _collect_toc_label_updates(
        cls,
        *,
        sources_sorted: list[dict[str, Any]],
        existing_updates: dict[str, bytes],
        translated_toc: list[TocEntry],
    ) -> dict[str, bytes]:
        toc_resources: list[EpubItem] = []
        for source in sources_sorted:
            if (
                cls._is_metadata_source(source)
                or cls._is_original_archive_source(source)
                or cls._is_chapter_source(source)
            ):
                continue

            media_type = str(source.get("mime_type", "") or "").strip().lower()
            if media_type not in CHAPTER_MIME_TYPES and media_type != "application/x-dtbncx+xml":
                continue

            relative_path = str(source.get("relative_path", ""))
            if not relative_path:
                continue

            payload = cls._resolve_source_payload_for_relative_path(
                source=source,
                existing_updates=existing_updates,
            )
            if payload is None:
                continue

            toc_resources.append(
                EpubItem(
                    file_name=relative_path,
                    media_type=media_type,
                    content=payload,
                )
            )

        cls._apply_translated_toc_to_resources(toc_resources, translated_toc)
        return {resource.file_name: resource.content for resource in toc_resources}

    @staticmethod
    def _resolve_source_payload_for_relative_path(
        *,
        source: dict[str, Any],
        existing_updates: dict[str, bytes],
    ) -> bytes | None:
        relative_path = str(source.get("relative_path", ""))
        if not relative_path:
            return None
        payload = existing_updates.get(relative_path)
        if payload is not None:
            return payload
        if source["source_type"] == "text":
            return str(source["text_content"]).encode("utf-8")
        if source.get("binary_content"):
            return bytes(source["binary_content"])
        return None

    @classmethod
    def _collect_nav_label_updates(
        cls,
        *,
        sources_sorted: list[dict[str, Any]],
        existing_updates: dict[str, bytes],
        translated_specs: list[dict[str, Any]],
    ) -> dict[str, bytes]:
        specs_by_path: dict[str, list[dict[str, Any]]] = {}
        for spec in translated_specs:
            resource_path = str(spec.get("resource_path", "")).strip()
            if not resource_path:
                continue
            specs_by_path.setdefault(resource_path, []).append(spec)

        if not specs_by_path:
            return {}

        source_by_path = {
            str(source.get("relative_path", "")): source
            for source in sources_sorted
            if str(source.get("relative_path", ""))
        }

        updates: dict[str, bytes] = {}
        for resource_path, specs in specs_by_path.items():
            source = source_by_path.get(resource_path)
            if source is None:
                continue
            payload = cls._resolve_source_payload_for_relative_path(source=source, existing_updates=existing_updates)
            if payload is None:
                continue
            updated_payload = cls._apply_nav_label_specs_to_document(payload, specs)
            if updated_payload is not None:
                updates[resource_path] = updated_payload
        return updates

    def export_preserve_structure(self, output_folder: Path) -> None:
        """Not supported for EPUB documents."""
        raise NotImplementedError("EPUB documents do not support structure-preserving export")

    # =========================================================================
    # Image reembedding
    # =========================================================================

    async def reembed(
        self,
        image_reembedding_config: ImageReembeddingConfig,
        *,
        force: bool = False,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> int:
        """Generate reembedded images for EPUB image sources with translated text.

        Uses existing DB cache to skip already-done items unless force=True.
        Returns count of images newly generated.
        """
        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])

        if source_ids is not None:
            source_ids_set = frozenset(source_ids)
            sources_sorted = [s for s in sources_sorted if s["source_id"] in source_ids_set]

        generator = create_image_generator(image_reembedding_config)
        existing = self.repo.load_reembedded_images(self.document_id) if not force else {}
        semaphore = asyncio.Semaphore(image_reembedding_config.concurrency)

        # Pre-filter sources to count only those that will actually be processed
        sources_to_process = []
        for source in sources_sorted:
            if source["source_type"] != "image" or not source.get("binary_content"):
                continue
            source_id = int(source["source_id"])
            translated_text = self._translated_image_texts.get(source_id, "")
            if not translated_text.strip():
                continue
            if source_id in existing:
                continue
            legacy_idx = source_id * 1_000_000
            if legacy_idx in existing:
                continue
            sources_to_process.append(source)

        total = len(sources_to_process)
        if total == 0:
            return 0

        completed = 0
        progress_lock = asyncio.Lock()

        async def process_source(source: dict[str, Any]) -> None:
            nonlocal completed
            async with semaphore:
                raise_if_cancelled(cancel_check)
                if source["source_type"] != "image" or not source.get("binary_content"):
                    return

                source_id = int(source["source_id"])
                translated_text = self._translated_image_texts.get(source_id, "")
                if not translated_text.strip():
                    return

                if source_id in existing:
                    self._translated_resource_images[source_id] = existing[source_id]
                    return
                legacy_idx = source_id * 1_000_000
                if legacy_idx in existing:
                    self._translated_resource_images[source_id] = existing[legacy_idx]
                    return

                source_bytes = bytes(source["binary_content"])
                mime_type = detect_mime_type(source_bytes)
                original_text = self._extract_image_embedded_text(source)
                text_replacements = build_text_replacements(original_text, translated_text)
                new_bytes = await generator.edit_image(
                    image_bytes=source_bytes,
                    mime_type=mime_type,
                    text_replacements=text_replacements,
                    cancel_check=cancel_check,
                )
                raise_if_cancelled(cancel_check)
                self._translated_resource_images[source_id] = (new_bytes, "image/png")
                self.repo.save_reembedded_image(self.document_id, source_id, new_bytes, "image/png")

                async with progress_lock:
                    completed += 1
                    if progress_callback:
                        progress_callback(
                            ProgressUpdate(
                                step=WorkflowStep.REEMBED,
                                current=completed,
                                total=total,
                                message=f"Reembedding EPUB image {completed}/{total}",
                            )
                        )

        results = await asyncio.gather(*[process_source(source) for source in sources_sorted], return_exceptions=True)
        for source, result in zip(sources_sorted, results, strict=True):
            if isinstance(result, OperationCancelledError):
                raise result
            if isinstance(result, Exception):
                raise RuntimeError(
                    f"Failed to reembed EPUB image source {source.get('source_id', '?')}: {result}"
                ) from result

        return completed

    @classmethod
    def _compose_source_image_from_persisted_reembeds(
        cls,
        source: dict[str, Any],
        persisted_reembedded: dict[int, tuple[bytes, str]],
    ) -> tuple[bytes, str] | None:
        """Fallback for export after reload: load persisted full-image replacement."""
        source_id = source.get("source_id")
        if source_id is None or not source.get("ocr_json"):
            return None
        sid = int(source_id)
        if sid in persisted_reembedded:
            return persisted_reembedded[sid]
        legacy_idx = sid * 1_000_000
        return persisted_reembedded.get(legacy_idx)
