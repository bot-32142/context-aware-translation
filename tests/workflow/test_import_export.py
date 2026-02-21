from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from context_aware_translation.config import Config
from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.workflow.session import WorkflowSession

# Minimal valid 1x1 white PNG (passes epubcheck validation)
_VALID_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff"
    b"?\x00\x05\xfe\x02\xfe\r\xefF\xb8\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (4, 4)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def import_test_config(tmp_path: Path) -> Config:
    work = tmp_path / "data"
    from context_aware_translation.config import (
        ExtractorConfig,
        GlossaryTranslationConfig,
        ReviewConfig,
        SummarizorConfig,
        TranslatorConfig,
    )

    base_settings = {
        "api_key": "DUMMY_API_KEY",
        "base_url": "https://api.test.com/v1",
        "model": "test-model",
    }
    return Config(
        working_dir=work,
        translation_target_language="简体中文",
        extractor_config=ExtractorConfig(**base_settings),
        summarizor_config=SummarizorConfig(**base_settings),
        translator_config=TranslatorConfig(**base_settings),
        glossary_config=GlossaryTranslationConfig(**base_settings),
        review_config=ReviewConfig(**base_settings),
    )


class TestImportPath:
    def test_import_single_text_file(self, import_test_config: Config):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, World!")
            f.flush()
            file_path = Path(f.name)

        try:
            with WorkflowSession(import_test_config) as translator:
                result = translator.import_path(file_path)

                assert result["imported"] == 1
                assert result["skipped"] == 0

                db = translator.document_repo
                doc = db.get_document_row()
                assert doc is not None
                assert doc["document_type"] == "text"

                sources = db.get_document_sources(doc["document_id"])
                assert len(sources) == 1
                assert sources[0]["source_type"] == "text"
                assert sources[0]["text_content"] == "Hello, World!"
        finally:
            file_path.unlink()

    def test_import_single_image_file(self, import_test_config: Config):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as f:
            content = _VALID_PNG
            f.write(content)
            f.flush()
            file_path = Path(f.name)

        try:
            with WorkflowSession(import_test_config) as translator:
                result = translator.import_path(file_path)

                assert result["imported"] == 1

                db = translator.document_repo
                doc = db.get_document_row()
                assert doc is not None
                assert doc["document_type"] == "scanned_book"

                sources = db.get_document_sources(doc["document_id"])
                assert len(sources) == 1
                assert sources[0]["source_type"] == "image"
                assert sources[0]["binary_content"] == content
        finally:
            file_path.unlink()

    def test_import_folder(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "file1.txt").write_text("content1")
            (folder / "file2.txt").write_text("content2")
            (folder / "file3.txt").write_text("content3")

            with WorkflowSession(import_test_config) as translator:
                result = translator.import_path(folder)

                assert result["imported"] == 3
                assert result["skipped"] == 0

                db = translator.document_repo
                doc = db.get_document_row()
                assert doc is not None
                assert doc["document_type"] == "text"

                sources = db.get_document_sources(doc["document_id"])
                assert len(sources) == 3

    def test_import_folder_alphabetical_order(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "zebra.txt").write_text("z")
            (folder / "alpha.txt").write_text("a")
            (folder / "middle.txt").write_text("m")

            with WorkflowSession(import_test_config) as translator:
                translator.import_path(folder)

                db = translator.document_repo
                doc = db.get_document_row()
                sources = db.get_document_sources(doc["document_id"])
                paths = [s["relative_path"] for s in sources]
                assert paths == ["alpha.txt", "middle.txt", "zebra.txt"]

    def test_import_skips_existing_files(self, import_test_config: Config):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello")
            f.flush()
            file_path = Path(f.name)

        try:
            with WorkflowSession(import_test_config) as translator:
                result1 = translator.import_path(file_path)
                assert result1["imported"] == 1
                assert result1["skipped"] == 0

                result2 = translator.import_path(file_path)
                assert result2["imported"] == 0
                assert result2["skipped"] == 1

                db = translator.document_repo
                doc = db.get_document_row()
                sources = db.get_document_sources(doc["document_id"])
                assert len(sources) == 1
        finally:
            file_path.unlink()

    def test_import_ignores_unsupported_files(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "script.py").write_text("print('hello')")
            (folder / "data.json").write_text("{}")
            (folder / "valid.txt").write_text("text")

            with WorkflowSession(import_test_config) as translator:
                result = translator.import_path(folder)

                assert result["imported"] == 1
                db = translator.document_repo
                doc = db.get_document_row()
                sources = db.get_document_sources(doc["document_id"])
                assert len(sources) == 1
                assert sources[0]["relative_path"] == "valid.txt"

    def test_import_ignores_subdirectories(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            subdir = folder / "subdir"
            subdir.mkdir()
            (folder / "root.txt").write_text("root")
            (subdir / "nested.txt").write_text("nested")

            with WorkflowSession(import_test_config) as translator:
                result = translator.import_path(folder)

                assert result["imported"] == 1
                db = translator.document_repo
                doc = db.get_document_row()
                sources = db.get_document_sources(doc["document_id"])
                assert len(sources) == 1
                assert sources[0]["relative_path"] == "root.txt"

    def test_import_can_be_cancelled(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "file1.txt").write_text("content1")
            (folder / "file2.txt").write_text("content2")
            (folder / "file3.txt").write_text("content3")

            state = {"calls": 0}

            def cancel_check() -> bool:
                state["calls"] += 1
                return state["calls"] >= 5

            with WorkflowSession(import_test_config) as translator:
                with pytest.raises(OperationCancelledError):
                    translator.import_path(folder, cancel_check=cancel_check)

                # Cancellation should rollback transaction fully.
                assert translator.document_repo.get_document_row() is None

    def test_import_does_not_cancel_after_successful_do_import(
        self,
        import_test_config: Config,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import context_aware_translation.documents.base as base_module

        class _FakeDoc:
            document_type = "fake"

            @classmethod
            def can_import(cls, _path: Path) -> bool:
                return True

            @classmethod
            def do_import(cls, repo, _path: Path, cancel_check=None):  # noqa: ANN001
                _ = cancel_check
                state["completed"] = True
                repo.insert_document("text", auto_commit=True)
                return {"imported": 1, "skipped": 0}

        state = {"completed": False}

        def cancel_check() -> bool:
            return state["completed"]

        monkeypatch.setattr(base_module, "get_document_classes", lambda: [_FakeDoc])
        fake_file = import_test_config.working_dir / "fake.input"
        fake_file.parent.mkdir(parents=True, exist_ok=True)
        fake_file.write_text("x", encoding="utf-8")

        with WorkflowSession(import_test_config) as translator:
            result = translator.import_path(fake_file, document_type="fake", cancel_check=cancel_check)

        assert result["imported"] == 1
        assert result["skipped"] == 0
        assert result["document_id"] is not None

    def test_import_empty_folder_raises(self, import_test_config: Config):
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            WorkflowSession(import_test_config) as translator,
            pytest.raises(ValueError, match="Cannot import empty folder"),
        ):
            translator.import_path(Path(tmpdir))

    def test_import_nonexistent_path_raises(self, import_test_config: Config):
        with WorkflowSession(import_test_config) as translator, pytest.raises(ValueError, match="does not exist"):
            translator.import_path(Path("/nonexistent/path"))

    def test_import_does_not_create_chunks_for_text_files(self, import_test_config: Config):
        """Test that import_path does NOT create chunks for text files (new behavior)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("This is some text content for chunking.")
            f.flush()
            file_path = Path(f.name)

        try:
            with WorkflowSession(import_test_config) as translator:
                translator.import_path(file_path)

                chunks = translator.manager.term_repo.list_chunks()
                assert len(chunks) == 0  # Should NOT create chunks during import
        finally:
            file_path.unlink()

    def test_import_does_not_create_chunks_for_images(self, import_test_config: Config):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as f:
            f.write(_VALID_PNG)
            f.flush()
            file_path = Path(f.name)

        try:
            with WorkflowSession(import_test_config) as translator:
                translator.import_path(file_path)

                chunks = translator.manager.term_repo.list_chunks()
                assert len(chunks) == 0
        finally:
            file_path.unlink()

    def test_import_text_folder_tracks_line_positions(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "file1.txt").write_text("line1\nline2\n")
            (folder / "file2.txt").write_text("line3\nline4\nline5")

            with WorkflowSession(import_test_config) as translator:
                translator.import_path(folder)

                db = translator.document_repo
                doc = db.get_document_row()
                sources = db.get_document_sources(doc["document_id"])

                assert len(sources) == 2
                assert sources[0]["relative_path"] == "file1.txt"
                assert sources[1]["relative_path"] == "file2.txt"

    def test_import_image_folder_creates_scanned_book(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "page1.png").write_bytes(_png_bytes((10, 20, 30)))
            (folder / "page2.png").write_bytes(_png_bytes((40, 50, 60)))

            with WorkflowSession(import_test_config) as translator:
                translator.import_path(folder, document_type="scanned_book")

                db = translator.document_repo
                doc = db.get_document_row()
                assert doc["document_type"] == "scanned_book"

                sources = db.get_document_sources(doc["document_id"])
                assert len(sources) == 2
                assert all(s["source_type"] == "image" for s in sources)


class TestImportEpub:
    def _make_epub_file(self, tmp_path: Path) -> Path:
        """Create a minimal EPUB for testing."""
        from context_aware_translation.documents.epub_container import (
            EpubBook,
            EpubItem,
            EpubMetadata,
            TocEntry,
            write_epub,
        )

        book = EpubBook(
            metadata=EpubMetadata(
                title="Test Book",
                authors=["Test Author"],
                language="en",
                identifier="test-id",
            ),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><h1>Chapter 1</h1><p>Hello world.</p></body></html>",
                ),
                EpubItem(
                    file_name="OEBPS/ch2.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Second chapter content.</p></body></html>",
                ),
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/images/fig1.png",
                    media_type="image/png",
                    content=_VALID_PNG,
                ),
            ],
            toc=[
                TocEntry(title="Chapter 1", href="ch1.xhtml"),
                TocEntry(title="Chapter 2", href="ch2.xhtml"),
            ],
        )

        epub_path = tmp_path / "test_book.epub"
        write_epub(epub_path, book)
        return epub_path

    def test_import_epub_file(self, import_test_config: Config):
        with WorkflowSession(import_test_config) as session:
            epub_path = self._make_epub_file(import_test_config.working_dir)
            result = session.import_path(epub_path, document_type="epub")

            assert result["imported"] == 1
            assert result["skipped"] == 0

            docs = session.document_repo.list_documents()
            epub_docs = [d for d in docs if d["document_type"] == "epub"]
            assert len(epub_docs) == 1

    def test_import_epub_has_chapter_sources(self, import_test_config: Config):
        with WorkflowSession(import_test_config) as session:
            epub_path = self._make_epub_file(import_test_config.working_dir)
            session.import_path(epub_path, document_type="epub")

            docs = session.document_repo.list_documents()
            sources = session.document_repo.get_document_sources(docs[0]["document_id"])

            chapter_sources = [
                s for s in sources if s["source_type"] == "text" and s.get("relative_path", "").endswith(".xhtml")
            ]
            assert len(chapter_sources) == 2

    def test_import_epub_has_image_sources(self, import_test_config: Config):
        with WorkflowSession(import_test_config) as session:
            epub_path = self._make_epub_file(import_test_config.working_dir)
            session.import_path(epub_path, document_type="epub")

            docs = session.document_repo.list_documents()
            sources = session.document_repo.get_document_sources(docs[0]["document_id"])

            image_sources = [s for s in sources if s["source_type"] == "image"]
            assert len(image_sources) >= 1

    def test_import_epub_metadata_not_in_pipeline(self, import_test_config: Config):
        with WorkflowSession(import_test_config) as session:
            epub_path = self._make_epub_file(import_test_config.working_dir)
            session.import_path(epub_path, document_type="epub")

            docs = session.document_repo.list_documents()
            sources = session.document_repo.get_document_sources(docs[0]["document_id"])

            metadata_sources = [s for s in sources if s.get("relative_path") == "__epub_metadata__.json"]
            assert len(metadata_sources) == 1
            meta = metadata_sources[0]
            assert meta["is_text_added"] == 1
            assert meta["is_ocr_completed"] == 1


class TestExportPreserveStructure:
    async def test_export_text_file(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_folder = Path(tmpdir) / "input"
            output_folder = Path(tmpdir) / "output"
            input_folder.mkdir()

            (input_folder / "test.txt").write_text("Hello World")

            with WorkflowSession(import_test_config) as translator:
                translator.import_path(input_folder)

                db = translator.document_repo
                doc = db.get_document_row()
                doc_id = doc["document_id"]
                sources = db.get_document_sources(doc_id)
                for source in sources:
                    if source["text_content"]:
                        translator.manager.add_text(source["text_content"], 1000, doc_id, "text")

                db.update_all_sources_text_added(doc_id)

                chunks = translator.manager.term_repo.list_chunks()
                for chunk in chunks:
                    chunk.is_translated = True
                    chunk.translation = "翻译后的内容"
                from context_aware_translation.storage.term_repository import (
                    BatchUpdate,
                )

                translator.manager.term_repo.apply_batch(BatchUpdate(keyed_context=[], chunk_records=chunks))

                await translator.export_preserve_structure(output_folder)

                # Output is in document_id subfolder
                output_file = output_folder / str(doc_id) / "test.txt"
                assert output_file.exists()
                assert output_file.read_text() == "翻译后的内容"

    async def test_export_image_file_copied(self, import_test_config: Config):
        """Scanned books do not support structure-preserving export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_folder = Path(tmpdir) / "input"
            output_folder = Path(tmpdir) / "output"
            input_folder.mkdir()

            binary_content = _png_bytes((77, 88, 99))
            (input_folder / "image.png").write_bytes(binary_content)

            with WorkflowSession(import_test_config) as translator:
                translator.import_path(input_folder, document_type="scanned_book")

                # Scanned books don't support structure-preserving export
                with pytest.raises(NotImplementedError, match="do not support structure-preserving export"):
                    await translator.export_preserve_structure(output_folder)

    async def test_export_creates_output_folder(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "test.txt"
            output_folder = Path(tmpdir) / "deep" / "nested" / "output"
            input_file.write_text("Hello")

            with WorkflowSession(import_test_config) as translator:
                translator.import_path(input_file)

                db = translator.document_repo
                doc = db.get_document_row()
                doc_id = doc["document_id"]
                sources = db.get_document_sources(doc_id)
                for source in sources:
                    if source["text_content"]:
                        translator.manager.add_text(source["text_content"], 1000, doc_id, "text")

                db.update_all_sources_text_added(doc_id)

                chunks = translator.manager.term_repo.list_chunks()
                for chunk in chunks:
                    chunk.is_translated = True
                    chunk.translation = "翻译"
                from context_aware_translation.storage.term_repository import (
                    BatchUpdate,
                )

                translator.manager.term_repo.apply_batch(BatchUpdate(keyed_context=[], chunk_records=chunks))

                await translator.export_preserve_structure(output_folder)

                assert output_folder.exists()

    async def test_export_multiple_files(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_folder = Path(tmpdir) / "input"
            output_folder = Path(tmpdir) / "output"
            input_folder.mkdir()

            (input_folder / "file1.txt").write_text("content1")
            (input_folder / "file2.txt").write_text("content2")
            (input_folder / "file3.txt").write_text("content3")

            with WorkflowSession(import_test_config) as translator:
                translator.import_path(input_folder)

                db = translator.document_repo
                doc = db.get_document_row()
                doc_id = doc["document_id"]
                sources = db.get_document_sources(doc_id)
                for source in sources:
                    if source["text_content"]:
                        translator.manager.add_text(source["text_content"], 1000, doc_id, "text")

                db.update_all_sources_text_added(doc_id)

                chunks = translator.manager.term_repo.list_chunks()
                for i, chunk in enumerate(chunks):
                    chunk.is_translated = True
                    chunk.translation = f"翻译{i}"
                from context_aware_translation.storage.term_repository import (
                    BatchUpdate,
                )

                translator.manager.term_repo.apply_batch(BatchUpdate(keyed_context=[], chunk_records=chunks))

                await translator.export_preserve_structure(output_folder)

                # Output is in document_id subfolder
                doc_subfolder = output_folder / str(doc_id)
                assert (doc_subfolder / "file1.txt").exists()
                assert (doc_subfolder / "file2.txt").exists()
                assert (doc_subfolder / "file3.txt").exists()

    async def test_export_empty_source_files(self, import_test_config: Config):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_folder = Path(tmpdir) / "output"

            with (
                WorkflowSession(import_test_config) as translator,
                pytest.raises(ValueError, match="No documents to export"),
            ):
                await translator.export_preserve_structure(output_folder)
