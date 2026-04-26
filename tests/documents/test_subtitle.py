from __future__ import annotations

import asyncio
from pathlib import Path

import pysubs2

from context_aware_translation.documents.subtitle import SubtitleDocument
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB
from context_aware_translation.utils.compression_marker import COMPRESSED_LINE_SENTINEL

SRT_SOURCE = """1
00:00:01,000 --> 00:00:02,500
Hello
world

2
00:00:03,000 --> 00:00:04,000
Yes.
"""

VTT_SOURCE = """WEBVTT

00:00:01.000 --> 00:00:02.500
Hello
world

00:00:03.000 --> 00:00:04.000
Yes.
"""

ASS_SOURCE = """[Script Info]
Title: Test
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\i1}Hello\\Nworld{\\i0}
Comment: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,Do not translate this comment
Dialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,Yes.
"""

SSA_SOURCE = """[Script Info]
Title: Test SSA
ScriptType: v4.00

[V4 Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,1,2,2,2,10,10,10,0,1

[Events]
Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: Marked=0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello
"""


def _setup_repo(tmp_path: Path) -> DocumentRepository:
    return DocumentRepository(SQLiteBookDB(tmp_path / "book.db"))


def _import_source(tmp_path: Path, filename: str, text: str) -> tuple[DocumentRepository, SubtitleDocument, Path]:
    source_path = tmp_path / filename
    source_path.write_text(text, encoding="utf-8")
    repo = _setup_repo(tmp_path)
    result = SubtitleDocument.do_import(repo, source_path)
    assert result == {"imported": 1, "skipped": 0}
    row = repo.get_document_row()
    assert row is not None
    return repo, SubtitleDocument(repo, int(row["document_id"])), source_path


def test_can_import_supported_subtitle_files(tmp_path: Path) -> None:
    for filename in ("sample.srt", "sample.vtt", "sample.ass", "sample.ssa"):
        path = tmp_path / filename
        path.write_text("subtitle", encoding="utf-8")
        assert SubtitleDocument.can_import(path) is True

    folder = tmp_path / "folder"
    folder.mkdir()
    assert SubtitleDocument.can_import(folder) is False
    assert SubtitleDocument.can_import(tmp_path / "sample.txt") is False


def test_import_srt_stores_original_source_and_line_stream(tmp_path: Path) -> None:
    repo, document, source_path = _import_source(tmp_path, "sample.srt", SRT_SOURCE)

    row = repo.get_document_row()
    assert row is not None
    assert row["document_type"] == "subtitle"

    sources = repo.get_document_sources(int(row["document_id"]))
    assert len(sources) == 1
    assert sources[0]["source_type"] == "text"
    assert sources[0]["relative_path"] == source_path.name
    assert sources[0]["text_content"] == SRT_SOURCE
    assert sources[0]["mime_type"] == "application/x-subrip"
    assert sources[0]["is_ocr_completed"] == 1
    assert sources[0]["is_text_added"] == 0

    assert document.get_text() == "Hello\nworld\n\nYes."


def test_import_vtt_and_export_same_format(tmp_path: Path) -> None:
    _repo, document, _source_path = _import_source(tmp_path, "sample.vtt", VTT_SOURCE)
    assert document.get_text() == "Hello\nworld\n\nYes."

    asyncio.run(document.set_text(["Bonjour", "monde", "", "Oui."]))
    output_path = tmp_path / "translated.vtt"
    SubtitleDocument.export_merged([document], "vtt", output_path)

    exported = output_path.read_text(encoding="utf-8")
    assert exported.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:02.500" in exported
    assert "Bonjour\nmonde" in exported
    assert "Oui." in exported


def test_export_srt_preserves_timing_order_and_replaces_text(tmp_path: Path) -> None:
    _repo, document, _source_path = _import_source(tmp_path, "sample.srt", SRT_SOURCE)

    asyncio.run(document.set_text(["Bonjour", "monde", "", "Oui."]))
    output_path = tmp_path / "translated.srt"
    SubtitleDocument.export_merged([document], "srt", output_path)

    subs = pysubs2.load(str(output_path), format_="srt")
    assert [event.start for event in subs.events] == [1000, 3000]
    assert [event.end for event in subs.events] == [2500, 4000]
    assert [event.text for event in subs.events] == ["Bonjour\\Nmonde", "Oui."]


def test_import_ssa_and_export_ssa(tmp_path: Path) -> None:
    _repo, document, _source_path = _import_source(tmp_path, "sample.ssa", SSA_SOURCE)

    assert document.get_text() == "Hello"
    asyncio.run(document.set_text(["Bonjour"]))
    output_path = tmp_path / "translated.ssa"
    SubtitleDocument.export_merged([document], "ssa", output_path)

    exported = output_path.read_text(encoding="utf-8")
    assert "[V4 Styles]" in exported
    assert "Dialogue: Marked=0,0:00:01.00,0:00:02.00" in exported
    assert "Bonjour" in exported


def test_ass_export_preserves_styles_comments_and_override_tags(tmp_path: Path) -> None:
    _repo, document, _source_path = _import_source(tmp_path, "sample.ass", ASS_SOURCE)

    text_stream = document.get_text()
    assert text_stream == "⟪ass:0⟫⟪/ass:0⟫Hello\nworld⟪ass:1⟫⟪/ass:1⟫\n\nYes."
    translated_lines = text_stream.split("\n")
    translated_lines[0] = "⟪ass:0⟫Bonjour⟪/ass:0⟫"
    translated_lines[1] = translated_lines[1].replace("world", "monde")
    translated_lines[3] = "Oui."

    asyncio.run(document.set_text(translated_lines))
    output_path = tmp_path / "translated.ass"
    SubtitleDocument.export_merged([document], "ass", output_path)

    exported = output_path.read_text(encoding="utf-8")
    assert "[V4+ Styles]" in exported
    assert "Style: Default,Arial,20" in exported
    assert "Comment: 0,0:00:03.00,0:00:04.00" in exported
    assert "{\\i1}Bonjour\\Nmonde{\\i0}" in exported
    assert "Dialogue: 0,0:00:05.00,0:00:06.00" in exported
    assert "Oui." in exported


def test_ass_to_srt_conversion_is_supported_and_loses_rich_sections(tmp_path: Path) -> None:
    _repo, document, _source_path = _import_source(tmp_path, "sample.ass", ASS_SOURCE)
    translated_lines = document.get_text().replace("Hello", "Bonjour").replace("world", "monde").replace("Yes.", "Oui.")

    asyncio.run(document.set_text(translated_lines.split("\n")))
    output_path = tmp_path / "translated.srt"
    SubtitleDocument.export_merged([document], "srt", output_path)

    exported = output_path.read_text(encoding="utf-8")
    assert "[V4+ Styles]" not in exported
    assert "Do not translate this comment" not in exported
    assert "<i>Bonjour\nmonde</i>" in exported
    assert "Oui." in exported


def test_duplicate_short_subtitles_export_to_independent_events(tmp_path: Path) -> None:
    source = """1
00:00:01,000 --> 00:00:02,000
Yes.

2
00:00:03,000 --> 00:00:04,000
Yes.
"""
    _repo, document, _source_path = _import_source(tmp_path, "duplicate.srt", source)

    asyncio.run(document.set_text(["是。", "", "对。"]))
    output_path = tmp_path / "translated.srt"
    SubtitleDocument.export_merged([document], "srt", output_path)

    subs = pysubs2.load(str(output_path), format_="srt")
    assert [event.start for event in subs.events] == [1000, 3000]
    assert [event.text for event in subs.events] == ["是。", "对。"]


def test_export_keeps_embedded_newlines_with_current_event(tmp_path: Path) -> None:
    source = """1
00:00:01,000 --> 00:00:02,000
Hello.

2
00:00:03,000 --> 00:00:04,000
Yes.
"""
    _repo, document, _source_path = _import_source(tmp_path, "wrapped.srt", source)

    asyncio.run(document.set_text(["Bonjour.", "Encore.", "", "Oui."]))
    output_path = tmp_path / "translated.srt"
    SubtitleDocument.export_merged([document], "srt", output_path)

    subs = pysubs2.load(str(output_path), format_="srt")
    assert [event.text for event in subs.events] == ["Bonjour.\\NEncore.", "Oui."]


def test_export_keeps_compressed_placeholder_with_expanded_event(tmp_path: Path) -> None:
    _repo, document, _source_path = _import_source(tmp_path, "sample.srt", SRT_SOURCE)

    asyncio.run(document.set_text(["Bonjour.", "Encore.", COMPRESSED_LINE_SENTINEL, "", "Oui."]))
    output_path = tmp_path / "translated.srt"
    SubtitleDocument.export_merged([document], "srt", output_path)

    subs = pysubs2.load(str(output_path), format_="srt")
    assert [event.text for event in subs.events] == ["Bonjour.\\NEncore.", "Oui."]


def test_ass_export_preserves_leading_blank_display_line_after_separator(tmp_path: Path) -> None:
    source = """[Script Info]
Title: Leading Blank
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,First
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,\\NSecond
"""
    _repo, document, _source_path = _import_source(tmp_path, "leading-blank.ass", source)

    assert document.get_text() == "First\n\n\nSecond"
    asyncio.run(document.set_text(["Un", "", "", "Deux"]))
    output_path = tmp_path / "translated.ass"
    SubtitleDocument.export_merged([document], "ass", output_path)

    exported = output_path.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,\\NDeux" in exported


def test_export_preserve_structure_uses_original_subtitle_extension(tmp_path: Path) -> None:
    _repo, document, _source_path = _import_source(tmp_path, "episode.ass", ASS_SOURCE)
    asyncio.run(document.set_text(document.get_text().split("\n")))

    output_folder = tmp_path / "preserve"
    document.export_preserve_structure(output_folder)

    output_path = output_folder / "episode.ass"
    assert output_path.exists()
    assert "[V4+ Styles]" in output_path.read_text(encoding="utf-8")
