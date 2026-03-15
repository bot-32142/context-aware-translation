from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.app_setup import (
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.runtime import build_workflow_profile_payload
from context_aware_translation.ui.features.workflow_profile_editor import (
    ADVANCED_STEP_IDS,
    ConnectionChoice,
    WorkflowProfileEditorDialog,
    WorkflowRoutesEditor,
)

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QScrollArea, QWidget
    from superqt import QCollapsible

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _close_workflow_top_levels():
    yield
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QWidget):
            widget.close()
            widget.deleteLater()
    QApplication.processEvents()


def test_workflow_profile_editor_uses_scrollable_dialog_layout():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label="Translator",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            )
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3-flash-preview",
            )
        ],
        allow_name_edit=True,
    )

    dialog.show()
    QTest.qWait(50)

    assert dialog.findChildren(QScrollArea)
    assert isinstance(dialog.general_section, QCollapsible)
    assert isinstance(dialog.routes_section, QCollapsible)
    assert not dialog.general_section.isExpanded()
    assert dialog.width() <= 1240
    assert dialog.routes_table.editTriggers() == dialog.routes_table.EditTrigger.NoEditTriggers
    assert dialog.routes_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert dialog.routes_table.columnWidth(1) >= 180
    assert dialog.routes_table.columnWidth(2) >= 160
    assert dialog.routes_table.columnCount() == 4
    assert dialog.routes_editor.width() <= dialog._body_scroll.viewport().width()
    assert dialog.routes_table.item(0, 0).text() == "Translator"
    assert dialog.routes_table.cellWidget(0, 3) is not None
    route_row = dialog._rows[0]
    assert route_row.connection_combo is not None
    assert (
        route_row.connection_combo.sizePolicy().horizontalPolicy()
        == route_row.connection_combo.sizePolicy().Policy.Expanding
    )
    assert route_row.model_edit.sizePolicy().horizontalPolicy() == route_row.model_edit.sizePolicy().Policy.Expanding
    assert route_row.connection_combo.minimumHeight() >= route_row.connection_combo.sizeHint().height()
    assert route_row.model_edit.minimumHeight() >= route_row.model_edit.sizeHint().height()
    assert dialog.routes_table.rowHeight(0) >= dialog.routes_table.cellWidget(0, 1).sizeHint().height()
    assert dialog.routes_table.rowHeight(0) >= dialog.routes_table.cellWidget(0, 3).sizeHint().height()
    assert "background-color: white" in dialog.routes_table.styleSheet()
    assert "palette(base)" not in dialog.routes_table.styleSheet()


def test_workflow_profile_editor_normalizes_initial_routes_height_and_collapsed_spacing():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=step_id,
                step_label=step_id.value.replace("_", " ").title(),
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            )
            for step_id in (
                WorkflowStepId.EXTRACTOR,
                WorkflowStepId.SUMMARIZER,
                WorkflowStepId.GLOSSARY_TRANSLATOR,
                WorkflowStepId.TRANSLATOR,
                WorkflowStepId.REVIEWER,
                WorkflowStepId.OCR,
                WorkflowStepId.IMAGE_REEMBEDDING,
                WorkflowStepId.MANGA_TRANSLATOR,
                WorkflowStepId.TRANSLATOR_BATCH,
            )
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3-flash-preview",
            )
        ],
        allow_name_edit=True,
    )

    dialog.show()
    QTest.qWait(100)

    assert dialog.routes_section.content().maximumHeight() >= dialog.routes_section.content().sizeHint().height()

    dialog.routes_section.collapse(False)
    dialog.general_section.collapse(False)
    QTest.qWait(50)

    gap = dialog.routes_section.geometry().top() - dialog.general_section.geometry().bottom() - 1
    assert not dialog.routes_section.content().isVisible()
    assert dialog.routes_section.height() <= dialog.routes_section.toggleButton().sizeHint().height() + 24
    assert gap <= 4


def test_workflow_profile_editor_keeps_last_route_row_fully_visible():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=step_id,
                step_label=step_id.value.replace("_", " ").title(),
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            )
            for step_id in (
                WorkflowStepId.EXTRACTOR,
                WorkflowStepId.SUMMARIZER,
                WorkflowStepId.GLOSSARY_TRANSLATOR,
                WorkflowStepId.TRANSLATOR,
                WorkflowStepId.REVIEWER,
                WorkflowStepId.OCR,
                WorkflowStepId.IMAGE_REEMBEDDING,
                WorkflowStepId.MANGA_TRANSLATOR,
                WorkflowStepId.TRANSLATOR_BATCH,
            )
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3-flash-preview",
            )
        ],
        allow_name_edit=True,
    )

    dialog.show()
    QTest.qWait(100)

    viewport = dialog.routes_editor._scroll_area.viewport()
    last_row = dialog.routes_editor.rows[-1].row_widget
    assert last_row is not None
    assert last_row.geometry().bottom() <= viewport.height() - 4


def test_workflow_routes_editor_leaves_bottom_clearance_for_last_visible_row():
    routes = [
        WorkflowStepRoute(
            step_id=step_id,
            step_label=step_id.value.replace("_", " ").title(),
            connection_id="conn-gemini",
            connection_label="Gemini",
            model="gemini-3-flash-preview",
        )
        for step_id in (
            WorkflowStepId.EXTRACTOR,
            WorkflowStepId.SUMMARIZER,
            WorkflowStepId.GLOSSARY_TRANSLATOR,
            WorkflowStepId.TRANSLATOR,
            WorkflowStepId.REVIEWER,
            WorkflowStepId.OCR,
            WorkflowStepId.IMAGE_REEMBEDDING,
            WorkflowStepId.MANGA_TRANSLATOR,
            WorkflowStepId.TRANSLATOR_BATCH,
        )
    ]
    editor = WorkflowRoutesEditor(
        routes,
        [
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3-flash-preview",
            )
        ],
        advanced_step_ids=ADVANCED_STEP_IDS,
        hint_text="hint",
        max_visible_rows=6,
    )

    editor.show()
    QTest.qWait(100)

    viewport = editor._scroll_area.viewport()
    last_visible_row = editor.rows[5].row_widget
    assert last_visible_row is not None
    assert last_visible_row.geometry().bottom() <= viewport.height() - 4


def test_workflow_profile_editor_is_resizable():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label=f"Translator {index}",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            )
            for index in range(8)
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3-flash-preview",
            )
        ],
        allow_name_edit=True,
    )
    dialog.show()
    QTest.qWait(100)
    initial_size = dialog.size()

    dialog.resize(initial_size.width() + 120, initial_size.height() + 80)
    QTest.qWait(50)

    assert dialog.width() >= initial_size.width() + 100
    assert dialog.height() >= initial_size.height() + 60


def test_workflow_profile_editor_scrolls_when_both_sections_are_expanded():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label=f"Translator {index}",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            )
            for index in range(12)
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3-flash-preview",
            )
        ],
        allow_name_edit=True,
    )
    dialog.show()
    dialog.general_section.expand(False)
    QTest.qWait(250)
    dialog.resize(dialog.width(), 420)
    QTest.qWait(50)

    assert dialog._body_scroll.horizontalScrollBar().maximum() == 0
    assert dialog._body_scroll.verticalScrollBar().maximum() > 0
    assert dialog.routes_editor.width() <= dialog._body_scroll.viewport().width()


def test_step_advanced_config_dialog_updates_route_config():
    from context_aware_translation.ui.features.workflow_profile_editor import StepAdvancedConfigDialog

    route = WorkflowStepRoute(
        step_id=WorkflowStepId.OCR,
        step_label="OCR",
        connection_id="conn-gemini",
        connection_label="Gemini",
        model="gemini-3-flash-preview",
        step_config={"ocr_dpi": 150, "strip_llm_artifacts": True},
    )

    dialog = StepAdvancedConfigDialog(route)
    dialog.ocr_dpi_spin.setValue(200)
    dialog.strip_artifacts_check.setChecked(False)

    updated = dialog.route()
    assert updated.step_config == {
        "ocr_dpi": 200,
        "strip_llm_artifacts": False,
    }


def test_workflow_profile_editor_only_shows_advanced_button_for_configurable_steps():
    from context_aware_translation.ui.features import workflow_profile_editor as editor_module

    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label="Translator",
                connection_id="conn-openai",
                connection_label="OpenAI",
                model="gpt-4.1-mini",
            ),
            WorkflowStepRoute(
                step_id=WorkflowStepId.IMAGE_REEMBEDDING,
                step_label="Image reembedding",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3.1-flash-image-preview",
            ),
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-openai",
                label="OpenAI",
                default_model="gpt-4.1-mini",
            ),
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3.1-flash-image-preview",
            ),
        ],
        allow_name_edit=True,
    )

    opened: list[WorkflowStepId] = []
    parent_widgets: list[QWidget | None] = []

    class _FakeStepDialog:
        def __init__(self, route: WorkflowStepRoute, parent=None, **_kwargs):
            opened.append(route.step_id)
            parent_widgets.append(parent)

        def exec(self):
            return QDialog.DialogCode.Rejected

    original = editor_module.StepAdvancedConfigDialog
    editor_module.StepAdvancedConfigDialog = _FakeStepDialog
    try:
        advanced_cell = dialog.routes_table.cellWidget(0, 3)
        assert advanced_cell is not None
        advanced_button = advanced_cell.findChild(QPushButton)
        assert advanced_button is not None
        advanced_button.click()
    finally:
        editor_module.StepAdvancedConfigDialog = original

    assert opened == [WorkflowStepId.TRANSLATOR]
    assert parent_widgets == [dialog]
    assert dialog.routes_table.item(1, 3).text() == "—"


def test_image_reembedding_backend_is_inferred_when_profile_payload_is_built():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.IMAGE_REEMBEDDING,
                step_label="Image reembedding",
                connection_id="conn-openai",
                connection_label="OpenAI",
                model="gpt-image-1",
            )
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-openai",
                label="OpenAI",
                default_model="gpt-image-1",
            )
        ],
        allow_name_edit=True,
    )

    built = dialog.profile()
    payload = build_workflow_profile_payload(base_config={}, profile=built)

    assert payload["image_reembedding_config"]["backend"] == "openai"
    assert dialog.routes_table.item(0, 0).text() == "Image reembedding"
    assert dialog.routes_table.item(0, 3).text() == "—"


def test_translator_batch_model_is_edited_from_main_model_column():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR_BATCH,
                step_label="Translator batch",
                connection_id=None,
                connection_label="Gemini AI Studio",
                model="gemini-2.5-pro",
                step_config={
                    "provider": "gemini_ai_studio",
                    "api_key": "secret",
                    "batch_size": 100,
                    "thinking_mode": "auto",
                },
            )
        ],
    )
    dialog = WorkflowProfileEditorDialog(profile=profile, connection_choices=[], allow_name_edit=True)

    batch_row = dialog._rows[0]
    assert batch_row.connection_combo is None
    assert batch_row.model_edit.isReadOnly() is False
    batch_row.model_edit.setText("gemini-2.5-flash")

    built = dialog.profile()
    payload = build_workflow_profile_payload(base_config={}, profile=built)

    assert dialog.routes_table.item(0, 0).text() == "Translator batch"
    assert dialog.routes_table.item(0, 1).text() == "Gemini AI Studio"
    assert payload["translator_batch_config"]["provider"] == "gemini_ai_studio"
    assert payload["translator_batch_config"]["model"] == "gemini-2.5-flash"
