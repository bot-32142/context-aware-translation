from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from context_aware_translation.config import TranslatorBatchConfig
from context_aware_translation.storage.repositories.llm_batch_store import LLMBatchStore

POLL_STATUS_PENDING = "pending"
POLL_STATUS_COMPLETED = "completed"
POLL_STATUS_FAILED = "failed"
POLL_STATUS_CANCELLED = "cancelled"


@dataclass(frozen=True)
class BatchPollResult:
    status: str
    error_text: str | None = None
    output_file_name: str | None = None
    warnings: list[str] | None = None


@dataclass(frozen=True)
class BatchSubmitResult:
    batch_name: str
    source_file_name: str | None = None


class BatchJobGateway(ABC):
    """Provider gateway for submit/poll/cancel operations."""

    @abstractmethod
    def build_inlined_request(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        request_kwargs: dict[str, Any],
        metadata: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Return (request_hash, inlined_request_payload)."""

    @abstractmethod
    async def submit_batch(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        model: str,
        inlined_requests: list[dict[str, Any]],
        display_name: str | None = None,
    ) -> BatchSubmitResult:
        """Submit provider batch job and return provider job and source file details."""

    @abstractmethod
    async def poll_once(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        batch_name: str,
        request_hashes: set[str],
        batch_store: LLMBatchStore,
    ) -> BatchPollResult:
        """Poll one provider batch job state and persist available responses."""

    @abstractmethod
    async def cancel_batch(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        batch_name: str,
    ) -> None:
        """Request provider-side cancellation for a submitted batch job."""

    @abstractmethod
    async def delete_batch(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        batch_name: str,
    ) -> None:
        """Best-effort provider-side deletion for completed/cancelled batch jobs."""

    @abstractmethod
    async def delete_file(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        file_name: str,
    ) -> None:
        """Best-effort provider-side deletion for uploaded/output files."""

    @abstractmethod
    async def find_batch_names(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        display_name: str,
        model: str | None = None,
    ) -> list[str]:
        """Find provider batch job names by display name."""
