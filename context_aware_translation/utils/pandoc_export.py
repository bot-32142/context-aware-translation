from pathlib import Path

import pypandoc


def _pandoc_extra_args(output_format: str) -> list[str]:
    extra_args: list[str] = []
    # Use MathML for epub to render LaTeX math properly
    if output_format == "epub":
        extra_args.append("--mathml")
    return extra_args


def export_pandoc(markdown: str, output_path: Path, format: str, from_format: str) -> None:
    """
    Exports markdown to a file.

    Cover images for epub are specified via YAML frontmatter (cover-image field)
    in the markdown content itself, handled by CoverItem.to_markdown().

    Note: LaTeX math cleanup is handled earlier in escape_markdown_text()
    when markdown is generated from OCR content.
    """
    pypandoc.convert_text(
        markdown,
        to=format,
        format=from_format,
        outputfile=str(output_path),
        extra_args=_pandoc_extra_args(format),
    )


def export_pandoc_file(input_path: Path, output_path: Path, format: str, from_format: str) -> None:
    """Convert an input file to another format using pandoc."""
    pypandoc.convert_file(
        str(input_path),
        to=format,
        format=from_format,
        outputfile=str(output_path),
        extra_args=_pandoc_extra_args(format),
    )
