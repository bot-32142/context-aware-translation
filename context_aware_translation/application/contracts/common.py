from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Base model for application-layer contracts.

    These models are the only data shapes the UI should depend on.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary for transport across UI boundaries."""

        return self.model_dump(mode="json")


class SurfaceStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    DONE = "done"
    CANCELLED = "cancelled"


class QueueStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    DONE = "done"
    CANCELLED = "cancelled"


class BlockerCode(StrEnum):
    NEEDS_SETUP = "needs_setup"
    NEEDS_EARLIER_DOCUMENT_FIRST = "needs_earlier_document_first"
    ALREADY_RUNNING_ELSEWHERE = "already_running_elsewhere"
    NEEDS_REVIEW = "needs_review"
    NOTHING_TO_DO = "nothing_to_do"


class CapabilityCode(StrEnum):
    TRANSLATION = "translation"
    IMAGE_TEXT_READING = "image_text_reading"
    IMAGE_EDITING = "image_editing"
    REASONING_AND_REVIEW = "reasoning_and_review"


class ProviderKind(StrEnum):
    GEMINI = "gemini"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"


class NavigationTargetKind(StrEnum):
    PROJECTS = "projects"
    APP_SETUP = "app_setup"
    PROJECT_SETUP = "project_setup"
    WORK = "work"
    TERMS = "terms"
    QUEUE = "queue"
    DOCUMENT_OCR = "document_ocr"
    DOCUMENT_TERMS = "document_terms"
    DOCUMENT_TRANSLATION = "document_translation"
    DOCUMENT_IMAGES = "document_images"
    DOCUMENT_EXPORT = "document_export"


class DocumentSection(StrEnum):
    OCR = "ocr"
    TERMS = "terms"
    TRANSLATION = "translation"
    IMAGES = "images"
    EXPORT = "export"


class DocumentTypeCode(StrEnum):
    TEXT = "text"
    PDF = "pdf"
    EPUB = "epub"
    SUBTITLE = "subtitle"
    SCANNED_BOOK = "scanned_book"
    MANGA = "manga"
    OTHER = "other"


class UserMessageSeverity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class QueueActionKind(StrEnum):
    RUN = "run"
    CANCEL = "cancel"
    RETRY = "retry"
    DELETE = "delete"
    OPEN_RELATED_ITEM = "open_related_item"


class DocumentRowActionKind(StrEnum):
    OPEN = "open"
    OPEN_OCR = "open_ocr"
    OPEN_TERMS = "open_terms"
    OPEN_TRANSLATION = "open_translation"
    OPEN_IMAGES = "open_images"
    EXPORT = "export"
    BLOCKED = "blocked"
    FIX_SETUP = "fix_setup"


class NavigationTarget(ContractModel):
    kind: NavigationTargetKind
    project_id: str | None = None
    document_id: int | None = None


class UserMessage(ContractModel):
    severity: UserMessageSeverity
    text: str
    code: str | None = None


class BlockerInfo(ContractModel):
    code: BlockerCode
    message: str
    target: NavigationTarget | None = None


class ActionState(ContractModel):
    enabled: bool = False
    blocker: BlockerInfo | None = None


class ProgressInfo(ContractModel):
    current: int | None = None
    total: int | None = None
    label: str | None = None


class ProjectRef(ContractModel):
    project_id: str
    name: str


class DocumentRef(ContractModel):
    document_id: int
    order_index: int
    label: str
    document_type: DocumentTypeCode | None = None


class AcceptedCommand(ContractModel):
    command_name: str
    command_id: str | None = None
    queue_item_id: str | None = None
    message: UserMessage | None = None


class ExportOption(ContractModel):
    format_id: str
    label: str
    is_default: bool = False


class ExportResult(ContractModel):
    output_path: str
    exported_count: int = 1
    message: UserMessage | None = None


class MetadataValue(ContractModel):
    key: str
    value: str


class StringFilter(ContractModel):
    query: str = ""
    filter_id: str = "all"


class IdList(ContractModel):
    values: list[int] = Field(default_factory=list)
