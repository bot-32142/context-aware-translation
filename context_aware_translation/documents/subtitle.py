from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pysubs2

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.progress import ProgressCallback
from context_aware_translation.documents.base import Document
from context_aware_translation.documents.epub_support.inline_markers import MERGED_TOKEN_CLOSE, MERGED_TOKEN_OPEN
from context_aware_translation.utils.compression_marker import decode_compressed_lines

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig
    from context_aware_translation.llm.client import LLMClient
    from context_aware_translation.storage.repositories.document_repository import DocumentRepository


SUBTITLE_EXTENSIONS = frozenset({".srt", ".vtt", ".ass", ".ssa"})
SUBTITLE_FORMATS = ("srt", "vtt", "ass", "ssa")
SUBTITLE_FORMAT_BY_EXTENSION = {f".{fmt}": fmt for fmt in SUBTITLE_FORMATS}

_ASS_FORMATS = frozenset({"ass", "ssa"})
_ASS_LINE_BREAK_RE = re.compile(r"\\[Nn]")
_ASS_OVERRIDE_TAG_RE = re.compile(r"\{[^{}\r\n]*\\[^{}\r\n]*\}")
_ASS_PROTECTED_TAG_RE = re.compile(re.escape(MERGED_TOKEN_OPEN) + r"(/?)ass:(\d+)" + re.escape(MERGED_TOKEN_CLOSE))


class SubtitleDocument(Document):
    """Document for subtitle files with timed-event text translated as a line stream."""

    document_type = "subtitle"
    supported_export_formats = SUBTITLE_FORMATS
    requires_ocr_config = False
    ocr_required_for_translation = False
    supports_preserve_structure = True
    supports_multi_export = False
    supports_original_image_export = False

    def __init__(self, repo: DocumentRepository, document_id: int):
        super().__init__(repo, document_id)
        self._translated_lines: list[str] | None = None

    @classmethod
    def can_import(cls, path: Path) -> bool:
        path = Path(path)
        return path.exists() and path.is_file() and _format_from_path(path) is not None

    @classmethod
    def do_import(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        path = Path(path)
        raise_if_cancelled(cancel_check)
        source_format = _format_from_path(path)
        if source_format is None:
            raise ValueError(f"Unsupported subtitle format: {path.suffix}")

        original_text = path.read_text(encoding="utf-8-sig")
        raise_if_cancelled(cancel_check)
        _load_subtitles(original_text, source_format)

        if repo.source_exists_by_content(original_text):
            return {"imported": 0, "skipped": 1}

        repo.begin()
        try:
            raise_if_cancelled(cancel_check)
            document_id = repo.insert_document(cls.document_type, auto_commit=False)
            repo.insert_document_source(
                document_id,
                0,
                "text",
                relative_path=path.name,
                text_content=original_text,
                mime_type=_mime_type_for_format(source_format),
                is_ocr_completed=True,
                is_text_added=False,
                auto_commit=False,
            )
            raise_if_cancelled(cancel_check)
            repo.commit()
        except Exception:
            repo.rollback()
            raise

        return {"imported": 1, "skipped": 0}

    def is_ocr_completed(self) -> bool:
        return True

    async def process_ocr(
        self,
        llm_client: LLMClient,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_item_processed: Callable[[], None] | None = None,
    ) -> int:
        _ = (llm_client, source_ids, on_item_processed)
        raise_if_cancelled(cancel_check)
        return 0

    def get_text(self) -> str:
        source = self._single_source()
        source_format = _format_from_source(source)
        subs = _load_subtitles(str(source.get("text_content") or ""), source_format)
        cue_texts: list[str] = []
        for event in _translatable_events(subs):
            lines = _event_text_to_stream_lines(event.text, source_format)
            if lines:
                cue_texts.append("\n".join(lines))
        return "\n\n".join(cue_texts)

    def is_text_added(self) -> bool:
        sources = self.repo.get_document_sources(self.document_id)
        if not sources:
            return True
        return all(source["is_text_added"] == 1 for source in sources)

    def mark_text_added(self) -> None:
        self.repo.update_all_sources_text_added(self.document_id)

    async def set_text(
        self,
        lines: list[str],
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> int:
        _ = progress_callback
        raise_if_cancelled(cancel_check)
        self._translated_lines = list(lines)
        return len(lines)

    async def reembed(
        self,
        image_reembedding_config: ImageReembeddingConfig,
        *,
        force: bool = False,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> int:
        _ = (image_reembedding_config, force, source_ids, progress_callback)
        raise_if_cancelled(cancel_check)
        return 0

    def can_export(self, export_format: str) -> bool:
        return export_format.lower().lstrip(".") in self.supported_export_formats

    @classmethod
    def export_merged(
        cls,
        documents: list[Document],
        export_format: str,
        output_path: Path,
        *,
        use_original_images: bool = False,
    ) -> None:
        _ = use_original_images
        if len(documents) != 1:
            raise ValueError("Subtitle export supports one document at a time.")
        document = documents[0]
        if not isinstance(document, SubtitleDocument):
            raise ValueError("All documents must be SubtitleDocument instances.")
        document._export_single(export_format, Path(output_path))

    def export_preserve_structure(self, output_folder: Path) -> None:
        source = self._single_source()
        relative_path = str(source.get("relative_path") or "").strip()
        if not relative_path:
            raise ValueError("Subtitle source does not have an original relative path.")
        source_format = _format_from_source(source)
        output_path = Path(output_folder) / relative_path
        self._export_single(source_format, output_path)

    def _single_source(self) -> dict[str, Any]:
        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda source: int(source.get("sequence_number", 0) or 0))
        if len(sources_sorted) != 1:
            raise ValueError("Subtitle documents must contain exactly one source file.")
        return sources_sorted[0]

    def _export_single(self, export_format: str, output_path: Path) -> None:
        target_format = export_format.lower().lstrip(".")
        if not self.can_export(target_format):
            supported = ", ".join(self.supported_export_formats)
            raise ValueError(f"Format '{export_format}' not supported. Supported: {supported}")
        if self._translated_lines is None:
            raise ValueError("No translated text to export. Call set_text() first.")

        source = self._single_source()
        source_format = _format_from_source(source)
        subs = _load_subtitles(str(source.get("text_content") or ""), source_format)
        self._replace_event_text(subs, source_format)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        subs.save(str(output_path), encoding="utf-8", format_=target_format)

    def _replace_event_text(self, subs: Any, source_format: str) -> None:
        assert self._translated_lines is not None
        translated_lines = decode_compressed_lines(self._translated_lines)
        cursor = 0

        events = _translatable_events(subs)
        for index, event in enumerate(events):
            source_lines, tag_map = _event_text_to_stream_lines_with_tags(event.text, source_format)
            line_count = len(source_lines)
            event_lines = translated_lines[cursor : cursor + line_count]
            if len(event_lines) < line_count:
                raise ValueError(
                    "Translated subtitle line count is shorter than the source subtitle line stream "
                    f"for document {self.document_id}."
                )
            cursor += line_count
            event_lines = [_restore_ass_override_tags(line, tag_map) for line in event_lines]
            event.text = _stream_lines_to_event_text(event_lines)

            if index + 1 < len(events) and cursor < len(translated_lines) and not translated_lines[cursor]:
                cursor += 1

        extra_lines = [line for line in translated_lines[cursor:] if line]
        if extra_lines:
            raise ValueError(
                "Translated subtitle line count is longer than the source subtitle line stream "
                f"for document {self.document_id}."
            )


def _format_from_path(path: Path) -> str | None:
    return SUBTITLE_FORMAT_BY_EXTENSION.get(path.suffix.lower())


def _format_from_source(source: dict[str, Any]) -> str:
    relative_path = str(source.get("relative_path") or "").strip()
    source_format = _format_from_path(Path(relative_path))
    if source_format is None:
        raise ValueError(f"Unsupported subtitle source format: {relative_path}")
    return source_format


def _mime_type_for_format(source_format: str) -> str:
    return {
        "srt": "application/x-subrip",
        "vtt": "text/vtt",
        "ass": "text/x-ass",
        "ssa": "text/x-ssa",
    }[source_format]


def _load_subtitles(text: str, source_format: str) -> Any:
    return pysubs2.SSAFile.from_string(text, format_=source_format)


def _translatable_events(subs: Any) -> list[Any]:
    return [
        event
        for event in subs.events
        if not bool(getattr(event, "is_comment", False)) and _has_displayed_text(str(event.text or ""))
    ]


def _has_displayed_text(text: str) -> bool:
    visible = _ASS_OVERRIDE_TAG_RE.sub("", text)
    visible = _ASS_LINE_BREAK_RE.sub("\n", visible)
    visible = visible.replace("\\h", " ")
    return bool(visible.strip())


def _event_text_to_stream_lines(text: str, source_format: str) -> list[str]:
    lines, _tag_map = _event_text_to_stream_lines_with_tags(text, source_format)
    return lines


def _event_text_to_stream_lines_with_tags(text: str, source_format: str) -> tuple[list[str], dict[int, str]]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    tag_map: dict[int, str] = {}
    if source_format in _ASS_FORMATS:
        normalized, tag_map = _protect_ass_override_tags(normalized)
    normalized = _ASS_LINE_BREAK_RE.sub("\n", normalized)
    normalized = normalized.replace("\\h", " ")
    return normalized.split("\n"), tag_map


def _stream_lines_to_event_text(lines: list[str]) -> str:
    return "\\N".join(lines)


def _protect_ass_override_tags(text: str) -> tuple[str, dict[int, str]]:
    tag_map: dict[int, str] = {}

    def _replace(match: re.Match[str]) -> str:
        tag_id = len(tag_map)
        tag_map[tag_id] = match.group(0)
        return (
            f"{MERGED_TOKEN_OPEN}ass:{tag_id}{MERGED_TOKEN_CLOSE}{MERGED_TOKEN_OPEN}/ass:{tag_id}{MERGED_TOKEN_CLOSE}"
        )

    return _ASS_OVERRIDE_TAG_RE.sub(_replace, text), tag_map


def _restore_ass_override_tags(text: str, tag_map: dict[int, str]) -> str:
    if not tag_map:
        return text

    def _replace(match: re.Match[str]) -> str:
        if match.group(1):
            return ""
        tag_id = int(match.group(2))
        return tag_map.get(tag_id, match.group(0))

    return _ASS_PROTECTED_TAG_RE.sub(_replace, text)
