from __future__ import annotations

from pydantic import Field

from context_aware_translation.application.contracts.common import (
    BlockerInfo,
    ContractModel,
    DocumentRef,
    DocumentRowActionKind,
    ExportOption,
    NavigationTarget,
    ProjectRef,
    SurfaceStatus,
)


class DocumentRowAction(ContractModel):
    kind: DocumentRowActionKind
    label: str
    target: NavigationTarget | None = None
    blocker: BlockerInfo | None = None


class ContextFrontierState(ContractModel):
    summary: str
    last_ready_document: DocumentRef | None = None
    blocker: BlockerInfo | None = None


class WorkDocumentRow(ContractModel):
    document: DocumentRef
    status: SurfaceStatus
    state_summary: str
    blocker: BlockerInfo | None = None
    primary_action: DocumentRowAction


class WorkboardState(ContractModel):
    project: ProjectRef
    context_frontier: ContextFrontierState | None = None
    rows: list[WorkDocumentRow] = Field(default_factory=list)
    setup_blocker: BlockerInfo | None = None


class ImportDocumentsRequest(ContractModel):
    project_id: str
    paths: list[str]


class PrepareExportRequest(ContractModel):
    project_id: str
    document_ids: list[int]


class ExportDialogState(ContractModel):
    project_id: str
    document_ids: list[int]
    document_labels: list[str]
    available_formats: list[ExportOption]
    default_output_path: str | None = None
    blocker: BlockerInfo | None = None
    supports_preserve_structure: bool = False
    incomplete_translation_message: str | None = None


class RunExportRequest(ContractModel):
    project_id: str
    document_ids: list[int]
    format_id: str
    output_path: str
    options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
