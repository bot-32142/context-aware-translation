from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    CapabilityCard,
    ConnectionStatus,
    ConnectionSummary,
    DefaultRoute,
    ProviderCard,
    SetupWizardState,
    SetupWizardStep,
)
from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
    CapabilityAvailability,
    CapabilityCode,
    DocumentRef,
    DocumentRowActionKind,
    NavigationTarget,
    NavigationTargetKind,
    PresetCode,
    ProjectRef,
    ProviderKind,
    QueueActionKind,
    QueueStatus,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import (
    DocumentExportState,
    DocumentTranslationState,
    DocumentWorkspaceState,
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.contracts.project_setup import (
    ProjectCapabilityBinding,
    ProjectCapabilityCard,
    ProjectConnectionOption,
    ProjectSetupState,
)
from context_aware_translation.application.contracts.queue import QueueItem, QueueState
from context_aware_translation.application.contracts.terms import (
    TermsScope,
    TermsScopeKind,
    TermsTableState,
    TermStatus,
    TermTableRow,
)
from context_aware_translation.application.contracts.work import (
    ContextFrontierState,
    DocumentRowAction,
    WorkboardState,
    WorkDocumentRow,
)
from context_aware_translation.application.errors import ApplicationError, ApplicationErrorCode, ApplicationErrorPayload


def test_workboard_state_serializes_cleanly() -> None:
    project = ProjectRef(project_id="proj-1", name="One Piece")
    document = DocumentRef(document_id=4, order_index=4, label="04.png")
    blocker = BlockerInfo(
        code=BlockerCode.NEEDS_REVIEW,
        message="Review this page before continuing.",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_OCR,
            project_id="proj-1",
            document_id=4,
        ),
    )
    row = WorkDocumentRow(
        document=document,
        status=SurfaceStatus.BLOCKED,
        state_summary="Needs OCR review",
        blocker=blocker,
        primary_action=DocumentRowAction(
            kind=DocumentRowActionKind.OPEN_OCR,
            label="Open OCR",
            target=NavigationTarget(
                kind=NavigationTargetKind.DOCUMENT_OCR,
                project_id="proj-1",
                document_id=4,
            ),
        ),
    )
    state = WorkboardState(
        project=project,
        context_frontier=ContextFrontierState(summary="Context ready through 03", blocker=blocker),
        rows=[row],
        setup_blocker=None,
    )

    payload = state.model_dump(mode="json")

    assert payload["project"]["project_id"] == "proj-1"
    assert payload["rows"][0]["status"] == "blocked"
    assert payload["rows"][0]["primary_action"]["kind"] == "open_ocr"
    assert payload["rows"][0]["blocker"]["code"] == "needs_review"


def test_setup_and_document_contracts_are_json_serializable() -> None:
    app_setup = AppSetupState(
        connections=[
            ConnectionSummary(
                connection_id="conn-gemini",
                display_name="Gemini",
                provider=ProviderKind.GEMINI,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                default_model="gemini-3-flash-preview",
                status=ConnectionStatus.READY,
                capabilities=[CapabilityCode.IMAGE_TEXT_READING, CapabilityCode.IMAGE_EDITING],
            )
        ],
        capabilities=[
            CapabilityCard(
                capability=CapabilityCode.IMAGE_TEXT_READING,
                availability=CapabilityAvailability.READY,
                message="Gemini ready",
                connection_id="conn-gemini",
                connection_label="Gemini",
            )
        ],
        default_routes=[
            DefaultRoute(
                capability=CapabilityCode.IMAGE_TEXT_READING,
                connection_id="conn-gemini",
                connection_label="Gemini",
            )
        ],
        requires_wizard=False,
    )
    project_setup = ProjectSetupState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        target_language="English",
        preset=PresetCode.BALANCED,
        bindings=[
            ProjectCapabilityBinding(
                capability=CapabilityCode.IMAGE_TEXT_READING,
                availability=CapabilityAvailability.READY,
                source="app_default",
                connection_id="conn-gemini",
                connection_label="Gemini",
            )
        ],
        capability_cards=[
            ProjectCapabilityCard(
                capability=CapabilityCode.IMAGE_TEXT_READING,
                availability=CapabilityAvailability.READY,
                source="app_default",
                connection_id="conn-gemini",
                connection_label="Gemini",
                options=[
                    ProjectConnectionOption(
                        connection_id="conn-gemini",
                        connection_label="Gemini",
                    )
                ],
            )
        ],
    )
    translation = DocumentTranslationState(
        workspace=DocumentWorkspaceState(
            project=ProjectRef(project_id="proj-1", name="One Piece"),
            document=DocumentRef(document_id=4, order_index=4, label="04.png"),
            active_tab="translation",
            available_tabs=["overview", "ocr", "terms", "translation", "images", "export"],
        ),
        units=[
            TranslationUnitState(
                unit_id="chunk-1",
                unit_kind=TranslationUnitKind.CHUNK,
                label="Chunk 1",
                status=SurfaceStatus.READY,
                source_text="全員さっさと降りろ!!!",
                translated_text="Everyone, get down now!!!",
                line_count=1,
            )
        ],
        current_unit_id="chunk-1",
    )
    export_state = DocumentExportState(
        workspace=translation.workspace,
        can_export=True,
        available_formats=[],
        default_output_path="/tmp/out.epub",
    )

    assert app_setup.model_dump(mode="json")["connections"][0]["provider"] == "gemini"
    assert project_setup.model_dump(mode="json")["preset"] == "balanced"
    assert translation.model_dump(mode="json")["workspace"]["active_tab"] == "translation"
    assert export_state.model_dump(mode="json")["can_export"] is True


def test_setup_wizard_state_serializes_for_provider_first_flow() -> None:
    wizard = SetupWizardState(
        step=SetupWizardStep.ENTER_KEYS,
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
                recommended_for=[
                    CapabilityCode.IMAGE_TEXT_READING,
                    CapabilityCode.IMAGE_EDITING,
                ],
            )
        ],
        selected_providers=[ProviderKind.GEMINI],
    )

    payload = wizard.to_payload()

    assert payload["step"] == "enter_keys"
    assert payload["available_providers"][0]["provider"] == "gemini"


def test_terms_queue_and_errors_expose_ui_safe_contracts() -> None:
    terms = TermsTableState(
        scope=TermsScope(
            kind=TermsScopeKind.DOCUMENT,
            project=ProjectRef(project_id="proj-1", name="One Piece"),
            document=DocumentRef(document_id=4, order_index=4, label="04.png"),
        ),
        rows=[
            TermTableRow(
                term_id=1,
                term_key="ニカ",
                term="ニカ",
                translation="Nika",
                description="Sun god reference",
                occurrences=3,
                votes=2,
                reviewed=True,
                status=TermStatus.READY,
            )
        ],
    )
    queue = QueueState(
        items=[
            QueueItem(
                queue_item_id="task-1",
                title="Read text from images",
                project_id="proj-1",
                document_id=4,
                status=QueueStatus.RUNNING,
                related_target=NavigationTarget(
                    kind=NavigationTargetKind.DOCUMENT_OCR,
                    project_id="proj-1",
                    document_id=4,
                ),
                available_actions=[QueueActionKind.CANCEL, QueueActionKind.OPEN_RELATED_ITEM],
            )
        ]
    )
    receipt = AcceptedCommand(
        command_name="run_ocr",
        command_id="cmd-1",
        queue_item_id="task-1",
        message=UserMessage(severity=UserMessageSeverity.INFO, text="OCR queued."),
    )
    error = ApplicationError(
        ApplicationErrorPayload(
            code=ApplicationErrorCode.BLOCKED,
            message="Review this page before continuing.",
            details={"document_id": 4},
        )
    )

    assert terms.model_dump(mode="json")["scope"]["kind"] == "document"
    assert queue.model_dump(mode="json")["items"][0]["available_actions"] == ["cancel", "open_related_item"]
    assert receipt.model_dump(mode="json")["message"]["severity"] == "info"
    assert error.payload.code == ApplicationErrorCode.BLOCKED
