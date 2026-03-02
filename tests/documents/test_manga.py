from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_aware_translation.documents.manga import MangaDocument


@pytest.mark.asyncio
async def test_process_ocr_with_empty_source_ids_processes_none():
    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = [
        {
            "source_id": 1,
            "sequence_number": 0,
            "binary_content": b"fake_image_data",
            "mime_type": "image/png",
        }
    ]

    mock_ocr_config = MagicMock()
    mock_ocr_config.concurrency = 3
    mock_ocr_config.ocr_dpi = 150

    with patch("context_aware_translation.llm.manga_ocr.ocr_manga_image", new_callable=AsyncMock) as mock_ocr:
        doc = MangaDocument(mock_repo, 1, mock_ocr_config)
        processed = await doc.process_ocr(MagicMock(), source_ids=[])

        assert processed == 0
        mock_ocr.assert_not_called()
        mock_repo.update_source_ocr.assert_not_called()
        mock_repo.update_source_ocr_completed.assert_not_called()


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
        {"source_id": 10, "sequence_number": 0, "ocr_json": '{"text":"jp1"}', "binary_content": b"img1"},
    ]
    mock_repo.load_reembedded_images.return_value = {}

    mock_ocr_config = MagicMock()
    doc = MangaDocument(mock_repo, 1, mock_ocr_config)
    await doc.set_text(["EN PAGE 1"])

    image_reembedding_config = MagicMock()
    image_reembedding_config.concurrency = 1
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
