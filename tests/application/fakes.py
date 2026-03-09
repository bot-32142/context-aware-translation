from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionTestRequest,
    ConnectionTestResult,
    SaveConnectionRequest,
    SaveDefaultRoutesRequest,
    SetupWizardRequest,
    SetupWizardState,
    SetupWizardStep,
)
from context_aware_translation.application.contracts.common import AcceptedCommand, DocumentSection
from context_aware_translation.application.contracts.document import (
    DocumentExportResult,
    DocumentExportState,
    DocumentImagesState,
    DocumentOCRActions,
    DocumentOCRState,
    DocumentOverviewState,
    DocumentSection,
    DocumentTranslationState,
    DocumentWorkspaceState,
    RetranslateRequest,
    RunDocumentExportRequest,
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
)
from context_aware_translation.application.contracts.queue import QueueActionRequest, QueueState
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
from context_aware_translation.application.contracts.work import (
    ExportDialogState,
    ImportDocumentsRequest,
    PrepareExportRequest,
    RunExportRequest,
    WorkboardState,
)
from context_aware_translation.application.events import InMemoryApplicationEventBus


@dataclass
class FakeProjectsService:
    list_state: ProjectsScreenState
    project_summary: ProjectSummary | None = None
    create_result: ProjectSummary | None = None
    update_result: ProjectSummary | None = None
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def list_projects(self) -> ProjectsScreenState:
        self.calls.append(("list_projects", None))
        return self.list_state

    def get_project(self, project_id: str) -> ProjectSummary:
        self.calls.append(("get_project", project_id))
        return self.project_summary or self.create_result or self.update_result  # pragma: no cover - setup error if absent

    def create_project(self, request: CreateProjectRequest) -> ProjectSummary:
        self.calls.append(("create_project", request))
        return self.create_result or self.project_summary  # pragma: no cover - setup error if absent

    def update_project(self, request: UpdateProjectRequest) -> ProjectSummary:
        self.calls.append(("update_project", request))
        return self.update_result or self.project_summary  # pragma: no cover - setup error if absent

    def delete_project(self, project_id: str, *, permanent: bool = True) -> None:
        self.calls.append(("delete_project", (project_id, permanent)))


@dataclass
class FakeAppSetupService:
    state: AppSetupState
    wizard_state: SetupWizardState | None = None
    preview_state: SetupWizardState | None = None
    test_result: ConnectionTestResult | None = None
    seed_result: AcceptedCommand | None = None
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def get_state(self) -> AppSetupState:
        self.calls.append(("get_state", None))
        return self.state

    def get_wizard_state(self) -> SetupWizardState:
        self.calls.append(("get_wizard_state", None))
        return (
            self.wizard_state
            if self.wizard_state is not None
            else SetupWizardState(step=SetupWizardStep.CHOOSE_PROVIDERS)
        )

    def preview_setup_wizard(self, request: SetupWizardRequest) -> SetupWizardState:
        self.calls.append(("preview_setup_wizard", request))
        return self.preview_state if self.preview_state is not None else self.get_wizard_state()

    def save_connection(self, request: SaveConnectionRequest) -> AppSetupState:
        self.calls.append(("save_connection", request))
        return self.state

    def delete_connection(self, connection_id: str) -> AppSetupState:
        self.calls.append(("delete_connection", connection_id))
        return self.state

    def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResult:
        self.calls.append(("test_connection", request))
        if self.test_result is None:
            raise NotImplementedError
        return self.test_result

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState:
        self.calls.append(("run_setup_wizard", request))
        return self.state

    def save_default_routes(self, request: SaveDefaultRoutesRequest) -> AppSetupState:
        self.calls.append(("save_default_routes", request))
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
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def get_workboard(self, project_id: str) -> WorkboardState:
        self.calls.append(("get_workboard", project_id))
        return self.state_by_project[project_id]

    def import_documents(self, request: ImportDocumentsRequest) -> AcceptedCommand:
        self.calls.append(("import_documents", request))
        raise NotImplementedError

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

    def get_project_terms(self, project_id: str) -> TermsTableState:
        self.calls.append(("get_project_terms", project_id))
        return self.project_state

    def get_document_terms(self, project_id: str, document_id: int) -> TermsTableState:
        self.calls.append(("get_document_terms", (project_id, document_id)))
        return self.document_state or self.project_state

    def update_term(self, request: UpdateTermRequest) -> TermsTableState:
        self.calls.append(("update_term", request))
        return self.document_state or self.project_state

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


@dataclass
class FakeDocumentService:
    workspace: DocumentWorkspaceState
    overview: DocumentOverviewState | None = None
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

    def get_overview(self, project_id: str, document_id: int) -> DocumentOverviewState:
        self.calls.append(("get_overview", (project_id, document_id)))
        if self.overview is not None:
            return self.overview
        return DocumentOverviewState(workspace=self.workspace, sections=[])

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
        return self.ocr  # type: ignore[return-value]

    def run_ocr(self, request: RunOCRRequest) -> AcceptedCommand:
        self.calls.append(("run_ocr", request))
        return self.command_result or AcceptedCommand(command_name="run_ocr")

    def get_terms(self, project_id: str, document_id: int) -> TermsTableState:
        self.calls.append(("get_terms", (project_id, document_id)))
        raise NotImplementedError

    def get_translation(self, project_id: str, document_id: int) -> DocumentTranslationState:
        self.calls.append(("get_translation", (project_id, document_id)))
        if self.translation is not None:
            return self.translation
        return DocumentTranslationState(
            workspace=self.workspace.model_copy(update={"active_tab": DocumentSection.TRANSLATION}),
        )

    def save_translation(self, request: SaveTranslationRequest) -> DocumentTranslationState:
        self.calls.append(("save_translation", request))
        return self.get_translation(request.project_id, request.document_id)

    def retranslate(self, request: RetranslateRequest) -> AcceptedCommand:
        self.calls.append(("retranslate", request))
        return self.command_result or AcceptedCommand(command_name="retranslate")

    def get_images(self, project_id: str, document_id: int) -> DocumentImagesState:
        self.calls.append(("get_images", (project_id, document_id)))
        return self.images  # type: ignore[return-value]

    def run_image_reinsertion(self, request: RunImageReinsertionRequest) -> AcceptedCommand:
        self.calls.append(("run_image_reinsertion", request))
        return self.command_result or AcceptedCommand(command_name="run_image_reinsertion")

    def get_export(self, project_id: str, document_id: int) -> DocumentExportState:
        self.calls.append(("get_export", (project_id, document_id)))
        return self.export  # type: ignore[return-value]

    def export_document(self, request: RunDocumentExportRequest) -> DocumentExportResult:
        self.calls.append(("export_document", request))
        return self.export_result  # type: ignore[return-value]


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


@dataclass
class FakeApplicationServices:
    projects: FakeProjectsService | None = None
    app_setup: FakeAppSetupService | None = None
    project_setup: FakeProjectSetupService | None = None
    work: FakeWorkService | None = None
    terms: FakeTermsService | None = None
    document: FakeDocumentService | None = None
    queue: FakeQueueService | None = None


@dataclass
class FakeApplicationContext:
    services: FakeApplicationServices
    events: InMemoryApplicationEventBus = field(default_factory=InMemoryApplicationEventBus)
