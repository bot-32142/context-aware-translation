#!/usr/bin/env python3
"""Generate README screenshots for the setup wizard."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleFactory

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionTestResult,
    ProviderCard,
    SetupWizardRequest,
    SetupWizardState,
)
from context_aware_translation.application.contracts.common import (
    ProviderKind,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.runtime import infer_capabilities, recommended_workflow_profile_from_drafts
from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog
from context_aware_translation.ui.main import _configure_qt_environment, load_stylesheet
from context_aware_translation.ui.startup import preferred_style_name


@dataclass
class _FakeAppSetupService:
    state: AppSetupState
    wizard_state: SetupWizardState

    def get_state(self) -> AppSetupState:
        return self.state

    def get_wizard_state(self) -> SetupWizardState:
        return self.wizard_state

    def preview_setup_wizard(self, request: SetupWizardRequest) -> SetupWizardState:
        recommendation = recommended_workflow_profile_from_drafts(
            request.connections,
            name=request.profile_name or "Recommended",
            target_language=request.target_language or "English",
        )
        return SetupWizardState(
            available_providers=self.wizard_state.available_providers,
            selected_providers=request.providers,
            drafts=request.connections,
            test_results=[
                ConnectionTestResult(
                    connection_label=draft.display_name,
                    supported_capabilities=infer_capabilities(draft.provider),
                    message=UserMessage(
                        severity=UserMessageSeverity.INFO,
                        text="Connection accepted. Capability testing was inferred from the provider type.",
                    ),
                )
                for draft in request.connections
            ],
            recommendation=recommendation,
            profile_name=request.profile_name or "Recommended",
            target_language=request.target_language or "English",
        )

    def run_setup_wizard(self, request: SetupWizardRequest) -> AppSetupState:  # noqa: ARG002
        return self.state


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _service() -> _FakeAppSetupService:
    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            ),
            ProviderCard(
                provider=ProviderKind.OPENAI,
                label="OpenAI",
                helper_text="General-purpose text and image-capable provider.",
            ),
            ProviderCard(
                provider=ProviderKind.DEEPSEEK,
                label="DeepSeek",
                helper_text="Low-cost text translation and context building.",
            ),
            ProviderCard(
                provider=ProviderKind.ANTHROPIC,
                label="Anthropic",
                helper_text="Text translation and image understanding.",
            ),
        ],
        selected_providers=[],
        drafts=[],
        profile_name="Recommended",
        target_language="English",
    )
    return _FakeAppSetupService(state=AppSetupState(connections=[], shared_profiles=[]), wizard_state=wizard_state)


def _select_demo_setup(dialog: SetupWizardDialog) -> None:
    gemini_checkbox, gemini_api_key = dialog._provider_inputs[ProviderKind.GEMINI]
    deepseek_checkbox, deepseek_api_key = dialog._provider_inputs[ProviderKind.DEEPSEEK]
    gemini_checkbox.setChecked(True)
    gemini_api_key.setText("demo-gemini-key")
    deepseek_checkbox.setChecked(True)
    deepseek_api_key.setText("demo-deepseek-key")
    QApplication.processEvents()


def _prepare_app() -> QApplication:
    _configure_qt_environment()
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    styles = QStyleFactory.keys()
    style_name = (
        "Fusion" if "Fusion" in styles else (preferred_style_name(sys.platform, styles) or next(iter(styles), None))
    )
    if style_name:
        app.setStyle(style_name)
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)
    return app


def _render_page_content(dialog: SetupWizardDialog, output_path: Path, *, minimum_size: QSize | None = None) -> None:
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    QApplication.processEvents()
    QTest.qWait(250)
    dialog.page_content.adjustSize()
    if minimum_size is not None:
        dialog.page_content.resize(dialog.page_content.size().expandedTo(minimum_size))
    QApplication.processEvents()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dialog.page_content.grab().save(str(output_path))
    dialog.close()
    QApplication.processEvents()


def main() -> int:
    _prepare_app()
    service = _service()
    output_dir = _project_root() / "docs" / "screenshots"

    provider_dialog = SetupWizardDialog(service, service.wizard_state)
    _select_demo_setup(provider_dialog)
    _render_page_content(provider_dialog, output_dir / "setup-wizard-providers.png", minimum_size=QSize(1400, 0))

    review_dialog = SetupWizardDialog(service, service.wizard_state)
    _select_demo_setup(review_dialog)
    review_dialog._go_next()
    if review_dialog._target_language_combo is not None:
        review_dialog._target_language_combo.setEditText("English")
        QApplication.processEvents()
    _render_page_content(review_dialog, output_dir / "setup-wizard-review.png", minimum_size=QSize(1400, 0))

    print(f"Generated screenshots in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
