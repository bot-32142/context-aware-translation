from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from context_aware_translation.application.contracts.common import (
    BlockerInfo,
    ContractModel,
    DocumentRef,
    DocumentSection,
    ExportOption,
    ExportResult,
    ProgressInfo,
    ProjectRef,
    SurfaceStatus,
)
from context_aware_translation.application.contracts.terms import TermsTableState


class DocumentWorkspaceState(ContractModel):
    project: ProjectRef
    document: DocumentRef
    active_tab: DocumentSection
    available_tabs: list[DocumentSection] = Field(default_factory=list)
    blocker: BlockerInfo | None = None


class DocumentSectionCard(ContractModel):
    section: DocumentSection
    status: SurfaceStatus
    summary: str
    blocker: BlockerInfo | None = None


class DocumentOverviewState(ContractModel):
    workspace: DocumentWorkspaceState
    sections: list[DocumentSectionCard] = Field(default_factory=list)


class OCRTextElement(ContractModel):
    element_id: int | None = None
    text: str
    bbox_id: int | None = None


class OCRPageState(ContractModel):
    source_id: int
    page_number: int
    total_pages: int | None = None
    image_path: str | None = None
    status: SurfaceStatus
    extracted_text: str | None = None
    elements: list[OCRTextElement] = Field(default_factory=list)
    blocker: BlockerInfo | None = None


class DocumentOCRState(ContractModel):
    workspace: DocumentWorkspaceState
    pages: list[OCRPageState] = Field(default_factory=list)
    current_page_index: int | None = None
    progress: ProgressInfo | None = None
    active_task_id: str | None = None


class SaveOCRPageRequest(ContractModel):
    project_id: str
    document_id: int
    source_id: int
    extracted_text: str | None = None
    elements: list[OCRTextElement] = Field(default_factory=list)


class RunOCRRequest(ContractModel):
    project_id: str
    document_id: int
    source_id: int | None = None
    pending_only: bool = False


class TranslationUnitKind(StrEnum):
    CHUNK = "chunk"
    PAGE = "page"


class TranslationUnitState(ContractModel):
    unit_id: str
    unit_kind: TranslationUnitKind
    label: str
    status: SurfaceStatus
    source_text: str
    translated_text: str | None = None
    line_count: int | None = None
    blocker: BlockerInfo | None = None


class DocumentTranslationState(ContractModel):
    workspace: DocumentWorkspaceState
    units: list[TranslationUnitState] = Field(default_factory=list)
    current_unit_id: str | None = None
    progress: ProgressInfo | None = None
    active_task_id: str | None = None
    terms: TermsTableState | None = None


class SaveTranslationRequest(ContractModel):
    project_id: str
    document_id: int
    unit_id: str
    translated_text: str


class RetranslateRequest(ContractModel):
    project_id: str
    document_id: int
    unit_id: str


class ImageAssetState(ContractModel):
    asset_id: str
    label: str
    status: SurfaceStatus
    source_id: int | None = None
    output_path: str | None = None
    blocker: BlockerInfo | None = None


class DocumentImagesState(ContractModel):
    workspace: DocumentWorkspaceState
    assets: list[ImageAssetState] = Field(default_factory=list)
    progress: ProgressInfo | None = None
    active_task_id: str | None = None


class RunImageReinsertionRequest(ContractModel):
    project_id: str
    document_id: int
    source_id: int | None = None
    pending_only: bool = True
    force_all: bool = False


class DocumentExportState(ContractModel):
    workspace: DocumentWorkspaceState
    can_export: bool
    available_formats: list[ExportOption] = Field(default_factory=list)
    default_output_path: str | None = None
    blocker: BlockerInfo | None = None


class RunDocumentExportRequest(ContractModel):
    project_id: str
    document_id: int
    format_id: str
    output_path: str
    options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class DocumentExportResult(ExportResult):
    document_id: int
