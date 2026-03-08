from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.common import AcceptedCommand
from context_aware_translation.application.contracts.document import (
    DocumentExportResult,
    DocumentExportState,
    DocumentImagesState,
    DocumentOCRState,
    DocumentOverviewState,
    DocumentTranslationState,
    DocumentWorkspaceState,
    RetranslateRequest,
    RunDocumentExportRequest,
    RunImageReinsertionRequest,
    RunOCRRequest,
    SaveOCRPageRequest,
    SaveTranslationRequest,
)
from context_aware_translation.application.contracts.terms import TermsTableState


class DocumentService(Protocol):
    def get_workspace(self, project_id: str, document_id: int) -> DocumentWorkspaceState: ...

    def get_overview(self, project_id: str, document_id: int) -> DocumentOverviewState: ...

    def get_ocr(self, project_id: str, document_id: int) -> DocumentOCRState: ...

    def save_ocr(self, request: SaveOCRPageRequest) -> DocumentOCRState: ...

    def run_ocr(self, request: RunOCRRequest) -> AcceptedCommand: ...

    def get_terms(self, project_id: str, document_id: int) -> TermsTableState: ...

    def get_translation(self, project_id: str, document_id: int) -> DocumentTranslationState: ...

    def save_translation(self, request: SaveTranslationRequest) -> DocumentTranslationState: ...

    def retranslate(self, request: RetranslateRequest) -> AcceptedCommand: ...

    def get_images(self, project_id: str, document_id: int) -> DocumentImagesState: ...

    def run_image_reinsertion(self, request: RunImageReinsertionRequest) -> AcceptedCommand: ...

    def get_export(self, project_id: str, document_id: int) -> DocumentExportState: ...

    def export_document(self, request: RunDocumentExportRequest) -> DocumentExportResult: ...
