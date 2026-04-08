#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QStyleFactory, QWidget

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    ConnectionTestResult,
    ProviderCard,
    SetupWizardMode,
    SetupWizardState,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    ActionState,
    CapabilityCode,
    DocumentRef,
    DocumentRowActionKind,
    DocumentSection,
    ExportOption,
    NavigationTarget,
    NavigationTargetKind,
    ProjectRef,
    ProviderKind,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import (
    DocumentExportState,
    DocumentImagesState,
    DocumentOCRState,
    DocumentTranslationState,
    DocumentWorkspaceState,
    OCRPageState,
    TranslateAndExportState,
    TranslationUnitActionState,
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.contracts.projects import (
    ProjectsScreenState,
    ProjectSummary,
    WorkflowProfileOption,
)
from context_aware_translation.application.contracts.terms import (
    TermsScope,
    TermsScopeKind,
    TermsTableState,
    TermStatus,
    TermsToolbarState,
    TermTableRow,
)
from context_aware_translation.application.contracts.work import (
    ContextFrontierState,
    DocumentRowAction,
    ExportDialogState,
    ImportDocumentTypeOption,
    ImportInspectionState,
    WorkboardState,
    WorkDocumentRow,
)
from context_aware_translation.application.events import InMemoryApplicationEventBus
from context_aware_translation.ui import i18n
from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane
from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog
from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView
from context_aware_translation.ui.features.document_workspace_view import TranslateAndExportDialog, WorkExportDialog
from context_aware_translation.ui.features.library_view import _ProjectDialog
from context_aware_translation.ui.features.terms_view import TermsView
from context_aware_translation.ui.features.work_view import WorkView
from context_aware_translation.ui.main import load_stylesheet
from context_aware_translation.ui.startup import preferred_style_name
from tests.application.fakes import (
    FakeAppSetupService,
    FakeDocumentService,
    FakeProjectsService,
    FakeTermsService,
    FakeWorkService,
)

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "docs" / "screenshots" / "EN"
SAMPLE_SOURCE_PATH = Path.home() / "workspace2" / "pg17989-images-3.epub"


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        app.setApplicationName("Context-Aware Translation")
        app.setOrganizationName("CAT")
        app.setOrganizationDomain("context-aware-translation")
    style_name = preferred_style_name(sys.platform, QStyleFactory.keys())
    if style_name:
        app.setStyle(style_name)
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)
    i18n.load_translation(app, "en")
    return app


def _settle(wait_ms: int = 160) -> None:
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(3):
        app.processEvents()
        QTest.qWait(wait_ms)


def _save_widget(widget: QWidget, output_path: Path, *, width: int, height: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    widget.resize(width, height)
    widget.show()
    _settle()
    for line_edit in widget.findChildren(QLineEdit):
        line_edit.setCursorPosition(0)
        line_edit.deselect()
    _settle(40)
    widget.repaint()
    _settle()
    image = widget.grab().toImage()
    if not image.save(str(output_path)):
        raise RuntimeError(f"Failed to save screenshot to {output_path}")


def _recommended_profile() -> WorkflowProfileDetail:
    routes = [
        WorkflowStepRoute(
            step_id=WorkflowStepId.EXTRACTOR,
            step_label="Extractor",
            connection_id="conn-deepseek",
            connection_label="DeepSeek",
            model="deepseek-chat",
        ),
        WorkflowStepRoute(
            step_id=WorkflowStepId.SUMMARIZER,
            step_label="Summarizer",
            connection_id="conn-deepseek",
            connection_label="DeepSeek",
            model="deepseek-chat",
        ),
        WorkflowStepRoute(
            step_id=WorkflowStepId.TRANSLATOR,
            step_label="Translator",
            connection_id="conn-deepseek",
            connection_label="DeepSeek",
            model="deepseek-reasoner",
        ),
        WorkflowStepRoute(
            step_id=WorkflowStepId.POLISH,
            step_label="Polish",
            connection_id="conn-deepseek",
            connection_label="DeepSeek",
            model="deepseek-chat",
        ),
        WorkflowStepRoute(
            step_id=WorkflowStepId.REVIEWER,
            step_label="Reviewer",
            connection_id="conn-deepseek",
            connection_label="DeepSeek",
            model="deepseek-reasoner",
        ),
        WorkflowStepRoute(
            step_id=WorkflowStepId.OCR,
            step_label="OCR",
            connection_id="conn-gemini",
            connection_label="Gemini",
            model="gemini-2.5-flash",
        ),
        WorkflowStepRoute(
            step_id=WorkflowStepId.IMAGE_REEMBEDDING,
            step_label="Image reembedding",
            connection_id="conn-gemini",
            connection_label="Gemini",
            model="gemini-2.5-flash-image-preview",
        ),
    ]
    return WorkflowProfileDetail(
        profile_id="profile:monte-cristo",
        name="Monte Cristo English",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=routes,
        is_default=True,
    )


def _connection_summary(
    *,
    connection_id: str,
    display_name: str,
    provider: ProviderKind,
    base_url: str,
    model: str,
    concurrency: int,
) -> ConnectionSummary:
    return ConnectionSummary(
        connection_id=connection_id,
        display_name=display_name,
        provider=provider,
        base_url=base_url,
        default_model=model,
        concurrency=concurrency,
        status=ConnectionStatus.READY,
    )


def _app_setup_state() -> AppSetupState:
    return AppSetupState(
        connections=[
            _connection_summary(
                connection_id="conn-deepseek",
                display_name="DeepSeek",
                provider=ProviderKind.DEEPSEEK,
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
                concurrency=15,
            ),
            _connection_summary(
                connection_id="conn-gemini",
                display_name="Gemini",
                provider=ProviderKind.GEMINI,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                model="gemini-2.5-flash",
                concurrency=5,
            ),
        ],
        shared_profiles=[_recommended_profile()],
    )


def _wizard_service() -> FakeAppSetupService:
    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.DEEPSEEK,
                label="DeepSeek",
                helper_text="Fast, inexpensive text generation for extraction, translation, and review.",
            ),
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Strong OCR and image support for EPUB images, PDFs, and scanned pages.",
            ),
            ProviderCard(
                provider=ProviderKind.OPENAI,
                label="OpenAI",
                helper_text="General-purpose text and image-capable models.",
            ),
            ProviderCard(
                provider=ProviderKind.ANTHROPIC,
                label="Anthropic",
                helper_text="Claude models for high-quality reasoning and editorial passes.",
            ),
        ]
    )
    preview_state = SetupWizardState(
        available_providers=wizard_state.available_providers,
        selected_providers=[ProviderKind.DEEPSEEK, ProviderKind.GEMINI],
        drafts=[
            ConnectionDraft(
                display_name="DeepSeek",
                provider=ProviderKind.DEEPSEEK,
                api_key="demo-deepseek-key",
                base_url="https://api.deepseek.com",
                default_model="deepseek-chat",
            ),
            ConnectionDraft(
                display_name="Gemini",
                provider=ProviderKind.GEMINI,
                api_key="demo-gemini-key",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                default_model="gemini-2.5-flash",
            ),
        ],
        test_results=[
            ConnectionTestResult(
                connection_label="DeepSeek",
                supported_capabilities=[CapabilityCode.TRANSLATION, CapabilityCode.REASONING_AND_REVIEW],
                message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
            ),
            ConnectionTestResult(
                connection_label="Gemini",
                supported_capabilities=[CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING],
                message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
            ),
        ],
        recommendation=_recommended_profile(),
        profile_name="Monte Cristo English",
        target_language="English",
        recommendation_mode=SetupWizardMode.BALANCED,
    )
    return FakeAppSetupService(state=_app_setup_state(), wizard_state=wizard_state, preview_state=preview_state)


def _projects_service() -> FakeProjectsService:
    summary = ProjectSummary(
        project=ProjectRef(project_id="proj-monte-cristo", name="The Count of Monte Cristo"),
        target_language="English",
        progress_summary="34.0% (17/50)",
        modified_at=datetime(2026, 4, 6, 18, 47, tzinfo=UTC).timestamp(),
    )
    workflow_profiles = [
        WorkflowProfileOption(
            profile_id="profile:monte-cristo",
            name="Monte Cristo English",
            target_language="English",
            is_default=True,
        ),
        WorkflowProfileOption(
            profile_id="profile:zh",
            name="Chinese Release",
            target_language="Chinese",
        ),
    ]
    return FakeProjectsService(
        list_state=ProjectsScreenState(items=[summary]),
        project_summary=summary,
        create_result=summary,
        update_result=summary,
        workflow_profiles=workflow_profiles,
    )


def _work_service() -> FakeWorkService:
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-monte-cristo",
            document_id=1,
        ),
    )
    rows = [
        WorkDocumentRow(
            document=DocumentRef(document_id=1, order_index=1, label="Title Page"),
            status=SurfaceStatus.READY,
            source_count=1,
            ocr_status="N/A",
            terms_status="Ready",
            translation_status="Ready",
            state_summary="Ready to translate",
            primary_action=action,
        ),
        WorkDocumentRow(
            document=DocumentRef(document_id=2, order_index=2, label="Chapter 1 · Marseille — Arrival"),
            status=SurfaceStatus.READY,
            source_count=14,
            ocr_status="N/A",
            terms_status="In progress (18/41)",
            translation_status="Not started",
            state_summary="Build and review terms",
            primary_action=action.model_copy(
                update={
                    "target": NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_TERMS,
                        project_id="proj-monte-cristo",
                        document_id=2,
                    ),
                    "label": "Open Terms",
                }
            ),
        ),
        WorkDocumentRow(
            document=DocumentRef(document_id=3, order_index=3, label="Chapter 2 · Father and Son"),
            status=SurfaceStatus.READY,
            source_count=12,
            ocr_status="N/A",
            terms_status="Complete",
            translation_status="In progress (7/12)",
            state_summary="Continue translation",
            primary_action=action.model_copy(
                update={
                    "target": NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
                        project_id="proj-monte-cristo",
                        document_id=3,
                    )
                }
            ),
        ),
    ]
    state = WorkboardState(
        project=ProjectRef(project_id="proj-monte-cristo", name="The Count of Monte Cristo"),
        context_frontier=ContextFrontierState(summary="Context ready through Chapter 2"),
        rows=rows,
    )
    source_label = str(SAMPLE_SOURCE_PATH) if SAMPLE_SOURCE_PATH.exists() else "~/workspace2/pg17989-images-3.epub"
    service = FakeWorkService(state_by_project={"proj-monte-cristo": state})
    service.import_inspection_state = ImportInspectionState(
        selected_paths=[source_label],
        available_types=[ImportDocumentTypeOption(document_type="epub", label="EPUB")],
        summary=f"1 source selected · {Path(source_label).name}",
    )
    service.import_result = AcceptedCommand(
        command_name="import_documents",
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Import complete."),
    )
    return service


def _terms_state() -> TermsTableState:
    return TermsTableState(
        scope=TermsScope(
            kind=TermsScopeKind.PROJECT,
            project=ProjectRef(project_id="proj-monte-cristo", name="The Count of Monte Cristo"),
        ),
        toolbar=TermsToolbarState(
            can_translate_pending=True,
            can_review=True,
            can_filter_noise=True,
            can_add_terms=True,
            can_import=True,
            can_export=True,
        ),
        rows=[
            TermTableRow(
                term_id=1,
                term_key="Edmond Dantès",
                term="Edmond Dantès",
                term_type="character",
                translation="Edmond Dantès",
                description="Young sailor on the Pharaon; later known as the Count of Monte Cristo.",
                occurrences=22,
                votes=5,
                reviewed=True,
                ignored=False,
                status=TermStatus.READY,
            ),
            TermTableRow(
                term_id=2,
                term_key="Villefort",
                term="Villefort",
                term_type="character",
                translation="Villefort",
                description="Deputy crown prosecutor whose ambition drives several early plot turns.",
                occurrences=16,
                votes=4,
                reviewed=True,
                ignored=False,
                status=TermStatus.READY,
            ),
            TermTableRow(
                term_id=3,
                term_key="Pharaon",
                term="Pharaon",
                term_type="other",
                translation="Pharaon",
                description="Merchant ship returning to Marseille at the beginning of the novel.",
                occurrences=12,
                votes=3,
                reviewed=False,
                ignored=False,
                status=TermStatus.NEEDS_REVIEW,
            ),
            TermTableRow(
                term_id=4,
                term_key="Mercédès",
                term="Mercédès",
                term_type="character",
                translation="Mercédès",
                description="Dantès's fiancée in Marseille.",
                occurrences=9,
                votes=2,
                reviewed=False,
                ignored=False,
                status=TermStatus.NEEDS_REVIEW,
            ),
        ],
    )


def _document_workspace_state(active_tab: DocumentSection) -> DocumentWorkspaceState:
    return DocumentWorkspaceState(
        project=ProjectRef(project_id="proj-monte-cristo", name="The Count of Monte Cristo"),
        document=DocumentRef(document_id=2, order_index=2, label="Chapter 1 · Marseille — Arrival"),
        active_tab=active_tab,
    )


def _document_service() -> FakeDocumentService:
    translation_state = DocumentTranslationState(
        workspace=_document_workspace_state(DocumentSection.TRANSLATION),
        units=[
            TranslationUnitState(
                unit_id="chunk-1",
                unit_kind=TranslationUnitKind.CHUNK,
                label="Chunk 1",
                status=SurfaceStatus.DONE,
                source_text=(
                    "Le 24 février 1815, la vigie de Notre-Dame de la Garde signala le trois-mâts le Pharaon,\n"
                    "venant de Smyrne, Trieste et Naples."
                ),
                translated_text=(
                    "On February 24, 1815, the watchman at Notre-Dame de la Garde signaled the three-master Pharaon,\n"
                    "arriving from Smyrna, Trieste, and Naples."
                ),
                line_count=2,
                actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
            ),
            TranslationUnitState(
                unit_id="chunk-2",
                unit_kind=TranslationUnitKind.CHUNK,
                label="Chunk 2",
                status=SurfaceStatus.READY,
                source_text="M. Morrel monta d'un bond sur le quai et appela Edmond Dantès.",
                translated_text="M. Morrel leapt onto the quay and called out to Edmond Dantès.",
                line_count=1,
                actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
            ),
            TranslationUnitState(
                unit_id="chunk-3",
                unit_kind=TranslationUnitKind.CHUNK,
                label="Chunk 3",
                status=SurfaceStatus.READY,
                source_text="Le jeune marin sauta dans le canot et gagna le port.",
                translated_text="The young sailor sprang into the boat and made for the harbor.",
                line_count=1,
                actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
            ),
        ],
        run_action=ActionState(enabled=True),
        batch_action=ActionState(enabled=True),
        supports_batch=True,
        current_unit_id="chunk-1",
    )
    return FakeDocumentService(
        workspace=_document_workspace_state(DocumentSection.TRANSLATION),
        ocr=DocumentOCRState(workspace=_document_workspace_state(DocumentSection.OCR), pages=[OCRPageState(
            source_id=201,
            page_number=1,
            total_pages=1,
            status=SurfaceStatus.DONE,
            extracted_text="Sample OCR page",
        )]),
        ocr_page_images={201: None},
        translation=translation_state,
        images=DocumentImagesState(workspace=_document_workspace_state(DocumentSection.IMAGES), assets=[]),
        export=DocumentExportState(
            workspace=_document_workspace_state(DocumentSection.EXPORT),
            can_export=True,
            available_formats=[
                ExportOption(format_id="epub", label="EPUB", is_default=True),
                ExportOption(format_id="html", label="HTML"),
                ExportOption(format_id="docx", label="DOCX"),
            ],
            default_output_path=str((ROOT / "output" / "the-count-of-monte-cristo.epub").resolve()),
            supports_preserve_structure=True,
            supports_original_image_export=True,
            supports_epub_layout_conversion=True,
        ),
        translate_and_export=TranslateAndExportState(
            workspace=_document_workspace_state(DocumentSection.TRANSLATION),
            can_start=True,
            available_formats=[
                ExportOption(format_id="epub", label="EPUB", is_default=True),
                ExportOption(format_id="html", label="HTML"),
                ExportOption(format_id="docx", label="DOCX"),
            ],
            default_output_path=str((ROOT / "output" / "the-count-of-monte-cristo.epub").resolve()),
            supports_preserve_structure=True,
            supports_original_image_export=True,
            supports_epub_layout_conversion=True,
            batch_available=True,
            reembedding_available=True,
        ),
    )


def _export_state() -> ExportDialogState:
    return ExportDialogState(
        project_id="proj-monte-cristo",
        document_ids=[1, 2, 3],
        document_labels=[
            "Title Page",
            "Chapter 1 · Marseille — Arrival",
            "Chapter 2 · Father and Son",
        ],
        available_formats=[
            ExportOption(format_id="epub", label="EPUB", is_default=True),
            ExportOption(format_id="html", label="HTML"),
            ExportOption(format_id="docx", label="DOCX"),
        ],
        default_output_path=str((ROOT / "output" / "the-count-of-monte-cristo.epub").resolve()),
        supports_preserve_structure=True,
        supports_original_image_export=True,
        supports_epub_layout_conversion=True,
    )


def generate() -> None:
    _ensure_app()

    app_settings = AppSettingsPane(FakeAppSetupService(state=_app_setup_state()))
    _save_widget(app_settings, SCREENSHOT_DIR / "InitialSetup.png", width=1280, height=460)
    app_settings.close()
    app_settings.deleteLater()
    _settle(60)

    wizard_service = _wizard_service()

    wizard = SetupWizardDialog(wizard_service, wizard_service.get_wizard_state())
    _save_widget(wizard, SCREENSHOT_DIR / "Wizard.png", width=1160, height=760)
    wizard.close()
    wizard.deleteLater()
    _settle(60)

    api_wizard = SetupWizardDialog(wizard_service, wizard_service.get_wizard_state())
    api_wizard._provider_inputs[ProviderKind.DEEPSEEK][0].setChecked(True)
    api_wizard._provider_inputs[ProviderKind.GEMINI][0].setChecked(True)
    api_wizard._provider_inputs[ProviderKind.DEEPSEEK][1].setText("demo-deepseek-key")
    api_wizard._provider_inputs[ProviderKind.GEMINI][1].setText("demo-gemini-key")
    _save_widget(api_wizard, SCREENSHOT_DIR / "APISetup.png", width=1160, height=760)
    api_wizard.close()
    api_wizard.deleteLater()
    _settle(60)

    language_wizard = SetupWizardDialog(wizard_service, wizard_service.get_wizard_state())
    language_wizard._provider_inputs[ProviderKind.DEEPSEEK][0].setChecked(True)
    language_wizard._provider_inputs[ProviderKind.GEMINI][0].setChecked(True)
    language_wizard._provider_inputs[ProviderKind.DEEPSEEK][1].setText("demo-deepseek-key")
    language_wizard._provider_inputs[ProviderKind.GEMINI][1].setText("demo-gemini-key")
    language_wizard._go_next()
    if language_wizard._profile_name_edit is not None:
        language_wizard._profile_name_edit.setText("Monte Cristo English")
    if language_wizard._target_language_combo is not None:
        language_wizard._target_language_combo.setCurrentText("English")
    _save_widget(language_wizard, SCREENSHOT_DIR / "Language.png", width=1240, height=720)
    language_wizard.close()
    language_wizard.deleteLater()
    _settle(60)

    project_dialog = _ProjectDialog(
        title="New Project",
        name="Monte Cristo",
        target_language="English",
        workflow_profiles=_projects_service().workflow_profiles,
        workflow_profile_id="profile:monte-cristo",
    )
    _save_widget(project_dialog, SCREENSHOT_DIR / "NewProject.png", width=700, height=280)
    project_dialog.close()
    project_dialog.deleteLater()
    _settle(60)

    bus = InMemoryApplicationEventBus()
    work_service = _work_service()
    work_view = WorkView(
        "proj-monte-cristo",
        work_service,
        _document_service(),
        FakeTermsService(project_state=_terms_state(), document_state=_terms_state()),
        bus,
    )
    work_view._inspect_import_paths([str(SAMPLE_SOURCE_PATH if SAMPLE_SOURCE_PATH.exists() else Path("~/workspace2/pg17989-images-3.epub"))])
    work_view.rows_table.selectRow(1)
    _save_widget(work_view, SCREENSHOT_DIR / "Import.png", width=1320, height=600)
    work_view.cleanup()
    work_view.close()
    work_view.deleteLater()
    _settle(60)

    terms_view = TermsView(
        "proj-monte-cristo",
        FakeTermsService(project_state=_terms_state()),
        InMemoryApplicationEventBus(),
    )
    _save_widget(terms_view, SCREENSHOT_DIR / "Terms.png", width=1320, height=560)
    terms_view.cleanup()
    terms_view.close()
    terms_view.deleteLater()
    _settle(60)

    translation_view = DocumentTranslationView(_document_service(), "proj-monte-cristo", 2)
    translation_view.refresh()
    _save_widget(translation_view, SCREENSHOT_DIR / "Translate.png", width=1280, height=760)
    translation_view.close()
    translation_view.deleteLater()
    _settle(60)

    translate_and_export_dialog = TranslateAndExportDialog(
        _document_service(),
        _document_service().translate_and_export,
    )
    translate_and_export_dialog.batch_cb.setChecked(True)
    translate_and_export_dialog.reembedding_cb.setChecked(True)
    _save_widget(translate_and_export_dialog, SCREENSHOT_DIR / "TranslateAndExport.png", width=760, height=420)
    translate_and_export_dialog.close()
    translate_and_export_dialog.deleteLater()
    _settle(60)

    export_dialog = WorkExportDialog(
        FakeWorkService(
            state_by_project={"proj-monte-cristo": WorkboardState(project=ProjectRef(project_id="proj-monte-cristo", name="The Count of Monte Cristo"))}
        ),
        _export_state(),
    )
    _save_widget(export_dialog, SCREENSHOT_DIR / "Export.png", width=760, height=360)
    export_dialog.close()
    export_dialog.deleteLater()
    _settle(60)


def main() -> None:
    generate()
    print(f"Generated README screenshots in {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
