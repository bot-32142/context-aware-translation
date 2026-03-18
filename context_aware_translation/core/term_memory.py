from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TermMemoryVersion:
    term: str
    effective_start_chunk: int
    latest_evidence_chunk: int
    summary_text: str
    kind: str
    source_count: int
    created_at: float
