from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    ProviderCard,
    SetupWizardState,
    SetupWizardStep,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
    DocumentRef,
    DocumentRowActionKind,
    DocumentSection,
    NavigationTarget,
    NavigationTargetKind,
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
    DocumentImagesState,
    DocumentImagesToolbarState,
    DocumentTranslationState,
    DocumentWorkspaceState,
    ImageAssetState,
    TranslationUnitActionState,
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.contracts.project_setup import ProjectSetupState
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
from context_aware_translation.application.runtime import (
    build_connection_summary,
    build_workflow_profile_detail,
    build_workflow_profile_payload,
    recommended_workflow_profile_from_drafts,
)
from context_aware_translation.storage.endpoint_profile import EndpointProfile


def _profile(*, profile_id: str, name: str, kind: WorkflowProfileKind) -> WorkflowProfileDetail:
    return WorkflowProfileDetail(
        profile_id=profile_id,
        name=name,
        kind=kind,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label="Translator",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            ),
            WorkflowStepRoute(
                step_id=WorkflowStepId.OCR,
                step_label="OCR",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            ),
        ],
        is_default=(kind is WorkflowProfileKind.SHARED),
    )


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
    shared_profile = _profile(profile_id="profile:shared", name="Recommended", kind=WorkflowProfileKind.SHARED)
    project_profile = _profile(
        profile_id="project:proj-1", name="One Piece profile", kind=WorkflowProfileKind.PROJECT_SPECIFIC
    )
    app_setup = AppSetupState(
        connections=[
            ConnectionSummary(
                connection_id="conn-gemini",
                display_name="Gemini",
                provider=ProviderKind.GEMINI,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                default_model="gemini-3-flash-preview",
                status=ConnectionStatus.READY,
            )
        ],
        shared_profiles=[shared_profile],
        default_profile_id=shared_profile.profile_id,
        requires_wizard=False,
    )
    project_setup = ProjectSetupState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        available_connections=app_setup.connections,
        shared_profiles=[shared_profile],
        selected_shared_profile_id=shared_profile.profile_id,
        selected_shared_profile=shared_profile,
        project_profile=project_profile,
    )
    translation = DocumentTranslationState(
        workspace=DocumentWorkspaceState(
            project=ProjectRef(project_id="proj-1", name="One Piece"),
            document=DocumentRef(document_id=4, order_index=4, label="04.png"),
            active_tab="translation",
            available_tabs=["ocr", "terms", "translation", "images", "export"],
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
                actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
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
    images_state = DocumentImagesState(
        workspace=translation.workspace.model_copy(update={"active_tab": DocumentSection.IMAGES}),
        assets=[
            ImageAssetState(
                asset_id="source-1",
                label="Image 1",
                status=SurfaceStatus.READY,
                source_id=10,
                translated_text="Everyone, get down now!!!",
                can_run=True,
            )
        ],
        toolbar=DocumentImagesToolbarState(can_run_pending=True),
        active_task_id=None,
    )

    assert app_setup.model_dump(mode="json")["connections"][0]["provider"] == "gemini"
    assert project_setup.model_dump(mode="json")["project_profile"]["kind"] == "project_specific"
    assert translation.model_dump(mode="json")["workspace"]["active_tab"] == "translation"
    assert translation.model_dump(mode="json")["units"][0]["actions"]["can_retranslate"] is True
    assert export_state.model_dump(mode="json")["can_export"] is True
    assert images_state.model_dump(mode="json")["assets"][0]["translated_text"] == "Everyone, get down now!!!"


def test_managed_connection_names_are_hidden_from_display() -> None:
    summary = build_connection_summary(
        EndpointProfile(
            profile_id="conn-1",
            name="recommended-Gemini 2.5 Pro",
            created_at=0.0,
            updated_at=0.0,
            api_key="secret",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-2.5-pro",
        )
    )

    assert summary.display_name == "Gemini 2.5 Pro"
    assert summary.is_managed is True


def test_setup_wizard_state_serializes_for_provider_first_flow() -> None:
    wizard = SetupWizardState(
        step=SetupWizardStep.CHOOSE_PROVIDERS,
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
        selected_providers=[ProviderKind.GEMINI],
        profile_name="Team Default",
        recommendation=_profile(profile_id="recommended", name="Recommended", kind=WorkflowProfileKind.SHARED),
    )

    payload = wizard.to_payload()

    assert payload["step"] == "choose_providers"
    assert payload["profile_name"] == "Team Default"
    assert payload["available_providers"][0]["provider"] == "gemini"
    assert payload["recommendation"]["routes"][0]["step_id"] == "translator"


def test_recommended_workflow_profile_uses_ranked_step_rules() -> None:
    detail = recommended_workflow_profile_from_drafts(
        [
            ConnectionDraft(display_name="Gemini", provider=ProviderKind.GEMINI, api_key="gkey"),
            ConnectionDraft(display_name="DeepSeek", provider=ProviderKind.DEEPSEEK, api_key="dkey"),
            ConnectionDraft(display_name="OpenAI", provider=ProviderKind.OPENAI, api_key="okey"),
        ],
        name="Wizard Profile",
        target_language="English",
    )

    route_map = {route.step_id: route for route in detail.routes}
    assert route_map[WorkflowStepId.EXTRACTOR].model == "deepseek-chat"
    assert route_map[WorkflowStepId.SUMMARIZER].model == "deepseek-chat"
    assert route_map[WorkflowStepId.GLOSSARY_TRANSLATOR].model == "gemini-2.5-flash"
    assert route_map[WorkflowStepId.TRANSLATOR].model == "gemini-2.5-pro"
    assert route_map[WorkflowStepId.REVIEWER].model == "gemini-2.5-pro"
    assert route_map[WorkflowStepId.OCR].model == "gemini-3-flash-preview"
    assert route_map[WorkflowStepId.IMAGE_REEMBEDDING].model == "gemini-3.1-flash-image-preview"
    assert route_map[WorkflowStepId.IMAGE_REEMBEDDING].step_config["backend"] == "gemini"
    assert route_map[WorkflowStepId.MANGA_TRANSLATOR].model == "gemini-2.5-pro"
    assert route_map[WorkflowStepId.TRANSLATOR_BATCH].model == "gemini-2.5-pro"


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


def test_workflow_profile_round_trips_step_advanced_config() -> None:
    config = {
        "translation_target_language": "English",
        "ocr_config": {
            "endpoint_profile": "conn-gemini",
            "ocr_dpi": 200,
            "strip_llm_artifacts": False,
        },
        "translator_config": {
            "endpoint_profile": "conn-openai",
            "max_tokens_per_llm_call": 6000,
            "chunk_size": 1200,
        },
        "image_reembedding_config": {
            "endpoint_profile": "conn-gemini",
            "backend": "openai",
        },
        "translator_batch_config": {
            "provider": "gemini_ai_studio",
            "api_key": "secret",
            "model": "gemini-2.5-flash",
            "batch_size": 50,
            "thinking_mode": "medium",
        },
    }

    detail = build_workflow_profile_detail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        config=config,
        connection_name_by_id={
            "conn-gemini": "Gemini",
            "conn-openai": "OpenAI",
        },
        connection_model_by_id={
            "conn-gemini": "gemini-3-flash-preview",
            "conn-openai": "gpt-4.1-mini",
        },
    )

    ocr_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.OCR)
    assert ocr_route.step_config == {
        "ocr_dpi": 200,
        "strip_llm_artifacts": False,
    }

    batch_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.TRANSLATOR_BATCH)
    assert batch_route.model == "gemini-2.5-flash"
    assert batch_route.step_config == {
        "provider": "gemini_ai_studio",
        "api_key": "secret",
        "batch_size": 50,
        "thinking_mode": "medium",
    }

    payload = build_workflow_profile_payload(base_config=None, profile=detail)
    assert payload["ocr_config"]["ocr_dpi"] == 200
    assert payload["ocr_config"]["strip_llm_artifacts"] is False
    assert payload["translator_config"]["chunk_size"] == 1200
    assert payload["image_reembedding_config"]["backend"] == "openai"
    assert payload["translator_batch_config"]["model"] == "gemini-2.5-flash"
    assert payload["translator_batch_config"]["thinking_mode"] == "medium"
