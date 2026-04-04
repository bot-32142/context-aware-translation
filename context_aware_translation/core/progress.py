"""Progress callback types for workflow operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class WorkflowStep(Enum):
    """Workflow steps that can report progress."""

    OCR = "ocr"
    EXTRACT_TERMS = "extract_terms"
    TERM_MEMORY = "term_memory"
    REVIEW = "review"
    TRANSLATE_GLOSSARY = "translate_glossary"
    TRANSLATE_CHUNKS = "translate_chunks"
    REEMBED = "reembed"
    EXPORT = "export"


@dataclass
class ProgressUpdate:
    """Progress update for workflow operations.

    Attributes:
        step: Current workflow step
        current: Current item being processed (1-indexed)
        total: Total items to process
        message: Human-readable status message
    """

    step: WorkflowStep
    current: int
    total: int
    message: str = ""


# Type alias for progress callback functions
ProgressCallback = Callable[[ProgressUpdate], None]
