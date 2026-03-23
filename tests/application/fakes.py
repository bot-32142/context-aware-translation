from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionSummary,
    ConnectionTestRequest,
    ConnectionTestResult,
    SaveConnectionRequest,
    SaveWorkflowProfileRequest,
    SetupWizardRequest,
    SetupWizardState,
)
from context_aware_translation.application.contracts.common import AcceptedCommand, DocumentSection
from context_aware_translation.application.contracts.document import (
    CancelOCRRequest,
    DocumentExportResult,
    DocumentExportState,
    DocumentImagesState,
    DocumentOCRActions,
    DocumentOCRState,
    DocumentTranslationState,
    DocumentWorkspaceState,
    RetranslateRequest,
    RunDocumentExportRequest,
    RunDocumentTranslationRequest,
    RunImageReinsertionRequest,
    RunOCRRequest,
    SaveOCRPageRequest,
    SaveTranslationRequest,
)
from context_aware_translation.application.contracts.project_setup import ProjectSetupState, SaveProjectSetupRequest
from context_aware_translation.application.contracts.projects import (
    CreateProjectRequest,
    ProjectsScreenState,
    ProjectSummary,
    UpdateProjectRequest,
    WorkflowProfileOption,
)
from context_aware_translation.application.contracts.queue import QueueActionRequest, QueueState
from context_aware_translation.application.contracts.terms import (
    BuildTermsRequest,
    BulkUpdateTermsRequest,
    BulkUpdateTermsResult,
    ExportTermsRequest,
    FilterNoiseRequest,
    ImportTermsRequest,
    ReviewTermsRequest,
    TermsTableState,
    TermsToolbarState,
    TranslatePendingTermsRequest,
    UpdateTermRequest,
    UpdateTermRowsRequest,
    UpdateTermRowsResult,
)
from context_aware_translation.application.contracts.work import (
    DeleteDocumentStackRequest,
    ExportDialogState,
    ImportDocumentsRequest,
    ImportInspectionState,
    InspectImportPathsRequest,
    PrepareExportRequest,
    ResetDocumentStackRequest,
    RunExportRequest,
    WorkboardState,
    WorkMutationResult,
)
from context_aware_translation.application.events import InMemoryApplicationEventBus


@dataclass
class FakeApplicationServices:
    work: Any = None
    projects: Any = None
    app_setup: Any = None
    project_setup: Any = None
    terms: Any = None
    document: Any = None
    queue: Any = None


@dataclass
class FakeApplicationContext:
    services: FakeApplicationServices
    events: InMemoryApplicationEventBus = field(default_factory=InMemoryApplicationEventBus)


@dataclass
class FakeProjectsService:
    list_state: ProjectsScreenState
    project_summary: ProjectSummary | None = None
    create_result: ProjectSummary | None = None
    update_result: ProjectSummary | None = None
    workflow_profiles: list[WorkflowProfileOption] = field(default_factory=list)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def list_projects(self) -> ProjectsScreenState:
        self.calls.append(("list_projects", None))
        return self.list_state

    def get_project(self, project_id: str) -> ProjectSummary:
        self.calls.append(("get_project", project_id))
        project = self.project_summary or self.create_result or self.update_result
        if project is None:
            raise NotImplementedError
        return cast(ProjectSummary, project)

    def list_workflow_profiles(self) -> list[WorkflowProfileOption]:
        self.calls.append(("list_workflow_profiles", None))
        return list(self.workflow_profiles)

    def create_project(self, request: CreateProjectRequest) -> ProjectSummary:
        self.calls.append(("create_project", request))
        project = self.create_result or self.project_summary
        if project is None:
            raise NotImplementedError
        return cast(ProjectSummary, project)

    def update_project(self, request: UpdateProjectRequest) -> ProjectSummary:
        self.calls.append(("update_project", request))
        project = self.update_result or self.project_summary
        if project is None:
            raise NotImplementedError
        return cast(ProjectSummary, project)

    def delete_project(self, project_id: str, *, permanent: bool = True) -> None:
        self.calls.append(("delete_project", (project_id, permanent)))


@dataclass
class FakeAppSetupService:
    state: AppSetupState
    wizard_state: SetupWizardState | None = None
    preview_state: SetupWizardState | None = None
    test_result: ConnectionTestResult | None = None
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def get_state(self) -> AppSetupState:
        self.calls.append(("get_state", None))
        return self.state

    def get_wizard_state(self) -> SetupWizardState:
        self.calls.append(("get_wizard_state", None))
        return self.wizard_state if self.wizard_state is not None else SetupWizardState()

    def preview_setup_wizard(self, request: SetupWizardRequest) -> SetupWizardState:
        self.calls.append(("preview_setup_wizard", request))
        return self.preview_state if self.preview_state is not None else self.get_wizard_state()

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState:
        self.calls.append(("save_connection", request))
        return self.state

    def delete_connection(self, connection_id: str) -> AppSetupState:
        self.calls.append(("delete_connection", connection_id))
        return self.state

    def duplicate_connection(self, connection_id: str) -> AppSetupState:
        self.calls.append(("duplicate_connection", connection_id))
        return self.state

    def reset_connection_tokens(self, connection_id: str) -> ConnectionSummary:
        self.calls.append(("reset_connection_tokens", connection_id))
        return self.state.connections[0]

    def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResult:
        self.calls.append(("test_connection", request))
        if self.test_result is None:
            raise NotImplementedError
        return self.test_result

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState:
        self.calls.append(("run_setup_wizard", request))
        return self.state

    def save_workflow_profile(self, request: SaveWorkflowProfileRequest) -> AppSetupState:
        self.calls.append(("save_workflow_profile", request))
        return self.state

    def duplicate_workflow_profile(self, profile_id: str) -> AppSetupState:
        self.calls.append(("duplicate_workflow_profile", profile_id))
        return self.state

    def delete_workflow_profile(self, profile_id: str) -> AppSetupState:
        self.calls.append(("delete_workflow_profile", profile_id))
        return self.state


@dataclass
class FakeProjectSetupService:
    state: ProjectSetupState
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def get_state(self, project_id: str) -> ProjectSetupState:
        self.calls.append(("get_state", project_id))
        return self.state

    def save(self, request: SaveProjectSetupRequest) -> ProjectSetupState:
        self.calls.append(("save", request))
        return self.state


@dataclass
class FakeWorkService:
    state_by_project: dict[str, WorkboardState]
    export_state: ExportDialogState | None = None
    export_result: Any | None = None
    import_inspection_state: ImportInspectionState | None = None
    import_result: AcceptedCommand | None = None
    reset_result: WorkMutationResult | None = None
    delete_result: WorkMutationResult | None = None
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def get_workboard(self, project_id: str) -> WorkboardState:
        self.calls.append(("get_workboard", project_id))
        return self.state_by_project[project_id]

    def inspect_import_paths(self, request: InspectImportPathsRequest) -> ImportInspectionState:
        self.calls.append(("inspect_import_paths", request))
        if self.import_inspection_state is None:
            raise NotImplementedError
        return self.import_inspection_state

    def import_documents(self, request: ImportDocumentsRequest) -> AcceptedCommand:
        self.calls.append(("import_documents", request))
        if self.import_result is None:
            raise NotImplementedError
        return self.import_result

    def reset_document_stack(self, request: ResetDocumentStackRequest) -> WorkMutationResult:
        self.calls.append(("reset_document_stack", request))
        if self.reset_result is None:
            raise NotImplementedError
        return self.reset_result

    def delete_document_stack(self, request: DeleteDocumentStackRequest) -> WorkMutationResult:
        self.calls.append(("delete_document_stack", request))
        if self.delete_result is None:
            raise NotImplementedError
        return self.delete_result

    def prepare_export(self, request: PrepareExportRequest) -> ExportDialogState:
        self.calls.append(("prepare_export", request))
        if self.export_state is None:
            raise NotImplementedError
        return self.export_state

    def run_export(self, request: RunExportRequest) -> Any:
        self.calls.append(("run_export", request))
        if self.export_result is None:
            raise NotImplementedError
        return self.export_result


@dataclass
class FakeTermsService:
    project_state: TermsTableState
    document_state: TermsTableState | None = None
    command_result: AcceptedCommand | None = None
    calls: list[tuple[str, Any]] = field(default_factory=list)

    @staticmethod
    def _with_recomputed_toolbar(state: TermsTableState) -> TermsTableState:
        rows = state.rows
        blocked = any(
            blocker is not None and blocker.message == "Another terms task is already running for this project."
            for blocker in (
                state.toolbar.translate_pending_blocker,
                state.toolbar.review_blocker,
                state.toolbar.filter_noise_blocker,
            )
        )
        toolbar = state.toolbar.model_copy(
            update={
                "can_translate_pending": (
                    False if blocked else any(not (row.translation or "").strip() and not row.ignored for row in rows)
                ),
                "can_review": False if blocked else any(not row.reviewed for row in rows),
                "can_filter_noise": (
                    False
                    if blocked
                    else any(not row.ignored and not row.reviewed and row.rare_candidate for row in rows)
                ),
            }
        )
        return state.model_copy(update={"toolbar": toolbar})

    def get_project_terms(self, project_id: str) -> TermsTableState:
        self.calls.append(("get_project_terms", project_id))
        return self.project_state

    def get_document_terms(self, project_id: str, document_id: int) -> TermsTableState:
        self.calls.append(("get_document_terms", (project_id, document_id)))
        return self.document_state or self.project_state

    def get_toolbar_state(
        self,
        project_id: str,
        *,
        document_id: int | None = None,
        rows: Sequence[Any] | None = None,
    ) -> TermsToolbarState:
        self.calls.append(("get_toolbar_state", (project_id, document_id)))
        state = (
            self.document_state if document_id is not None and self.document_state is not None else self.project_state
        )
        if rows is not None:
            state = state.model_copy(update={"rows": list(rows)})
        return self._with_recomputed_toolbar(state).toolbar

    def update_term(self, request: UpdateTermRequest) -> TermsTableState:
        self.calls.append(("update_term", request))
        return self.document_state or self.project_state

    def update_term_rows(self, request: UpdateTermRowsRequest) -> UpdateTermRowsResult:
        self.calls.append(("update_term_rows", request))
        rows_by_key = {row.term_key: row for row in request.rows}
        updated_state = (self.document_state or self.project_state).model_copy(
            update={
                "rows": [rows_by_key.get(row.term_key, row) for row in (self.document_state or self.project_state).rows]
            }
        )
        updated_state = self._with_recomputed_toolbar(updated_state)
        if self.document_state is not None:
            self.document_state = updated_state
        else:
            self.project_state = updated_state
        return UpdateTermRowsResult(rows=request.rows)

    def build_terms(self, request: BuildTermsRequest) -> AcceptedCommand:
        self.calls.append(("build_terms", request))
        return self.command_result or AcceptedCommand(command_name="build_terms")

    def translate_pending(self, request: TranslatePendingTermsRequest) -> AcceptedCommand:
        self.calls.append(("translate_pending", request))
        return self.command_result or AcceptedCommand(command_name="translate_pending")

    def review_terms(self, request: ReviewTermsRequest) -> AcceptedCommand:
        self.calls.append(("review_terms", request))
        return self.command_result or AcceptedCommand(command_name="review_terms")

    def filter_noise(self, request: FilterNoiseRequest) -> TermsTableState:
        self.calls.append(("filter_noise", request))
        return self.document_state or self.project_state

    def import_terms(self, request: ImportTermsRequest) -> TermsTableState:
        self.calls.append(("import_terms", request))
        return self.project_state

    def export_terms(self, request: ExportTermsRequest) -> AcceptedCommand:
        self.calls.append(("export_terms", request))
        return self.command_result or AcceptedCommand(command_name="export_terms")

    def bulk_update_terms(self, request: BulkUpdateTermsRequest) -> BulkUpdateTermsResult:
        self.calls.append(("bulk_update_terms", request))
        state = self.document_state or self.project_state
        if request.delete:
            updated_rows = [row for row in state.rows if row.term_key not in set(request.term_keys)]
        else:
            updated_rows = [
                row.model_copy(
                    update={
                        **({"ignored": request.ignored} if request.ignored is not None else {}),
                        **({"reviewed": request.reviewed} if request.reviewed is not None else {}),
                    }
                )
                if row.term_key in request.term_keys
                else row
                for row in state.rows
            ]
        updated_state = self._with_recomputed_toolbar(state.model_copy(update={"rows": updated_rows}))
        if self.document_state is not None:
            self.document_state = updated_state
        else:
            self.project_state = updated_state
        return BulkUpdateTermsResult(affected_count=len(request.term_keys))


@dataclass
class FakeDocumentService:
    workspace: DocumentWorkspaceState
    ocr: DocumentOCRState | None = None
    translation: DocumentTranslationState | None = None
    images: DocumentImagesState | None = None
    export: DocumentExportState | None = None
    export_result: DocumentExportResult | None = None
    command_result: AcceptedCommand | None = None
    ocr_page_images: dict[int, bytes | None] = field(default_factory=dict)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def get_workspace(self, project_id: str, document_id: int) -> DocumentWorkspaceState:
        self.calls.append(("get_workspace", (project_id, document_id)))
        return self.workspace

    def get_ocr(self, project_id: str, document_id: int) -> DocumentOCRState:
        self.calls.append(("get_ocr", (project_id, document_id)))
        if self.ocr is not None:
            return self.ocr
        return DocumentOCRState(
            workspace=self.workspace.model_copy(update={"active_tab": DocumentSection.OCR}),
            pages=[],
            current_page_index=None,
            actions=DocumentOCRActions(),
        )

    def get_ocr_page_image(self, project_id: str, document_id: int, source_id: int) -> bytes | None:
        self.calls.append(("get_ocr_page_image", (project_id, document_id, source_id)))
        return self.ocr_page_images.get(source_id)

    def save_ocr(self, request: SaveOCRPageRequest) -> DocumentOCRState:
        self.calls.append(("save_ocr", request))
        return self.get_ocr(request.project_id, request.document_id)

    def run_ocr(self, request: RunOCRRequest) -> AcceptedCommand:
        self.calls.append(("run_ocr", request))
        return self.command_result or AcceptedCommand(command_name="run_ocr")

    def cancel_ocr(self, request: CancelOCRRequest) -> AcceptedCommand:
        self.calls.append(("cancel_ocr", request))
        return self.command_result or AcceptedCommand(command_name="cancel_ocr")

    def get_terms(self, project_id: str, document_id: int) -> TermsTableState:
        raise NotImplementedError

    def get_translation(
        self, project_id: str, document_id: int, *, enable_polish: bool = True
    ) -> DocumentTranslationState:
        self.calls.append(("get_translation", (project_id, document_id, enable_polish)))
        if self.translation is None:
            raise NotImplementedError
        return self.translation

    def save_translation(self, request: SaveTranslationRequest) -> DocumentTranslationState:
        self.calls.append(("save_translation", request))
        if self.translation is None:
            raise NotImplementedError
        return self.translation

    def retranslate(self, request: RetranslateRequest) -> AcceptedCommand:
        self.calls.append(("retranslate", request))
        return self.command_result or AcceptedCommand(command_name="retranslate")

    def run_translation(self, request: RunDocumentTranslationRequest) -> AcceptedCommand:
        self.calls.append(("run_translation", request))
        return self.command_result or AcceptedCommand(command_name="run_translation")

    def get_images(self, project_id: str, document_id: int) -> DocumentImagesState:
        self.calls.append(("get_images", (project_id, document_id)))
        if self.images is None:
            raise NotImplementedError
        return self.images

    def run_image_reinsertion(self, request: RunImageReinsertionRequest) -> AcceptedCommand:
        self.calls.append(("run_image_reinsertion", request))
        return self.command_result or AcceptedCommand(command_name="run_image_reinsertion")

    def cancel_image_reinsertion(self, project_id: str, task_id: str) -> AcceptedCommand:
        self.calls.append(("cancel_image_reinsertion", (project_id, task_id)))
        return self.command_result or AcceptedCommand(command_name="cancel_image_reinsertion")

    def get_export(self, project_id: str, document_id: int) -> DocumentExportState:
        self.calls.append(("get_export", (project_id, document_id)))
        if self.export is None:
            raise NotImplementedError
        return self.export

    def export_document(self, request: RunDocumentExportRequest) -> DocumentExportResult:
        self.calls.append(("export_document", request))
        if self.export_result is None:
            raise NotImplementedError
        return self.export_result


@dataclass
class FakeQueueService:
    state: QueueState
    command_result: AcceptedCommand | None = None
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def get_queue(self, *, project_id: str | None = None) -> QueueState:
        self.calls.append(("get_queue", project_id))
        return self.state

    def apply_action(self, request: QueueActionRequest) -> AcceptedCommand:
        self.calls.append(("apply_action", request))
        return self.command_result or AcceptedCommand(command_name="queue_action")


def make_fake_event_bus() -> InMemoryApplicationEventBus:
    return InMemoryApplicationEventBus()
