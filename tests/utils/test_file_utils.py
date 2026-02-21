from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from context_aware_translation.utils.file_utils import (
    IMAGE_EXTENSIONS,
    TEXT_EXTENSIONS,
    classify_file,
    get_mime_type,
    scan_folder,
)


class TestClassifyFile:
    def test_text_extensions(self):
        for ext in TEXT_EXTENSIONS:
            assert classify_file(Path(f"test{ext}")) == "text"

    def test_text_extensions_uppercase(self):
        assert classify_file(Path("test.TXT")) == "text"
        assert classify_file(Path("test.MD")) == "text"

    def test_image_extensions(self):
        for ext in IMAGE_EXTENSIONS:
            assert classify_file(Path(f"test{ext}")) == "image"

    def test_image_extensions_uppercase(self):
        assert classify_file(Path("test.PNG")) == "image"
        assert classify_file(Path("test.JPG")) == "image"

    def test_unsupported_extension(self):
        assert classify_file(Path("test.py")) is None
        assert classify_file(Path("test.json")) is None
        assert classify_file(Path("test.csv")) is None
        assert classify_file(Path("test")) is None

    def test_hidden_files(self):
        assert classify_file(Path(".hidden.txt")) == "text"
        assert classify_file(Path(".hidden.png")) == "image"

    def test_multiple_dots(self):
        assert classify_file(Path("file.backup.txt")) == "text"
        assert classify_file(Path("image.2024.png")) == "image"


class TestGetMimeType:
    def test_text_files(self):
        assert get_mime_type(Path("file.txt")) == "text/plain"

    def test_markdown_files(self):
        mime = get_mime_type(Path("file.md"))
        assert mime in ("text/markdown", "text/x-markdown", None)

    def test_image_files(self):
        assert get_mime_type(Path("file.png")) == "image/png"
        assert get_mime_type(Path("file.jpg")) == "image/jpeg"
        assert get_mime_type(Path("file.jpeg")) == "image/jpeg"
        assert get_mime_type(Path("file.gif")) == "image/gif"

    def test_pdf_files(self):
        assert get_mime_type(Path("file.pdf")) == "application/pdf"

    def test_unknown_extension(self):
        result = get_mime_type(Path("file.xyz123"))
        assert result is None


class TestScanFolder:
    def test_scans_supported_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "file1.txt").write_text("text1")
            (folder / "file2.md").write_text("text2")
            (folder / "image.png").write_bytes(b"png")
            (folder / "image2.jpg").write_bytes(b"jpg")

            files = scan_folder(folder)

            assert len(files) == 4
            names = [f.name for f in files]
            assert "file1.txt" in names
            assert "file2.md" in names
            assert "image.png" in names
            assert "image2.jpg" in names

    def test_ignores_unsupported_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "script.py").write_text("print('hello')")
            (folder / "data.json").write_text("{}")
            (folder / "file.txt").write_text("text")

            files = scan_folder(folder)

            assert len(files) == 1
            assert files[0].name == "file.txt"

    def test_ignores_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            subdir = folder / "subdir"
            subdir.mkdir()
            (folder / "root.txt").write_text("root")
            (subdir / "nested.txt").write_text("nested")

            files = scan_folder(folder)

            assert len(files) == 1
            assert files[0].name == "root.txt"

    def test_returns_alphabetically_sorted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "zebra.txt").write_text("z")
            (folder / "alpha.txt").write_text("a")
            (folder / "middle.txt").write_text("m")

            files = scan_folder(folder)

            names = [f.name for f in files]
            assert names == ["alpha.txt", "middle.txt", "zebra.txt"]

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            files = scan_folder(Path(tmpdir))
            assert files == []

    def test_raises_for_nonexistent_folder(self):
        with pytest.raises(ValueError, match="not a directory"):
            scan_folder(Path("/nonexistent/folder"))

    def test_raises_for_file_path(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="not a directory"):
                scan_folder(path)
        finally:
            path.unlink()
