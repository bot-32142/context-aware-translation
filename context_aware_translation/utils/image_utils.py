"""Image utility functions for document processing."""

from __future__ import annotations


def validate_image_bytes(image_bytes: bytes, source_name: str | None = None) -> None:
    """Validate that bytes represent a decodable raster image.

    Args:
        image_bytes: Raw image bytes
        source_name: Optional source identifier for error messages

    Raises:
        ValueError: If bytes are empty or cannot be decoded as an image
    """
    import io

    from PIL import Image, UnidentifiedImageError

    source_label = f" '{source_name}'" if source_name else ""

    if not image_bytes:
        raise ValueError(f"Invalid image data{source_label}: empty payload")

    try:
        # verify() catches many structural issues quickly.
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.verify()
        # Re-open and decode to catch runtime decode failures.
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ValueError(f"Invalid image data{source_label}: {e}") from e


def compress_image_for_ocr(image_bytes: bytes, max_dpi: int = 150) -> bytes:
    """Compress image to a maximum DPI for faster OCR processing.

    Args:
        image_bytes: Original image bytes (PNG or JPEG format)
        max_dpi: Maximum DPI for output (default 150)

    Returns:
        Compressed image bytes (PNG format), or original if already small enough
    """
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    width, height = img.size

    # Estimate current DPI assuming US Letter page (8.5x11 inches)
    # This is a heuristic - actual DPI depends on page size
    estimated_dpi = max(width / 8.5, height / 11)

    if estimated_dpi <= max_dpi:
        return image_bytes  # Already small enough

    # Scale down to target DPI
    scale_factor = max_dpi / estimated_dpi
    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)

    resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()


def detect_mime_type(image_bytes: bytes) -> str:
    """Detect MIME type from image bytes magic number."""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    elif image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    elif image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    elif image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    else:
        return "image/png"  # Default to PNG
