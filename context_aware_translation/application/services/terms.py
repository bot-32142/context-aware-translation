from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.common import AcceptedCommand
from context_aware_translation.application.contracts.terms import (
    BuildTermsRequest,
    ExportTermsRequest,
    FilterNoiseRequest,
    ImportTermsRequest,
    ReviewTermsRequest,
    TermsTableState,
    TranslatePendingTermsRequest,
    UpdateTermRequest,
)


class TermsService(Protocol):
    def get_project_terms(self, project_id: str) -> TermsTableState: ...

    def get_document_terms(self, project_id: str, document_id: int) -> TermsTableState: ...

    def update_term(self, request: UpdateTermRequest) -> TermsTableState: ...

    def build_terms(self, request: BuildTermsRequest) -> AcceptedCommand: ...

    def translate_pending(self, request: TranslatePendingTermsRequest) -> AcceptedCommand: ...

    def review_terms(self, request: ReviewTermsRequest) -> AcceptedCommand: ...

    def filter_noise(self, request: FilterNoiseRequest) -> TermsTableState: ...

    def import_terms(self, request: ImportTermsRequest) -> TermsTableState: ...

    def export_terms(self, request: ExportTermsRequest) -> AcceptedCommand: ...
