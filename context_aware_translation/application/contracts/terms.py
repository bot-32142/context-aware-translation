from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from context_aware_translation.application.contracts.common import (
    BlockerInfo,
    ContractModel,
    DocumentRef,
    ProjectRef,
    StringFilter,
    SurfaceStatus,
)


class TermsScopeKind(StrEnum):
    PROJECT = "project"
    DOCUMENT = "document"


class TermStatus(StrEnum):
    NEEDS_TRANSLATION = "needs_translation"
    NEEDS_REVIEW = "needs_review"
    READY = "ready"
    IGNORED = "ignored"


class TermsScope(ContractModel):
    kind: TermsScopeKind
    project: ProjectRef
    document: DocumentRef | None = None


class TermTableRow(ContractModel):
    term_id: int
    term: str
    translation: str | None = None
    description: str | None = None
    occurrences: int = 0
    votes: int = 0
    ignored: bool = False
    reviewed: bool = False
    status: TermStatus = TermStatus.NEEDS_TRANSLATION


class TermsToolbarState(ContractModel):
    can_build: bool = False
    can_translate_pending: bool = False
    can_review: bool = False
    can_filter_noise: bool = False
    can_import: bool = True
    can_export: bool = True
    build_blocker: BlockerInfo | None = None


class TermsTableState(ContractModel):
    scope: TermsScope
    filters: StringFilter = Field(default_factory=StringFilter)
    toolbar: TermsToolbarState = Field(default_factory=TermsToolbarState)
    rows: list[TermTableRow] = Field(default_factory=list)
    status: SurfaceStatus = SurfaceStatus.READY


class UpdateTermRequest(ContractModel):
    scope: TermsScope
    term_id: int
    translation: str | None = None
    description: str | None = None
    ignored: bool | None = None
    reviewed: bool | None = None


class BuildTermsRequest(ContractModel):
    project_id: str
    document_id: int | None = None
    cutoff_document_id: int | None = None


class TranslatePendingTermsRequest(ContractModel):
    project_id: str
    document_id: int | None = None


class ReviewTermsRequest(ContractModel):
    project_id: str
    document_id: int | None = None


class FilterNoiseRequest(ContractModel):
    project_id: str
    threshold: float | None = None
    document_id: int | None = None


class ImportTermsRequest(ContractModel):
    project_id: str
    input_path: str


class ExportTermsRequest(ContractModel):
    project_id: str
    output_path: str
    document_id: int | None = None
