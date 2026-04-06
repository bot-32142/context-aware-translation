from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from PySide6.QtWidgets import QApplication

from context_aware_translation.application.composition import build_application_context
from context_aware_translation.application.contracts.app_setup import (
    ConnectionDraft,
    SaveConnectionRequest,
    SetupWizardRequest,
    WorkflowProfileKind,
)
from context_aware_translation.application.contracts.common import ProviderKind
from context_aware_translation.application.contracts.project_setup import SaveProjectSetupRequest
from context_aware_translation.application.contracts.projects import CreateProjectRequest, UpdateProjectRequest
from context_aware_translation.application.contracts.terms import UpdateTermRequest
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.schema.book_db import TermRecord


def _ensure_qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


def _build_configured_context(tmp_path: Path):
    context = build_application_context(library_root=tmp_path)
    context.services.app_setup.run_setup_wizard(
        SetupWizardRequest(
            providers=[ProviderKind.OPENAI],
            connections=[
                ConnectionDraft(
                    display_name="OpenAI",
                    provider=ProviderKind.OPENAI,
                    api_key="test-key",
                )
            ],
        )
    )
    return context


def _configure_project_for_task_preflights(context, project_id: str) -> None:  # noqa: ANN001
    endpoint = context.runtime.book_manager.create_endpoint_profile(
        name=f"Test Endpoint {project_id}",
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1-mini",
    )
    config = context.runtime.get_effective_config_payload(project_id)
    for key in (
        "extractor_config",
        "summarizor_config",
        "glossary_config",
        "translator_config",
        "review_config",
        "ocr_config",
        "image_reembedding_config",
        "manga_translator_config",
    ):
        config.setdefault(key, {})
        config[key]["endpoint_profile"] = endpoint.profile_id
    context.runtime.book_manager.set_book_custom_config(project_id, config)


def test_build_application_context_exposes_services(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        setup_state = context.services.app_setup.get_state()
        assert setup_state.connections == []
        assert setup_state.shared_profiles == []
        assert context.services.app_setup.get_wizard_state().available_providers
    finally:
        context.close()


def test_projects_service_can_create_and_list_projects(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="One Piece", target_language="English")
        )
        listed = context.services.projects.list_projects()

        assert created.project.name == "One Piece"
        assert any(item.project.project_id == created.project.project_id for item in listed.items)
    finally:
        context.close()


def test_projects_service_creates_project_with_selected_workflow_profile(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        default_profile = context.runtime.book_manager.list_profiles()[0]
        alternate_config = dict(default_profile.config)
        alternate_config["translation_target_language"] = "Japanese"
        alternate_profile = context.runtime.book_manager.create_profile(
            name="Japanese Profile",
            config=alternate_config,
        )

        created = context.services.projects.create_project(
            CreateProjectRequest(name="Profile Pick", workflow_profile_id=alternate_profile.profile_id)
        )
        project_id = created.project.project_id
        book = context.runtime.get_book(project_id)
        project_setup = context.services.project_setup.get_state(project_id)

        assert book.profile_id == alternate_profile.profile_id
        assert created.target_language == "Japanese"
        assert project_setup.selected_shared_profile_id == alternate_profile.profile_id
    finally:
        context.close()


def test_projects_service_preserves_selected_profile_when_overriding_target_language(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        shared_profile = context.runtime.book_manager.list_profiles()[0]

        created = context.services.projects.create_project(
            CreateProjectRequest(
                name="Profile Override",
                workflow_profile_id=shared_profile.profile_id,
                target_language="Chinese",
            )
        )
        project_id = created.project.project_id
        book = context.runtime.get_book(project_id)
        config = context.runtime.get_effective_config_payload(project_id)
        project_setup = context.services.project_setup.get_state(project_id)

        assert book.profile_id is None
        assert config["translation_target_language"] == "Chinese"
        assert config["_ui_source_profile_id"] == shared_profile.profile_id
        assert project_setup.selected_shared_profile_id == shared_profile.profile_id
    finally:
        context.close()


def test_projects_service_preserves_source_profile_when_editing_target_language(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        shared_profile = context.runtime.book_manager.list_profiles()[0]
        created = context.services.projects.create_project(CreateProjectRequest(name="Edit Target"))
        project_id = created.project.project_id

        context.services.projects.update_project(UpdateProjectRequest(project_id=project_id, target_language="Chinese"))

        book = context.runtime.get_book(project_id)
        config = context.runtime.get_effective_config_payload(project_id)
        project_setup = context.services.project_setup.get_state(project_id)

        assert book.profile_id is None
        assert config["_ui_source_profile_id"] == shared_profile.profile_id
        assert project_setup.selected_shared_profile_id == shared_profile.profile_id
    finally:
        context.close()


def test_project_setup_and_work_queries_use_service_boundary(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Manga Test", target_language="English")
        )
        project_id = created.project.project_id

        project_setup = context.services.project_setup.get_state(project_id)
        workboard = context.services.work.get_workboard(project_id)

        assert project_setup.project.project_id == project_id
        assert project_setup.selected_shared_profile_id is not None or project_setup.project_profile is not None
        assert workboard.project.project_id == project_id
        assert workboard.rows == []
    finally:
        context.close()


def test_workboard_builds_labels_without_per_document_metadata_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Manga Test", target_language="English")
        )
        project_id = created.project.project_id

        with context.runtime.open_book_db(project_id) as dbx:
            first_doc = dbx.document_repo.insert_document("manga")
            dbx.document_repo.insert_document_source(
                first_doc,
                0,
                "image",
                relative_path="chapter-01/04.png",
                is_ocr_completed=True,
            )
            second_doc = dbx.document_repo.insert_document("manga")
            dbx.document_repo.insert_document_source(
                second_doc,
                0,
                "image",
                relative_path="chapter-01/05.png",
                is_ocr_completed=True,
            )

        def _unexpected_metadata_call(_self, document_id: int):  # noqa: ANN001
            raise AssertionError(f"unexpected metadata fetch for document {document_id}")

        monkeypatch.setattr(DocumentRepository, "get_document_sources_metadata", _unexpected_metadata_call)

        workboard = context.services.work.get_workboard(project_id)

        assert [row.document.label for row in workboard.rows] == ["04.png", "05.png"]
    finally:
        context.close()


def test_app_setup_preview_exposes_recommended_profile(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        preview = context.services.app_setup.preview_setup_wizard(
            SetupWizardRequest(
                providers=[ProviderKind.GEMINI, ProviderKind.DEEPSEEK],
                connections=[
                    ConnectionDraft(
                        display_name="Gemini",
                        provider=ProviderKind.GEMINI,
                        api_key="secret",
                        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                        default_model="gemini-3.1-flash",
                    ),
                    ConnectionDraft(
                        display_name="DeepSeek",
                        provider=ProviderKind.DEEPSEEK,
                        api_key="secret",
                        base_url="https://api.deepseek.com",
                        default_model="deepseek-chat",
                    ),
                ],
                target_language="Japanese",
            )
        )

        assert preview.test_results
        assert preview.recommendation is not None
        assert preview.recommendation.routes
        assert preview.recommendation.name == "Recommended"
        assert preview.recommendation.target_language == "Japanese"
    finally:
        context.close()


def test_setup_wizard_creates_curated_connections_and_named_profile(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        context.services.app_setup.run_setup_wizard(
            SetupWizardRequest(
                providers=[ProviderKind.GEMINI, ProviderKind.DEEPSEEK],
                profile_name="Team Default",
                target_language="Japanese",
                connections=[
                    ConnectionDraft(display_name="Gemini", provider=ProviderKind.GEMINI, api_key="gkey"),
                    ConnectionDraft(display_name="DeepSeek", provider=ProviderKind.DEEPSEEK, api_key="dkey"),
                ],
            )
        )

        endpoint_profiles = context.runtime.book_manager.list_endpoint_profiles()
        connection_names = {profile.name for profile in endpoint_profiles}
        assert "recommended-Gemini 2.5 Pro" in connection_names
        assert "recommended-Gemini 3.1 Pro" in connection_names
        assert "recommended-Gemini 3 Pro Image Preview" in connection_names
        assert "recommended-DeepSeek Chat" in connection_names
        assert "recommended-DeepSeek Reasoner" in connection_names
        assert next(profile for profile in endpoint_profiles if profile.name == "recommended-DeepSeek Chat").concurrency == 15
        assert (
            next(profile for profile in endpoint_profiles if profile.name == "recommended-DeepSeek Reasoner").concurrency
            == 15
        )

        created_profile = next(
            profile for profile in context.runtime.book_manager.list_profiles() if profile.name == "Team Default"
        )
        detail = context.services.app_setup.get_state()
        assert any(profile.name == "Team Default" for profile in detail.shared_profiles)
        assert created_profile.is_default is True
        assert created_profile.config["translation_target_language"] == "Japanese"
        assert created_profile.config["glossary_config"]["kwargs"] == {"reasoning_effort": "low"}
        assert created_profile.config["translator_config"]["model"] == "gemini-3.1-pro"
        assert created_profile.config["translator_config"]["kwargs"] == {"reasoning_effort": "none"}
        assert created_profile.config["polish_config"]["model"] == "gemini-3.1-pro"
        assert created_profile.config["polish_config"]["kwargs"] == {"reasoning_effort": "medium"}
        assert created_profile.config["ocr_config"]["kwargs"] == {"reasoning_effort": "none"}
        assert created_profile.config["image_reembedding_config"] == {
            "endpoint_profile": next(
                profile.profile_id
                for profile in endpoint_profiles
                if profile.name == "recommended-Gemini 3 Pro Image Preview"
            ),
            "model": "gemini-3-pro-image-preview",
            "backend": "gemini",
        }
        assert created_profile.config["manga_translator_config"]["model"] == "gemini-2.5-pro"
        assert created_profile.config["manga_translator_config"]["kwargs"] == {"reasoning_effort": "none"}
        assert created_profile.config["translator_batch_config"]["batch_size"] == 100
        assert created_profile.config["polish_batch_config"]["batch_size"] == 100
        assert (
            next(profile for profile in endpoint_profiles if profile.name == "recommended-Gemini 3.1 Pro").api_key
            == "gkey"
        )
        assert (
            next(profile for profile in endpoint_profiles if profile.name == "recommended-DeepSeek Chat").api_key
            == "dkey"
        )
        assert (
            next(profile for profile in endpoint_profiles if profile.name == "recommended-Gemini 3.1 Flash").timeout
            == 300
        )
    finally:
        context.close()


def test_setup_wizard_rerun_updates_existing_managed_connections_and_profile(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        context.services.app_setup.run_setup_wizard(
            SetupWizardRequest(
                providers=[ProviderKind.GEMINI, ProviderKind.DEEPSEEK],
                profile_name="Team Default",
                connections=[
                    ConnectionDraft(
                        display_name="Gemini",
                        provider=ProviderKind.GEMINI,
                        api_key="gkey-1",
                        description="Initial wizard settings",
                        token_limit=1000,
                    ),
                    ConnectionDraft(
                        display_name="DeepSeek",
                        provider=ProviderKind.DEEPSEEK,
                        api_key="dkey-1",
                        description="Initial wizard settings",
                        token_limit=1000,
                    ),
                ],
            )
        )

        initial_connection_ids = {
            profile.name: profile.profile_id
            for profile in context.runtime.book_manager.list_endpoint_profiles()
            if profile.name.startswith("recommended-")
        }
        initial_profile = next(
            profile for profile in context.runtime.book_manager.list_profiles() if profile.name == "Team Default"
        )

        context.services.app_setup.run_setup_wizard(
            SetupWizardRequest(
                providers=[ProviderKind.GEMINI, ProviderKind.DEEPSEEK],
                profile_name="Team Default",
                connections=[
                    ConnectionDraft(
                        display_name="Gemini",
                        provider=ProviderKind.GEMINI,
                        api_key="gkey-2",
                        description="Updated wizard settings",
                        token_limit=2000,
                    ),
                    ConnectionDraft(
                        display_name="DeepSeek",
                        provider=ProviderKind.DEEPSEEK,
                        api_key="dkey-2",
                        description="Updated wizard settings",
                        token_limit=2000,
                    ),
                ],
            )
        )

        rerun_connections = {
            profile.name: profile
            for profile in context.runtime.book_manager.list_endpoint_profiles()
            if profile.name.startswith("recommended-")
        }
        assert {name: profile.profile_id for name, profile in rerun_connections.items()} == initial_connection_ids
        assert rerun_connections["recommended-Gemini 2.5 Pro"].api_key == "gkey-2"
        assert rerun_connections["recommended-Gemini 2.5 Pro"].description == "Updated wizard settings"
        assert rerun_connections["recommended-Gemini 2.5 Pro"].token_limit == 2000
        assert rerun_connections["recommended-DeepSeek Chat"].api_key == "dkey-2"
        assert rerun_connections["recommended-DeepSeek Chat"].description == "Updated wizard settings"
        assert rerun_connections["recommended-DeepSeek Chat"].token_limit == 2000

        matching_profiles = [
            profile for profile in context.runtime.book_manager.list_profiles() if profile.name == "Team Default"
        ]
        assert len(matching_profiles) == 1
        assert matching_profiles[0].profile_id == initial_profile.profile_id
    finally:
        context.close()


def test_setup_wizard_rerun_overwrites_manual_managed_connection_edits(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        context.services.app_setup.run_setup_wizard(
            SetupWizardRequest(
                providers=[ProviderKind.GEMINI],
                profile_name="Team Default",
                connections=[
                    ConnectionDraft(
                        display_name="Gemini",
                        provider=ProviderKind.GEMINI,
                        api_key="gkey-1",
                    )
                ],
            )
        )

        managed = next(
            profile
            for profile in context.runtime.book_manager.list_endpoint_profiles()
            if profile.name == "recommended-Gemini 2.5 Pro"
        )

        state = context.services.app_setup.save_connection(
            SaveConnectionRequest(
                connection_id=managed.profile_id,
                connection=ConnectionDraft(
                    display_name="Gemini Personal Tweak",
                    provider=ProviderKind.OPENAI_COMPATIBLE,
                    api_key="custom-key",
                    base_url="https://example.com/v1",
                    default_model="custom-model",
                    description="Local override",
                    temperature=0.7,
                    token_limit=1234,
                    custom_parameters_json=json.dumps({"reasoning_effort": "medium"}),
                ),
            )
        )

        edited = next(connection for connection in state.connections if connection.connection_id == managed.profile_id)
        assert edited.display_name == "Gemini Personal Tweak"
        assert edited.is_managed is True
        assert edited.base_url == "https://example.com/v1"
        assert edited.default_model == "custom-model"
        assert edited.token_limit == 1234
        assert json.loads(edited.custom_parameters_json or "{}") == {"reasoning_effort": "medium"}

        context.services.app_setup.run_setup_wizard(
            SetupWizardRequest(
                providers=[ProviderKind.GEMINI],
                profile_name="Team Default",
                connections=[
                    ConnectionDraft(
                        display_name="Gemini",
                        provider=ProviderKind.GEMINI,
                        api_key="gkey-2",
                        description="Wizard reset",
                        token_limit=2000,
                    )
                ],
            )
        )

        rerun = context.runtime.book_manager.get_endpoint_profile(managed.profile_id)
        assert rerun is not None
        assert rerun.name == "recommended-Gemini 2.5 Pro"
        assert rerun.api_key == "gkey-2"
        assert rerun.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
        assert rerun.model == "gemini-2.5-pro"
        assert rerun.description == "Wizard reset"
        assert rerun.token_limit == 2000

        refreshed = next(
            connection
            for connection in context.services.app_setup.get_state().connections
            if connection.connection_id == managed.profile_id
        )
        assert refreshed.display_name == "Gemini 2.5 Pro"
        assert refreshed.is_managed is True
    finally:
        context.close()


def test_project_specific_profile_remains_usable_without_shared_profiles(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Setup Target", target_language="English")
        )
        project_id = created.project.project_id

        app_setup = context.services.app_setup.get_state()
        shared_profile = app_setup.shared_profiles[0]
        project_profile = shared_profile.model_copy(
            update={
                "profile_id": f"project:{project_id}",
                "name": "Project specific",
                "kind": WorkflowProfileKind.PROJECT_SPECIFIC,
                "is_default": False,
            }
        )
        context.services.project_setup.save(
            SaveProjectSetupRequest(
                project_id=project_id,
                shared_profile_id=shared_profile.profile_id,
                project_profile=project_profile,
            )
        )

        for profile in list(context.runtime.book_manager.list_profiles()):
            context.runtime.book_manager.delete_profile(profile.profile_id)

        state = context.services.project_setup.get_state(project_id)

        assert state.project_profile is not None
        assert state.blocker is None
    finally:
        context.close()


def test_app_setup_service_persists_advanced_connection_fields(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        state = context.services.app_setup.save_connection(
            SaveConnectionRequest(
                connection=ConnectionDraft(
                    display_name="DeepSeek Advanced",
                    provider=ProviderKind.DEEPSEEK,
                    api_key="secret",
                    base_url="https://api.deepseek.com",
                    default_model="deepseek-chat",
                    description="Detailed legacy endpoint-profile settings",
                    temperature=0.15,
                    timeout=90,
                    max_retries=4,
                    concurrency=2,
                    token_limit=200000,
                    input_token_limit=120000,
                    output_token_limit=80000,
                    custom_parameters_json=json.dumps(
                        {"reasoning_effort": "none", "extra_body": {"foo": "bar"}},
                        ensure_ascii=False,
                    ),
                )
            )
        )

        connection = next(item for item in state.connections if item.display_name == "DeepSeek Advanced")
        assert connection.description == "Detailed legacy endpoint-profile settings"
        assert connection.temperature == 0.15
        assert connection.timeout == 90
        assert connection.max_retries == 4
        assert connection.concurrency == 2
        assert connection.token_limit == 200000
        assert connection.input_token_limit == 120000
        assert connection.output_token_limit == 80000
        assert json.loads(connection.custom_parameters_json or "{}") == {
            "reasoning_effort": "none",
            "extra_body": {"foo": "bar"},
        }

        endpoint = next(
            profile
            for profile in context.runtime.book_manager.list_endpoint_profiles()
            if profile.name == "DeepSeek Advanced"
        )
        assert endpoint.description == "Detailed legacy endpoint-profile settings"
        assert endpoint.temperature == 0.15
        assert endpoint.timeout == 90
        assert endpoint.max_retries == 4
        assert endpoint.concurrency == 2
        assert endpoint.token_limit == 200000
        assert endpoint.input_token_limit == 120000
        assert endpoint.output_token_limit == 80000
        assert endpoint.kwargs["provider"] == ProviderKind.DEEPSEEK.value
        assert endpoint.kwargs["reasoning_effort"] == "none"
        assert endpoint.kwargs["extra_body"] == {"foo": "bar"}
    finally:
        context.close()


def test_app_setup_delete_connection_invalidates_dependent_surfaces(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    seen: list[str] = []
    subscription = context.events.subscribe(lambda event: seen.append(event.kind.value))
    try:
        state = context.services.app_setup.save_connection(
            SaveConnectionRequest(
                connection=ConnectionDraft(
                    display_name="Disposable",
                    provider=ProviderKind.OPENAI,
                    api_key="secret",
                    base_url="https://api.openai.com/v1",
                    default_model="gpt-4.1-mini",
                )
            )
        )
        connection = next(item for item in state.connections if item.display_name == "Disposable")
        seen.clear()

        context.services.app_setup.delete_connection(connection.connection_id)

        assert "setup_invalidated" in seen
        assert "projects_invalidated" in seen
        assert "workboard_invalidated" in seen
    finally:
        subscription.close()
        context.close()


def test_projects_delete_invalidates_all_affected_surfaces(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    seen: list[str] = []
    subscription = context.events.subscribe(lambda event: seen.append(event.kind.value))
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Delete Me", target_language="English")
        )
        project_id = created.project.project_id
        seen.clear()

        context.services.projects.delete_project(project_id, permanent=True)

        assert "projects_invalidated" in seen
        assert "setup_invalidated" in seen
        assert "workboard_invalidated" in seen
        assert "queue_changed" in seen
        assert "document_invalidated" in seen
        assert "terms_invalidated" in seen
    finally:
        subscription.close()
        context.close()


def test_application_context_close_closes_task_engine_before_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ensure_qt_app()
    close_order: list[str] = []
    context = build_application_context(library_root=tmp_path)
    original_engine_close = context.runtime.task_engine.close
    original_book_manager_close = context.runtime.book_manager.close

    def _track_engine_close() -> None:
        close_order.append("engine")
        original_engine_close()

    def _track_book_manager_close() -> None:
        close_order.append("book_manager")
        original_book_manager_close()

    monkeypatch.setattr(context.runtime.task_engine, "close", _track_engine_close, raising=True)
    monkeypatch.setattr(context.runtime.book_manager, "close", _track_book_manager_close, raising=True)

    context.close()

    assert close_order[:2] == ["engine", "book_manager"]


def test_application_context_close_keeps_runtime_resources_open_while_workers_still_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ensure_qt_app()
    close_order: list[str] = []
    context = build_application_context(library_root=tmp_path)

    def _track_engine_close() -> None:
        close_order.append("engine")

    def _track_task_store_close() -> None:
        close_order.append("task_store")

    def _track_book_manager_close() -> None:
        close_order.append("book_manager")

    monkeypatch.setattr(context.runtime.task_engine, "close", _track_engine_close, raising=True)
    monkeypatch.setattr(context.runtime.task_engine, "has_running_work", lambda: True, raising=True)
    monkeypatch.setattr(context.runtime.task_store, "close", _track_task_store_close, raising=True)
    monkeypatch.setattr(context.runtime.book_manager, "close", _track_book_manager_close, raising=True)

    context.close()

    assert close_order == ["engine"]


def test_terms_update_missing_term_raises_not_found(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Terms Missing", target_language="English")
        )
        project_id = created.project.project_id
        _configure_project_for_task_preflights(context, project_id)
        scope = context.services.terms.get_project_terms(project_id).scope

        with pytest.raises(ApplicationError) as exc_info:
            context.services.terms.update_term(
                UpdateTermRequest(
                    scope=scope,
                    term_id=1,
                    term_key="missing",
                    translation="x",
                )
            )

        assert exc_info.value.payload.code == "not_found"
    finally:
        context.close()


def test_terms_update_request_rejects_removed_description_field(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Terms Manual Edit", target_language="English")
        )
        project_id = created.project.project_id
        _configure_project_for_task_preflights(context, project_id)

        with context.runtime.open_book_db(project_id) as dbx:
            dbx.term_repo.upsert_terms(
                [
                    TermRecord(
                        key="ルフィ",
                        descriptions={"1": "Main character"},
                        occurrence={"1": 1},
                        votes=1,
                        total_api_calls=1,
                    )
                ]
            )

        scope = context.services.terms.get_project_terms(project_id).scope

        with pytest.raises(ValidationError):
            UpdateTermRequest.model_validate(
                {
                    "scope": scope,
                    "term_id": 1,
                    "term_key": "ルフィ",
                    "description": "Pirate captain",
                }
            )
    finally:
        context.close()
