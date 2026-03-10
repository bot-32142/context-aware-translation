from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from context_aware_translation.application.contracts.common import (
    ActionState,
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


class DocumentOCRActions(ContractModel):
    save: ActionState = Field(default_factory=ActionState)
    run_current: ActionState = Field(default_factory=ActionState)
    run_pending: ActionState = Field(default_factory=ActionState)


class DocumentOCRState(ContractModel):
    workspace: DocumentWorkspaceState
    pages: list[OCRPageState] = Field(default_factory=list)
    current_page_index: int | None = None
    actions: DocumentOCRActions = Field(default_factory=DocumentOCRActions)
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


class TranslationUnitActionState(ContractModel):
    can_save: bool = True
    can_retranslate: bool = False
    save_blocker: BlockerInfo | None = None
    retranslate_blocker: BlockerInfo | None = None


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
    source_id: int | None = None
    actions: TranslationUnitActionState = Field(default_factory=TranslationUnitActionState)
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


class RunDocumentTranslationRequest(ContractModel):
    project_id: str
    document_id: int


class ImageAssetState(ContractModel):
    asset_id: str
    label: str
    status: SurfaceStatus
    source_id: int | None = None
    translated_text: str | None = None
    output_path: str | None = None
    blocker: BlockerInfo | None = None
    can_run: bool = False
    run_blocker: BlockerInfo | None = None


class DocumentImagesToolbarState(ContractModel):
    can_run_pending: bool = False
    can_force_all: bool = False
    can_cancel: bool = False
    run_pending_blocker: BlockerInfo | None = None
    force_all_blocker: BlockerInfo | None = None
    cancel_blocker: BlockerInfo | None = None


class DocumentImagesState(ContractModel):
    workspace: DocumentWorkspaceState
    assets: list[ImageAssetState] = Field(default_factory=list)
    toolbar: DocumentImagesToolbarState = Field(default_factory=DocumentImagesToolbarState)
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
    supports_preserve_structure: bool = False
    incomplete_translation_message: str | None = None


class RunDocumentExportRequest(ContractModel):
    project_id: str
    document_id: int
    format_id: str
    output_path: str
    options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class DocumentExportResult(ExportResult):
    document_id: int
