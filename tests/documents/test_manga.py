from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from context_aware_translation.documents.manga import MangaDocument


def _png_bytes(width: int = 16, height: int = 16) -> bytes:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_process_ocr_with_empty_source_ids_processes_none():
    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = [
        {
            "source_id": 1,
            "sequence_number": 0,
            "binary_content": _png_bytes(),
            "mime_type": "image/png",
        }
    ]

    mock_ocr_config = MagicMock()
    mock_ocr_config.concurrency = 3
    mock_ocr_config.ocr_dpi = 150

    with patch(
        "context_aware_translation.llm.manga_ocr.ocr_manga_image_with_regions",
        new_callable=AsyncMock,
    ) as mock_ocr:
        doc = MangaDocument(mock_repo, 1, mock_ocr_config)
        processed = await doc.process_ocr(MagicMock(), source_ids=[])

        assert processed == 0
        mock_ocr.assert_not_called()
        mock_repo.update_source_ocr.assert_not_called()
        mock_repo.update_source_ocr_completed.assert_not_called()


@pytest.mark.asyncio
async def test_process_ocr_persists_regions_payload() -> None:
    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = [
        {
            "source_id": 1,
            "sequence_number": 0,
            "binary_content": _png_bytes(),
            "mime_type": "image/png",
        }
    ]

    mock_ocr_config = MagicMock()
    mock_ocr_config.concurrency = 1
    mock_ocr_config.ocr_dpi = 150

    payload = {
        "text": "line1",
        "regions": [{"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1, "text": "line1"}],
    }
    with patch(
        "context_aware_translation.llm.manga_ocr.ocr_manga_image_with_regions",
        new_callable=AsyncMock,
    ) as mock_ocr:
        mock_ocr.return_value = payload
        doc = MangaDocument(mock_repo, 1, mock_ocr_config)
        processed = await doc.process_ocr(MagicMock())

    assert processed == 1
    update_call = mock_repo.update_source_ocr.call_args
    assert update_call is not None
    saved_payload = json.loads(update_call.args[1])
    assert saved_payload["text"] == "line1"
    assert isinstance(saved_payload.get("regions"), list)


def test_do_import_rejects_invalid_folder_images(tmp_path: Path, temp_config):
    from context_aware_translation.storage.book_db import SQLiteBookDB
    from context_aware_translation.storage.document_repository import DocumentRepository

    folder = tmp_path / "manga_folder"
    folder.mkdir()
    (folder / "page1.png").write_bytes(b"not-a-real-image")

    db = SQLiteBookDB(temp_config.sqlite_path)
    repo = DocumentRepository(db)

    with pytest.raises(ValueError, match="Invalid image data"):
        MangaDocument.do_import(repo, folder)

    assert repo.get_document_row() is None


def test_do_import_rejects_invalid_cbz_images(tmp_path: Path, temp_config):
    from context_aware_translation.storage.book_db import SQLiteBookDB
    from context_aware_translation.storage.document_repository import DocumentRepository

    cbz_path = tmp_path / "broken.cbz"
    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.writestr("001.png", b"not-a-real-image")

    db = SQLiteBookDB(temp_config.sqlite_path)
    repo = DocumentRepository(db)

    with pytest.raises(ValueError, match="Invalid image data"):
        MangaDocument.do_import(repo, cbz_path)

    assert repo.get_document_row() is None


@pytest.mark.asyncio
async def test_reembed_preserves_inner_exception_as_cause() -> None:
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"source_id": 10, "sequence_number": 0, "ocr_json": '{"text":"jp1"}', "binary_content": _png_bytes()},
    ]
    mock_repo.load_reembedded_images.return_value = {}

    mock_ocr_config = MagicMock()
    doc = MangaDocument(mock_repo, 1, mock_ocr_config)
    await doc.set_text(["EN PAGE 1"])

    image_reembedding_config = MagicMock()
    image_reembedding_config.concurrency = 1
    image_reembedding_config.kwargs = {}
    mock_generator = MagicMock()
    mock_generator.edit_image = AsyncMock(side_effect=ValueError("boom"))

    with (
        patch(
            "context_aware_translation.llm.image_generator.create_image_generator",
            return_value=mock_generator,
        ),
        pytest.raises(RuntimeError, match=r"source 10\): ValueError: boom") as exc_info,
    ):
        await doc.reembed(image_reembedding_config)

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "boom"
    call_args = mock_generator.edit_image.await_args
    assert isinstance(call_args.args[0], bytes)
    assert call_args.args[0].startswith(b"\x89PNG")
    assert call_args.args[1] == "image/png"
    assert call_args.args[2] == [("jp1", "EN PAGE 1")]


@pytest.mark.asyncio
async def test_reembed_uses_grouped_crops_when_regions_present() -> None:
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    page_bytes = buffer.getvalue()

    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {
            "source_id": 10,
            "sequence_number": 0,
            "mime_type": "image/png",
            "binary_content": page_bytes,
            "ocr_json": json.dumps(
                {
                    "text": "jp1\njp2",
                    "regions": [
                        {"x": 0.05, "y": 0.10, "width": 0.12, "height": 0.10, "text": "jp1"},
                        {"x": 0.72, "y": 0.66, "width": 0.13, "height": 0.11, "text": "jp2"},
                    ],
                }
            ),
        }
    ]
    mock_repo.load_reembedded_images.return_value = {}

    doc = MangaDocument(mock_repo, 1, MagicMock())
    await doc.set_text(["EN1\nEN2"])

    image_reembedding_config = MagicMock()
    image_reembedding_config.concurrency = 1
    image_reembedding_config.kwargs = {}

    mock_generator = MagicMock()
    mock_generator.edit_image = AsyncMock(side_effect=lambda image_bytes, *_args, **_kwargs: image_bytes)

    with patch(
        "context_aware_translation.llm.image_generator.create_image_generator",
        return_value=mock_generator,
    ):
        processed = await doc.reembed(image_reembedding_config)

    assert processed == 1
    assert mock_generator.edit_image.await_count == 2
    first_call = mock_generator.edit_image.await_args_list[0]
    second_call = mock_generator.edit_image.await_args_list[1]
    assert first_call.args[2] == [("jp1", "EN1")]
    assert second_call.args[2] == [("jp2", "EN2")]
    mock_repo.save_reembedded_image.assert_called_once()
