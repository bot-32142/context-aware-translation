from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    ProviderCard,
    SetupWizardState,
    WizardRecommendationMode,
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
from context_aware_translation.storage.models.endpoint_profile import EndpointProfile


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
    )
    project_setup = ProjectSetupState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        available_connections=app_setup.connections,
        shared_profiles=[shared_profile],
        selected_shared_profile_id=shared_profile.profile_id,
        project_profile=project_profile,
    )
    translation = DocumentTranslationState(
        workspace=DocumentWorkspaceState(
            project=ProjectRef(project_id="proj-1", name="One Piece"),
            document=DocumentRef(document_id=4, order_index=4, label="04.png"),
            active_tab="translation",
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
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
        selected_providers=[ProviderKind.GEMINI],
        recommendation=_profile(profile_id="recommended", name="Recommended", kind=WorkflowProfileKind.SHARED),
    )

    payload = wizard.to_payload()

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
        recommendation_mode=WizardRecommendationMode.BALANCED,
    )

    route_map = {route.step_id: route for route in detail.routes}
    assert route_map[WorkflowStepId.EXTRACTOR].model == "deepseek-reasoner"
    assert route_map[WorkflowStepId.EXTRACTOR].step_config == {"max_gleaning": 1}
    assert route_map[WorkflowStepId.SUMMARIZER].model == "deepseek-chat"
    assert route_map[WorkflowStepId.GLOSSARY_TRANSLATOR].model == "gemini-2.5-flash"
    assert route_map[WorkflowStepId.GLOSSARY_TRANSLATOR].step_config["kwargs"] == {"reasoning_effort": "low"}
    assert route_map[WorkflowStepId.TRANSLATOR].model == "gemini-3.1-flash"
    assert route_map[WorkflowStepId.TRANSLATOR].step_config["kwargs"] == {"reasoning_effort": "none"}
    assert route_map[WorkflowStepId.TRANSLATOR].step_config["batch_size"] == 100
    assert route_map[WorkflowStepId.POLISH].model == "gemini-3.1-pro"
    assert route_map[WorkflowStepId.POLISH].step_config["kwargs"] == {"reasoning_effort": "medium"}
    assert route_map[WorkflowStepId.POLISH].step_config["batch_size"] == 100
    assert route_map[WorkflowStepId.REVIEWER].model == "gemini-2.5-pro"
    assert route_map[WorkflowStepId.OCR].model == "gemini-3.1-flash"
    assert route_map[WorkflowStepId.OCR].step_config["kwargs"] == {"reasoning_effort": "none"}
    assert route_map[WorkflowStepId.IMAGE_REEMBEDDING].model == "gemini-3-pro-image-preview"
    assert route_map[WorkflowStepId.IMAGE_REEMBEDDING].step_config["backend"] == "gemini"
    assert route_map[WorkflowStepId.IMAGE_REEMBEDDING].step_config == {"backend": "gemini"}
    assert route_map[WorkflowStepId.MANGA_TRANSLATOR].model == "gemini-3.1-flash"
    assert route_map[WorkflowStepId.MANGA_TRANSLATOR].step_config["kwargs"] == {"reasoning_effort": "none"}


def test_recommended_workflow_profile_skips_unsupported_openai_ocr_reasoning_none() -> None:
    detail = recommended_workflow_profile_from_drafts(
        [ConnectionDraft(display_name="OpenAI", provider=ProviderKind.OPENAI, api_key="okey")],
        name="Wizard Profile",
        target_language="English",
        recommendation_mode=WizardRecommendationMode.BALANCED,
    )

    route_map = {route.step_id: route for route in detail.routes}
    assert route_map[WorkflowStepId.EXTRACTOR].model == "o4-mini"
    assert route_map[WorkflowStepId.EXTRACTOR].step_config == {"max_gleaning": 1}
    assert route_map[WorkflowStepId.OCR].model == "gpt-4.1-mini"
    assert route_map[WorkflowStepId.OCR].step_config == {}
    assert route_map[WorkflowStepId.TRANSLATOR].model == "gpt-4.1"
    assert route_map[WorkflowStepId.TRANSLATOR].step_config == {}
    assert route_map[WorkflowStepId.POLISH].model == "o4-mini"
    assert route_map[WorkflowStepId.POLISH].step_config["kwargs"] == {"reasoning_effort": "medium"}
    assert route_map[WorkflowStepId.IMAGE_REEMBEDDING].step_config == {"backend": "openai"}


def test_recommended_workflow_profile_quality_mode_prefers_best_models_and_high_reasoning() -> None:
    detail = recommended_workflow_profile_from_drafts(
        [
            ConnectionDraft(display_name="Gemini", provider=ProviderKind.GEMINI, api_key="gkey"),
            ConnectionDraft(display_name="OpenAI", provider=ProviderKind.OPENAI, api_key="okey"),
            ConnectionDraft(display_name="DeepSeek", provider=ProviderKind.DEEPSEEK, api_key="dkey"),
        ],
        name="Wizard Profile",
        target_language="English",
        recommendation_mode=WizardRecommendationMode.QUALITY,
    )

    route_map = {route.step_id: route for route in detail.routes}
    assert route_map[WorkflowStepId.TRANSLATOR].model == "gemini-3.1-pro"
    assert route_map[WorkflowStepId.TRANSLATOR].step_config["kwargs"] == {"reasoning_effort": "high"}
    assert route_map[WorkflowStepId.POLISH].model == "gemini-3.1-pro"
    assert route_map[WorkflowStepId.POLISH].step_config["kwargs"] == {"reasoning_effort": "high"}
    assert route_map[WorkflowStepId.MANGA_TRANSLATOR].model == "gemini-3.1-pro"
    assert route_map[WorkflowStepId.MANGA_TRANSLATOR].step_config["kwargs"] == {"reasoning_effort": "high"}


def test_recommended_workflow_profile_does_not_force_deepseek_reasoning_effort() -> None:
    detail = recommended_workflow_profile_from_drafts(
        [ConnectionDraft(display_name="DeepSeek", provider=ProviderKind.DEEPSEEK, api_key="dkey")],
        name="Wizard Profile",
        target_language="English",
        recommendation_mode=WizardRecommendationMode.QUALITY,
    )

    route_map = {route.step_id: route for route in detail.routes}
    assert route_map[WorkflowStepId.EXTRACTOR].model == "deepseek-reasoner"
    assert route_map[WorkflowStepId.EXTRACTOR].step_config == {"max_gleaning": 1}
    assert route_map[WorkflowStepId.GLOSSARY_TRANSLATOR].model == "deepseek-chat"
    assert route_map[WorkflowStepId.GLOSSARY_TRANSLATOR].step_config == {}
    assert route_map[WorkflowStepId.TRANSLATOR].model == "deepseek-reasoner"
    assert route_map[WorkflowStepId.TRANSLATOR].step_config == {}
    assert route_map[WorkflowStepId.POLISH].model == "deepseek-reasoner"
    assert route_map[WorkflowStepId.POLISH].step_config == {}


def test_recommended_workflow_profile_budget_mode_uses_cheaper_anthropic_translator() -> None:
    detail = recommended_workflow_profile_from_drafts(
        [ConnectionDraft(display_name="Anthropic", provider=ProviderKind.ANTHROPIC, api_key="akey")],
        name="Wizard Profile",
        target_language="English",
        recommendation_mode=WizardRecommendationMode.BUDGET,
    )

    route_map = {route.step_id: route for route in detail.routes}
    assert route_map[WorkflowStepId.TRANSLATOR].model == "claude-3-5-haiku-latest"
    assert route_map[WorkflowStepId.TRANSLATOR].step_config["kwargs"] == {"reasoning_effort": "low"}
    assert route_map[WorkflowStepId.POLISH].model == "claude-3-5-sonnet-latest"
    assert route_map[WorkflowStepId.POLISH].step_config["kwargs"] == {"reasoning_effort": "low"}


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
                term_type="character",
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
            "kwargs": {"reasoning_effort": "none"},
        },
        "translator_config": {
            "endpoint_profile": "conn-openai",
            "temperature": 0.4,
            "timeout": 180,
            "concurrency": 2,
            "max_tokens_per_llm_call": 6000,
            "chunk_size": 1200,
            "kwargs": {"reasoning_effort": "low"},
        },
        "polish_config": {
            "endpoint_profile": "conn-gemini",
            "temperature": 0.1,
            "timeout": 240,
            "kwargs": {"reasoning_effort": "medium"},
        },
        "image_reembedding_config": {
            "endpoint_profile": "conn-gemini",
            "backend": "openai",
        },
        "translator_batch_config": {
            "batch_size": 50,
        },
        "polish_batch_config": {
            "batch_size": 25,
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
        connection_base_url_by_id={
            "conn-gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "conn-openai": "https://api.openai.com/v1",
        },
    )

    ocr_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.OCR)
    assert ocr_route.step_config == {
        "ocr_dpi": 200,
        "strip_llm_artifacts": False,
        "kwargs": {"reasoning_effort": "none"},
    }

    translator_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.TRANSLATOR)
    assert translator_route.step_config == {
        "temperature": 0.4,
        "timeout": 180,
        "concurrency": 2,
        "max_tokens_per_llm_call": 6000,
        "chunk_size": 1200,
        "kwargs": {"reasoning_effort": "low"},
    }
    polish_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.POLISH)
    assert polish_route.step_config == {
        "temperature": 0.1,
        "timeout": 240,
        "kwargs": {"reasoning_effort": "medium"},
    }

    payload = build_workflow_profile_payload(base_config=None, profile=detail)
    assert payload["ocr_config"]["ocr_dpi"] == 200
    assert payload["ocr_config"]["strip_llm_artifacts"] is False
    assert payload["ocr_config"]["kwargs"] == {"reasoning_effort": "none"}
    assert payload["translator_config"]["temperature"] == 0.4
    assert payload["translator_config"]["timeout"] == 180
    assert payload["translator_config"]["concurrency"] == 2
    assert payload["translator_config"]["chunk_size"] == 1200
    assert payload["translator_config"]["kwargs"] == {"reasoning_effort": "low"}
    assert payload["polish_config"]["temperature"] == 0.1
    assert payload["polish_config"]["timeout"] == 240
    assert payload["polish_config"]["kwargs"] == {"reasoning_effort": "medium"}
    assert payload["image_reembedding_config"]["backend"] == "openai"
    assert "translator_batch_config" not in payload
    assert "polish_batch_config" not in payload


def test_build_workflow_profile_detail_does_not_surface_batch_size_for_gemini_named_custom_endpoint() -> None:
    config = {
        "translation_target_language": "English",
        "translator_config": {
            "endpoint_profile": "conn-openrouter",
            "model": "gemini-2.5-pro",
        },
        "polish_config": {
            "endpoint_profile": "conn-openrouter",
            "model": "gemini-2.5-pro",
        },
        "translator_batch_config": {
            "batch_size": 50,
        },
        "polish_batch_config": {
            "batch_size": 25,
        },
    }

    detail = build_workflow_profile_detail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        config=config,
        connection_name_by_id={"conn-openrouter": "OpenRouter"},
        connection_model_by_id={"conn-openrouter": "gemini-2.5-pro"},
        connection_base_url_by_id={"conn-openrouter": "https://openrouter.ai/api/v1"},
    )

    translator_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.TRANSLATOR)
    polish_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.POLISH)

    assert translator_route.connection_base_url == "https://openrouter.ai/api/v1"
    assert "batch_size" not in translator_route.step_config
    assert "batch_size" not in polish_route.step_config


def test_build_workflow_profile_detail_does_not_fallback_polish_batch_size_to_translator_batch_size() -> None:
    config = {
        "translation_target_language": "English",
        "translator_config": {
            "endpoint_profile": "conn-gemini",
            "model": "gemini-2.5-pro",
        },
        "polish_config": {
            "endpoint_profile": "conn-gemini",
            "model": "gemini-2.5-pro",
        },
        "translator_batch_config": {
            "batch_size": 50,
        },
    }

    detail = build_workflow_profile_detail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        config=config,
        connection_name_by_id={"conn-gemini": "Gemini"},
        connection_model_by_id={"conn-gemini": "gemini-2.5-pro"},
        connection_base_url_by_id={"conn-gemini": "https://generativelanguage.googleapis.com/v1beta/openai/"},
    )

    translator_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.TRANSLATOR)
    polish_route = next(route for route in detail.routes if route.step_id is WorkflowStepId.POLISH)

    assert translator_route.step_config["batch_size"] == 50
    assert "batch_size" not in polish_route.step_config
