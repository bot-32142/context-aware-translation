from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication

from context_aware_translation.application.composition import build_application_context
from context_aware_translation.application.contracts.app_setup import ConnectionDraft, SetupWizardRequest
from context_aware_translation.application.contracts.common import ProviderKind
from context_aware_translation.application.contracts.projects import CreateProjectRequest


def _ensure_qt_app() -> QCoreApplication:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_build_application_context_exposes_services(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        setup_state = context.services.app_setup.get_state()
        assert setup_state.connections
        assert setup_state.default_routes
    finally:
        context.close()


def test_projects_service_can_create_and_list_projects(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="One Piece", target_language="English")
        )
        listed = context.services.projects.list_projects()

        assert created.project.name == "One Piece"
        assert any(item.project.project_id == created.project.project_id for item in listed.items)
    finally:
        context.close()


def test_project_setup_and_work_queries_use_service_boundary(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = build_application_context(library_root=tmp_path)
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Manga Test", target_language="English")
        )
        project_id = created.project.project_id

        project_setup = context.services.project_setup.get_state(project_id)
        workboard = context.services.work.get_workboard(project_id)

        assert project_setup.project.project_id == project_id
        assert project_setup.target_language == "English"
        assert workboard.project.project_id == project_id
        assert workboard.rows == []
    finally:
        context.close()


def test_app_setup_preview_exposes_recommended_routing(tmp_path: Path) -> None:
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
                        default_model="gemini-3-flash-preview",
                    ),
                    ConnectionDraft(
                        display_name="DeepSeek",
                        provider=ProviderKind.DEEPSEEK,
                        api_key="secret",
                        base_url="https://api.deepseek.com",
                        default_model="deepseek-chat",
                    ),
                ],
            )
        )

        assert preview.test_results
        assert preview.recommendation is not None
        assert preview.recommendation.routes
    finally:
        context.close()
