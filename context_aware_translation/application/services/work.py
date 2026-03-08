from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.common import AcceptedCommand, ExportResult
from context_aware_translation.application.contracts.work import (
    ExportDialogState,
    ImportDocumentsRequest,
    PrepareExportRequest,
    RunExportRequest,
    WorkboardState,
)


class WorkService(Protocol):
    def get_workboard(self, project_id: str) -> WorkboardState: ...

    def import_documents(self, request: ImportDocumentsRequest) -> AcceptedCommand: ...

    def prepare_export(self, request: PrepareExportRequest) -> ExportDialogState: ...

    def run_export(self, request: RunExportRequest) -> ExportResult: ...
