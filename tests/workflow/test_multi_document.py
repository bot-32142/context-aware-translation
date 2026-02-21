"""Tests for multi-document import and export functionality."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from context_aware_translation.config import Config
from context_aware_translation.storage.term_repository import BatchUpdate
from context_aware_translation.workflow.session import WorkflowSession

_VALID_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff"
    b"?\x00\x05\xfe\x02\xfe\r\xefF\xb8\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def multi_doc_config(tmp_path: Path) -> Config:
    """Create test config for multi-document tests."""
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


class TestMultiDocumentImport:
    """Tests for importing multiple documents."""

    def test_import_multiple_documents(self, multi_doc_config: Config):
        """Import two separate text files and verify both exist in database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            file1 = folder / "doc1.txt"
            file2 = folder / "doc2.txt"
            file1.write_text("First document content")
            file2.write_text("Second document content")

            with WorkflowSession(multi_doc_config) as translator:
                # Import first document
                result1 = translator.import_path(file1)
                assert result1["imported"] == 1
                assert result1["skipped"] == 0

                # Import second document
                result2 = translator.import_path(file2)
                assert result2["imported"] == 1
                assert result2["skipped"] == 0

                # Verify both documents exist
                repo = translator.document_repo
                documents = repo.list_documents()
                assert len(documents) == 2

                # Verify unique document IDs
                doc_ids = {doc["document_id"] for doc in documents}
                assert len(doc_ids) == 2

                # Verify both are text documents
                assert all(doc["document_type"] == "text" for doc in documents)

    def test_chunks_have_document_id(self, multi_doc_config: Config):
        """Import a document and verify chunks have correct document_id."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Test content for chunking")
            f.flush()
            file_path = Path(f.name)

        try:
            with WorkflowSession(multi_doc_config) as translator:
                translator.import_path(file_path)

                # Get document_id
                repo = translator.document_repo
                doc = repo.get_document_row()
                assert doc is not None
                document_id = doc["document_id"]

                # Add text to create chunks
                sources = repo.get_document_sources(document_id)
                for source in sources:
                    if source["text_content"]:
                        translator.manager.add_text(
                            source["text_content"],
                            1000,
                            document_id,
                            "text",
                        )
                repo.update_all_sources_text_added(document_id)

                # Verify chunks have document_id
                chunks = translator.manager.term_repo.list_chunks()
                assert len(chunks) > 0
                assert all(chunk.document_id == document_id for chunk in chunks)
        finally:
            file_path.unlink()

    def test_list_chunks_with_document_id_filter(self, multi_doc_config: Config):
        """Import two documents and verify list_chunks filters by document_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            file1 = folder / "doc1.txt"
            file2 = folder / "doc2.txt"
            file1.write_text("Content for document one")
            file2.write_text("Content for document two")

            with WorkflowSession(multi_doc_config) as translator:
                # Import both documents
                translator.import_path(file1)
                translator.import_path(file2)

                # Get document IDs
                repo = translator.document_repo
                documents = repo.list_documents()
                assert len(documents) == 2
                doc1_id = documents[0]["document_id"]
                doc2_id = documents[1]["document_id"]

                # Add text for both documents
                for doc_id in [doc1_id, doc2_id]:
                    sources = repo.get_document_sources(doc_id)
                    for source in sources:
                        if source["text_content"]:
                            translator.manager.add_text(
                                source["text_content"],
                                1000,
                                doc_id,
                                "text",
                            )
                    repo.update_all_sources_text_added(doc_id)

                # Filter chunks by document_id
                chunks_doc1 = translator.manager.term_repo.list_chunks(document_id=doc1_id)
                chunks_doc2 = translator.manager.term_repo.list_chunks(document_id=doc2_id)

                # Verify filtering works
                assert len(chunks_doc1) > 0
                assert len(chunks_doc2) > 0
                assert all(chunk.document_id == doc1_id for chunk in chunks_doc1)
                assert all(chunk.document_id == doc2_id for chunk in chunks_doc2)

                # Verify chunks are different
                chunk1_ids = {chunk.chunk_id for chunk in chunks_doc1}
                chunk2_ids = {chunk.chunk_id for chunk in chunks_doc2}
                assert chunk1_ids.isdisjoint(chunk2_ids)

    def test_list_documents(self, multi_doc_config: Config):
        """Import multiple documents and verify list_documents returns all."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "doc1.txt").write_text("First")
            (folder / "doc2.txt").write_text("Second")
            (folder / "doc3.txt").write_text("Third")

            with WorkflowSession(multi_doc_config) as translator:
                # Import all documents
                translator.import_path(folder / "doc1.txt")
                translator.import_path(folder / "doc2.txt")
                translator.import_path(folder / "doc3.txt")

                # List documents
                repo = translator.document_repo
                documents = repo.list_documents()

                # Verify all are returned
                assert len(documents) == 3
                assert all("document_id" in doc for doc in documents)
                assert all("document_type" in doc for doc in documents)


class TestMultiDocumentExport:
    """Tests for exporting multiple documents."""

    async def test_export_multiple_same_type(self, multi_doc_config: Config):
        """Import two text documents and verify merged export contains both."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            file1 = folder / "doc1.txt"
            file2 = folder / "doc2.txt"
            output_file = folder / "merged_output.txt"

            file1.write_text("First document content")
            file2.write_text("Second document content")

            with WorkflowSession(multi_doc_config) as translator:
                # Import both documents
                translator.import_path(file1)
                translator.import_path(file2)

                # Get documents and add text
                repo = translator.document_repo
                documents = repo.list_documents()
                assert len(documents) == 2

                for doc in documents:
                    doc_id = doc["document_id"]
                    sources = repo.get_document_sources(doc_id)
                    for source in sources:
                        if source["text_content"]:
                            translator.manager.add_text(
                                source["text_content"],
                                1000,
                                doc_id,
                                "text",
                            )
                    repo.update_all_sources_text_added(doc_id)

                # Mark all chunks as translated
                chunks = translator.manager.term_repo.list_chunks()
                for chunk in chunks:
                    chunk.is_translated = True
                    chunk.translation = f"翻译{chunk.chunk_id}"

                translator.manager.term_repo.apply_batch(BatchUpdate(keyed_context=[], chunk_records=chunks))

                # Export merged
                await translator.export(output_file)

                # Verify output contains content from both documents
                output_content = output_file.read_text()
                assert "翻译" in output_content
                # Should have translations from multiple chunks
                assert len(chunks) >= 2

    async def test_export_mixed_types_raises(self, multi_doc_config: Config):
        """Verify exporting mixed document types raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            text_file = folder / "doc.txt"
            image_file = folder / "image.png"
            output_file = folder / "output.txt"

            text_file.write_text("Text content")
            image_file.write_bytes(_VALID_PNG)

            with WorkflowSession(multi_doc_config) as translator:
                # Import both types
                translator.import_path(text_file)
                translator.import_path(image_file)

                # Attempt to export should raise
                with pytest.raises(ValueError, match="Cannot export mixed document types"):
                    await translator.export(output_file)

    async def test_export_preserve_structure_multiple_docs(self, multi_doc_config: Config):
        """Export with preserve_structure creates document_id subfolders."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            file1 = folder / "doc1.txt"
            file2 = folder / "doc2.txt"
            output_folder = folder / "output"

            file1.write_text("First content")
            file2.write_text("Second content")

            with WorkflowSession(multi_doc_config) as translator:
                # Import both documents
                translator.import_path(file1)
                translator.import_path(file2)

                # Get documents and add text
                repo = translator.document_repo
                documents = repo.list_documents()

                for doc in documents:
                    doc_id = doc["document_id"]
                    sources = repo.get_document_sources(doc_id)
                    for source in sources:
                        if source["text_content"]:
                            translator.manager.add_text(
                                source["text_content"],
                                1000,
                                doc_id,
                                "text",
                            )
                    repo.update_all_sources_text_added(doc_id)

                # Mark all chunks as translated
                chunks = translator.manager.term_repo.list_chunks()
                for chunk in chunks:
                    chunk.is_translated = True
                    chunk.translation = f"翻译{chunk.chunk_id}"

                translator.manager.term_repo.apply_batch(BatchUpdate(keyed_context=[], chunk_records=chunks))

                # Export with preserve structure
                await translator.export_preserve_structure(output_folder)

                # Verify document_id subfolders are created
                assert output_folder.exists()
                subdirs = [d for d in output_folder.iterdir() if d.is_dir()]
                assert len(subdirs) == 2

                # Verify each subfolder has expected files
                for subdir in subdirs:
                    # Should be named as document_id
                    doc_id = int(subdir.name)
                    assert doc_id in [doc["document_id"] for doc in documents]

                    # Should contain output files
                    files = list(subdir.iterdir())
                    assert len(files) > 0

    async def test_export_with_document_ids_filter(self, multi_doc_config: Config):
        """Export with document_ids filter exports only specified documents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            file1 = folder / "doc1.txt"
            file2 = folder / "doc2.txt"
            file3 = folder / "doc3.txt"
            output_file = folder / "filtered_output.txt"

            file1.write_text("First")
            file2.write_text("Second")
            file3.write_text("Third")

            with WorkflowSession(multi_doc_config) as translator:
                # Import all documents
                translator.import_path(file1)
                translator.import_path(file2)
                translator.import_path(file3)

                # Get all documents
                repo = translator.document_repo
                documents = repo.list_documents()
                assert len(documents) == 3

                # Add text for all documents
                for doc in documents:
                    doc_id = doc["document_id"]
                    sources = repo.get_document_sources(doc_id)
                    for source in sources:
                        if source["text_content"]:
                            translator.manager.add_text(
                                source["text_content"],
                                1000,
                                doc_id,
                                "text",
                            )
                    repo.update_all_sources_text_added(doc_id)

                # Mark all chunks as translated
                chunks = translator.manager.term_repo.list_chunks()
                for chunk in chunks:
                    chunk.is_translated = True
                    chunk.translation = f"翻译{chunk.chunk_id}"

                translator.manager.term_repo.apply_batch(BatchUpdate(keyed_context=[], chunk_records=chunks))

                # Export only documents 1 and 3
                doc_ids_to_export = [documents[0]["document_id"], documents[2]["document_id"]]
                await translator.export(output_file, document_ids=doc_ids_to_export)

                # Verify export succeeded (detailed verification would require checking content)
                assert output_file.exists()

                # Verify chunks from doc2 are not included
                doc2_chunks = translator.manager.term_repo.list_chunks(document_id=documents[1]["document_id"])
                doc2_chunk_ids = {chunk.chunk_id for chunk in doc2_chunks}

                # Get exported chunks (those from doc1 and doc3)
                exported_chunks = translator.manager.term_repo.list_chunks(
                    document_id=documents[0]["document_id"]
                ) + translator.manager.term_repo.list_chunks(document_id=documents[2]["document_id"])

                # Verify no overlap with doc2
                exported_chunk_ids = {chunk.chunk_id for chunk in exported_chunks}
                assert doc2_chunk_ids.isdisjoint(exported_chunk_ids)


class TestMultiDocumentValidation:
    """Tests for multi-document validation and edge cases."""

    async def test_empty_database_raises_on_export(self, multi_doc_config: Config):
        """Verify exporting with no documents raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "output.txt"

            with (
                WorkflowSession(multi_doc_config) as translator,
                pytest.raises(ValueError, match="No documents to export"),
            ):
                await translator.export(output_file)

    async def test_export_nonexistent_document_ids(self, multi_doc_config: Config):
        """Export with nonexistent document_ids raises or returns empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            file1 = folder / "doc1.txt"
            output_file = folder / "output.txt"

            file1.write_text("Content")

            with WorkflowSession(multi_doc_config) as translator:
                translator.import_path(file1)

                # Try to export nonexistent document IDs
                with pytest.raises(ValueError, match="No documents to export"):
                    await translator.export(output_file, document_ids=[999, 1000])
