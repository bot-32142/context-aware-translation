from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    ActionState,
    BlockerCode,
    BlockerInfo,
    DocumentRef,
    ProgressInfo,
    ProjectRef,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import (
    DocumentSection,
    DocumentTranslationState,
    DocumentWorkspaceState,
    TranslationUnitActionState,
    TranslationUnitKind,
    TranslationUnitState,
)
from tests.application.fakes import FakeDocumentService

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    QApplication = None
    QMessageBox = None
    QStackedWidget = None
    QPoint = None
    QTest = None
    Qt = None
    QTextEdit = None
    QVBoxLayout = None
    QWidget = None
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")

_QAPPLICATION = cast(Any, QApplication)
_QMESSAGEBOX = cast(Any, QMessageBox)
_QPOINT = cast(Any, QPoint)
_QSTACKEDWIDGET = cast(Any, QStackedWidget)
_QTEST = cast(Any, QTest)
_QT = cast(Any, Qt)
_QTEXTEDIT = cast(Any, QTextEdit)
_QVBOXLAYOUT = cast(Any, QVBoxLayout)
_QWIDGET = cast(Any, QWidget)


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = _QAPPLICATION.instance()
    if app is None:
        app = _QAPPLICATION([])
    yield app


def _make_state() -> DocumentTranslationState:
    workspace = DocumentWorkspaceState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        document=DocumentRef(document_id=4, order_index=4, label="04.png"),
        active_tab=DocumentSection.TRANSLATION,
    )
    return DocumentTranslationState(
        workspace=workspace,
        units=[
            TranslationUnitState(
                unit_id="1",
                unit_kind=TranslationUnitKind.CHUNK,
                label="Chunk 1",
                status=SurfaceStatus.READY,
                source_text="One\nTwo",
                translated_text="Uno\nDos",
                line_count=2,
                actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
            ),
            TranslationUnitState(
                unit_id="2",
                unit_kind=TranslationUnitKind.PAGE,
                label="Page 2",
                status=SurfaceStatus.BLOCKED,
                source_text="",
                actions=TranslationUnitActionState(can_save=False, can_retranslate=False),
                blocker=BlockerInfo(code=BlockerCode.NOTHING_TO_DO, message="No OCR text detected on this page."),
            ),
        ],
        run_action=ActionState(enabled=True),
        batch_action=ActionState(enabled=True),
        supports_batch=True,
        current_unit_id="1",
    )


def _selected_range(view) -> tuple[int, int, str]:
    cursor = view.translation_text.textCursor()
    return cursor.selectionStart(), cursor.selectionEnd(), cursor.selectedText()


def _cursor_position(view) -> tuple[int, int, bool]:
    cursor = view.translation_text.textCursor()
    return cursor.position(), cursor.anchor(), cursor.hasSelection()


def _chrome_signal(view, name: str):
    root = view.chrome_host.rootObject()
    assert root is not None
    return getattr(cast(Any, root), name)


def _selected_row_color(view) -> tuple[int, int, int]:
    item = view.unit_list.item(view.unit_list.currentRow())
    rect = view.unit_list.visualItemRect(item)
    point = rect.topLeft()
    point.setX(rect.right() - 20)
    point.setY(rect.center().y())
    image = view.unit_list.viewport().grab().toImage()
    ratio = image.devicePixelRatio()
    color = image.pixelColor(int(point.x() * ratio), int(point.y() * ratio))
    return color.red(), color.green(), color.blue()


def _multiline_text(prefix: str, count: int) -> str:
    return "\n".join(f"{prefix} {index:03d}" for index in range(count))


def _top_visible_block_number(editor: Any) -> int:
    cursor = editor.cursorForPosition(_QPOINT(8, 8))
    return cursor.blockNumber()


class _OverlayHost(_QWIDGET):
    def __init__(self) -> None:
        super().__init__()
        layout = _QVBOXLAYOUT(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.chrome_host = _QWIDGET(self)
        self.chrome_host.setFixedHeight(88)
        layout.addWidget(self.chrome_host)
        self.content_stack = _QSTACKEDWIDGET(self)
        layout.addWidget(self.content_stack, 1)


def test_document_translation_view_renders_units_and_routes_actions():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "documentTranslationPaneChrome"
        assert root.property("translateLabelText") == "Translate"
        assert root.property("canTranslate") is True
        assert root.property("supportsBatch") is True
        assert root.property("canBatch") is True
        assert root.property("translateTooltipText") == (
            "Translate all pending units in this document with the current settings."
        )
        assert root.property("batchTooltipText") == ("Submit this document as an asynchronous batch translation job.")
        assert view.unit_list.count() == 2
        assert view.viewmodel.can_translate is True
        assert view.viewmodel.can_batch is True
        assert view.save_button.isEnabled()
        assert view.retranslate_button.isEnabled()
        assert not view.previous_button.isEnabled()
        assert view.next_button.isEnabled()

        view.translation_text.setPlainText("One\nTwo updated")
        view.save_button.click()
        _chrome_signal(view, "translateRequested").emit()
        _chrome_signal(view, "polishToggled").emit(False)
        _chrome_signal(view, "batchRequested").emit()

        with patch.object(_QMESSAGEBOX, "question", return_value=_QMESSAGEBOX.StandardButton.Yes):
            view.retranslate_button.click()

        call_names = [name for name, _payload in service.calls]
        translation_calls = [payload for name, payload in service.calls if name == "run_translation"]
        assert "run_translation" in call_names
        assert "save_translation" in call_names
        assert "retranslate" in call_names
        assert view.viewmodel.polish_enabled is False
        assert len(translation_calls) == 2
        assert sum(1 for payload in translation_calls if not payload.batch) == 1
        assert sum(1 for payload in translation_calls if payload.batch) == 1
        assert any(payload.enable_polish for payload in translation_calls if not payload.batch)
        assert any(not payload.enable_polish for payload in translation_calls if payload.batch)
        view.next_button.click()
        assert view.unit_list.currentRow() == 1
    finally:
        view.deleteLater()


def test_document_translation_view_uses_side_by_side_plain_text_editors_and_hidden_find_panel():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.resize(1280, 760)
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()

        assert view.editor_splitter.orientation() == _QT.Orientation.Horizontal
        assert view.source_text.lineWrapMode() == _QTEXTEDIT.LineWrapMode.WidgetWidth
        assert view.translation_text.lineWrapMode() == _QTEXTEDIT.LineWrapMode.WidgetWidth
        assert view.source_text.isReadOnly()
        assert not view.find_panel.isVisible()
        assert view.find_panel.parentWidget() is view
        assert view.find_hint_button.parentWidget() is view.translation_header
        assert view.find_hint_button.text() == "Find/replace · Ctrl/Cmd+F"
        assert not hasattr(view, "selection_label")
        header_label_y = view.translation_label.mapTo(view.translation_header, _QPOINT(0, 0)).y()
        header_button_y = view.find_hint_button.mapTo(view.translation_header, _QPOINT(0, 0)).y()
        assert abs(header_label_y - header_button_y) <= 4
        initial_source_height = view.source_text.height()
        initial_translation_height = view.translation_text.height()
        assert abs(initial_source_height - initial_translation_height) <= 1

        view.find_input.setText("needle")
        view.find_hint_button.click()
        _QAPPLICATION.processEvents()
        assert view.find_panel.isVisible()
        assert view.replace_panel.isVisible()
        assert view.find_mode_panel.isVisible()
        assert not view.find_mode_summary_label.isVisible()
        assert view.show_replace_button.isChecked()
        assert view.literal_mode_button.isChecked()
        assert view.find_feedback_label.text() == "Literal mode searches exact text."
        assert view.find_input.text() == "needle"
        panel_bottom = (
            view.translation_text.viewport()
            .mapFromGlobal(view.find_panel.mapToGlobal(view.find_panel.rect().bottomLeft()))
            .y()
        )
        assert view.translation_text.height() == initial_translation_height
        assert view.source_text.height() == initial_source_height
        assert view.find_panel.geometry().top() < view.translation_text.mapTo(view, _QPOINT(0, 0)).y()
        assert panel_bottom < view.translation_text.viewport().height()
        original_panel_pos = view.find_panel.pos()
        drag_start = view.find_panel_header.rect().center()
        drag_end = drag_start + _QPOINT(-48, 24)
        _QTEST.mousePress(view.find_panel_header, _QT.MouseButton.LeftButton, pos=drag_start)
        _QTEST.mouseMove(view.find_panel_header, drag_end)
        _QTEST.mouseRelease(view.find_panel_header, _QT.MouseButton.LeftButton, pos=drag_end)
        _QAPPLICATION.processEvents()
        assert view.find_panel.pos() != original_panel_pos

        view.regex_mode_button.click()
        _QAPPLICATION.processEvents()
        assert view.regex_mode_button.isChecked()
        assert view.find_feedback_label.text() == "Regex mode supports capture groups. Use $1, $2, ... in replace."

        view.show_replace_button.click()
        _QAPPLICATION.processEvents()
        assert not view.replace_panel.isVisible()
        assert not view.find_mode_panel.isVisible()
        assert not view.show_replace_button.isChecked()
        assert view.regex_mode_button.isChecked()
        assert view.find_mode_summary_label.isVisible()
        assert view.find_mode_summary_label.text() == "Regex"
        assert view.find_feedback_label.text() == "Regex mode supports capture groups. Use $1, $2, ... in replace."

        view._hide_find_panel()
        _QAPPLICATION.processEvents()
        assert not view.find_panel.isVisible()
        assert not view.show_replace_button.isChecked()
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_places_find_panel_above_editor_when_hosted_in_shell():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    host = _OverlayHost()
    view = DocumentTranslationView(service, "proj-1", 4)
    host.content_stack.addWidget(view)
    try:
        host.resize(1440, 900)
        host.show()
        view.refresh()
        _QAPPLICATION.processEvents()

        view.find_hint_button.click()
        _QAPPLICATION.processEvents()

        assert view.find_panel.isVisible()
        assert view.find_panel.parentWidget() is host
        assert "QFrame#translationFindPanel" in view.find_panel.styleSheet()
        assert "QPushButton" in view.find_panel.styleSheet()
        panel_top = view.find_panel.geometry().top()
        panel_bottom = view.find_panel.geometry().bottom()
        view_top = view.mapTo(host, _QPOINT(0, 0)).y()
        editor_top = view.translation_text.mapTo(host, _QPOINT(0, 0)).y()
        assert panel_top < view_top
        assert panel_bottom < editor_top

        view.hide()
        _QAPPLICATION.processEvents()
        assert not view.find_panel.isVisible()
        assert view.find_panel.parentWidget() is view
    finally:
        host.close()
        host.deleteLater()


def test_document_translation_view_uses_stable_selection_fill_for_unit_list():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.resize(1080, 720)
        view.show()
        view.refresh()
        view.unit_list.setFocus()
        view.unit_list.setCurrentRow(0)
        _QAPPLICATION.processEvents()

        red, green, blue = _selected_row_color(view)
        assert abs(red - 239) <= 20
        assert abs(green - 231) <= 20
        assert abs(blue - 218) <= 20
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_disables_editing_for_blocked_page():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        view.unit_list.setCurrentRow(1)

        assert not view.save_button.isEnabled()
        assert not view.retranslate_button.isEnabled()
        assert view.translation_text.isReadOnly()
        assert "No OCR text detected" in view.blocker_label.text()
    finally:
        view.deleteLater()


def test_document_translation_view_refreshes_batch_visibility_when_polish_toggle_changes():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    class _DynamicDocumentService(FakeDocumentService):
        def get_translation(self, project_id: str, document_id: int, *, enable_polish: bool = True):
            self.calls.append(("get_translation", (project_id, document_id, enable_polish)))
            state = _make_state()
            if enable_polish:
                return state.model_copy(
                    update={
                        "supports_batch": False,
                        "batch_action": ActionState(enabled=False),
                    }
                )
            return state

    service = _DynamicDocumentService(workspace=_make_state().workspace, translation=_make_state())
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.property("supportsBatch") is False

        _chrome_signal(view, "polishToggled").emit(False)
        _QAPPLICATION.processEvents()

        assert root.property("supportsBatch") is True
        get_translation_calls = [payload for name, payload in service.calls if name == "get_translation"]
        assert get_translation_calls[-2:] == [("proj-1", 4, True), ("proj-1", 4, False)]
    finally:
        view.deleteLater()


def test_document_translation_view_find_next_uses_live_cursor_position_and_wraps():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        view.translation_text.setPlainText("alpha beta alpha beta alpha")
        view.find_input.setText("alpha")

        view.find_next_button.click()
        assert _selected_range(view) == (0, 5, "alpha")

        cursor = view.translation_text.textCursor()
        cursor.clearSelection()
        cursor.setPosition(17)
        view.translation_text.setTextCursor(cursor)

        view.find_next_button.click()
        assert _selected_range(view) == (22, 27, "alpha")

        view.find_next_button.click()
        assert _selected_range(view) == (0, 5, "alpha")
    finally:
        view.deleteLater()


def test_document_translation_view_replace_mode_stays_open_while_finding_and_replacing():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()
        view.translation_text.setPlainText("alpha beta alpha beta")
        view.find_input.setText("alpha")
        view.replace_input.setText("omega")
        view._show_replace_panel()
        _QAPPLICATION.processEvents()

        view.find_next_button.click()
        assert view.replace_panel.isVisible()
        assert view.show_replace_button.isChecked()

        view.replace_button.click()
        _QAPPLICATION.processEvents()
        assert view.replace_panel.isVisible()
        assert view.show_replace_button.isChecked()
        assert view.translation_text.toPlainText() == "omega beta alpha beta"
        assert _selected_range(view) == (11, 16, "alpha")
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_regex_find_replace_supports_group_references():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()
        view.translation_text.setPlainText("cat-01 dog-22 cat-33")
        view._show_replace_panel()
        view.regex_mode_button.click()
        _QAPPLICATION.processEvents()

        view.find_input.setText(r"(cat)-(\d+)")
        view.replace_input.setText(r"$1[$2]")

        view.find_next_button.click()
        assert _selected_range(view) == (0, 6, "cat-01")
        assert "capture groups" in view.find_feedback_label.text()

        view.replace_button.click()
        _QAPPLICATION.processEvents()
        assert view.translation_text.toPlainText() == "cat[01] dog-22 cat-33"

        view.replace_all_button.click()
        _QAPPLICATION.processEvents()
        assert view.translation_text.toPlainText() == "cat[01] dog-22 cat[33]"
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_regex_find_next_supports_zero_width_matches():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()
        view.translation_text.setPlainText("alpha\nbeta\ngamma")
        cursor = view.translation_text.textCursor()
        cursor.setPosition(1)
        view.translation_text.setTextCursor(cursor)
        view.regex_mode_button.click()
        _QAPPLICATION.processEvents()

        view.find_input.setText("^")

        view.find_next_button.click()
        assert _cursor_position(view) == (6, 6, False)

        view.find_next_button.click()
        assert _cursor_position(view) == (11, 11, False)

        view.find_next_button.click()
        assert _cursor_position(view) == (0, 0, False)
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_wildcard_find_replace_supports_group_references():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()
        view.translation_text.setPlainText("cat-01 dog-22 cat-33")
        view._show_replace_panel()
        view.wildcard_mode_button.click()
        _QAPPLICATION.processEvents()

        view.find_input.setText("cat-??")
        view.replace_input.setText("match-$1$2")

        view.find_next_button.click()
        assert _selected_range(view) == (0, 6, "cat-01")
        assert "Wildcard mode" in view.find_feedback_label.text()

        view.replace_all_button.click()
        _QAPPLICATION.processEvents()
        assert view.translation_text.toPlainText() == "match-01 dog-22 match-33"
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_find_next_advances_across_units_and_wraps():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    state = state.model_copy(
        update={
            "units": [
                state.units[0].model_copy(update={"translated_text": "alpha beta alpha beta"}),
                state.units[1].model_copy(
                    update={
                        "status": SurfaceStatus.READY,
                        "source_text": "Three",
                        "translated_text": "gamma alpha",
                        "blocker": None,
                        "actions": TranslationUnitActionState(can_save=True, can_retranslate=True),
                    }
                ),
            ]
        }
    )
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        view.find_input.setText("alpha")

        view.find_next_button.click()
        assert view.unit_list.currentRow() == 0
        assert _selected_range(view) == (0, 5, "alpha")

        view.find_next_button.click()
        assert view.unit_list.currentRow() == 0
        assert _selected_range(view) == (11, 16, "alpha")

        view.find_next_button.click()
        assert view.unit_list.currentRow() == 1
        assert _selected_range(view) == (6, 11, "alpha")

        view.find_next_button.click()
        assert view.unit_list.currentRow() == 0
        assert _selected_range(view) == (0, 5, "alpha")
    finally:
        view.deleteLater()


def test_document_translation_view_preserves_dirty_drafts_across_unit_navigation_find_and_refresh():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    state = state.model_copy(
        update={
            "units": [
                state.units[0].model_copy(update={"translated_text": "alpha one"}),
                state.units[1].model_copy(
                    update={
                        "status": SurfaceStatus.READY,
                        "source_text": "Two",
                        "translated_text": "beta alpha",
                        "blocker": None,
                        "actions": TranslationUnitActionState(can_save=True, can_retranslate=True),
                    }
                ),
            ]
        }
    )
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        view.translation_text.setPlainText("draft alpha one")

        view.unit_list.setCurrentRow(1)
        assert view.translation_text.toPlainText() == "beta alpha"

        view.unit_list.setCurrentRow(0)
        assert view.translation_text.toPlainText() == "draft alpha one"

        view.find_input.setText("beta")
        view.find_next_button.click()
        assert view.unit_list.currentRow() == 1

        view.unit_list.setCurrentRow(0)
        assert view.translation_text.toPlainText() == "draft alpha one"

        refreshed_state = state.model_copy(
            update={
                "units": [
                    state.units[0].model_copy(update={"translated_text": "persisted server text"}),
                    state.units[1],
                ]
            }
        )
        service.translation = refreshed_state
        view.refresh()
        assert view.translation_text.toPlainText() == "draft alpha one"

        _chrome_signal(view, "polishToggled").emit(False)
        assert view.translation_text.toPlainText() == "draft alpha one"
    finally:
        view.deleteLater()


def test_document_translation_view_retranslate_clears_only_target_unit_draft_on_refresh():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state().model_copy(
        update={
            "units": [
                _make_state().units[0].model_copy(update={"translated_text": "server chunk v1"}),
                _make_state()
                .units[1]
                .model_copy(
                    update={
                        "status": SurfaceStatus.READY,
                        "source_text": "Page source",
                        "translated_text": "server page v1",
                        "blocker": None,
                        "actions": TranslationUnitActionState(can_save=True, can_retranslate=True),
                    }
                ),
            ]
        }
    )
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        view.translation_text.setPlainText("stale local chunk draft")

        view.unit_list.setCurrentRow(1)
        view.translation_text.setPlainText("keep local page draft")
        view.unit_list.setCurrentRow(0)

        service.translation = state.model_copy(
            update={
                "units": [
                    state.units[0].model_copy(update={"translated_text": "fresh backend chunk result"}),
                    state.units[1].model_copy(update={"translated_text": "fresh backend page result"}),
                ]
            }
        )

        with patch.object(_QMESSAGEBOX, "question", return_value=_QMESSAGEBOX.StandardButton.Yes):
            view.retranslate_button.click()

        assert view.translation_text.toPlainText() == "fresh backend chunk result"
        view.unit_list.setCurrentRow(1)
        assert view.translation_text.toPlainText() == "keep local page draft"
    finally:
        view.deleteLater()


def test_document_translation_view_full_translate_clears_document_drafts_on_refresh():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state().model_copy(
        update={
            "units": [
                _make_state().units[0].model_copy(update={"translated_text": "server chunk v1"}),
                _make_state()
                .units[1]
                .model_copy(
                    update={
                        "status": SurfaceStatus.READY,
                        "source_text": "Page source",
                        "translated_text": "server page v1",
                        "blocker": None,
                        "actions": TranslationUnitActionState(can_save=True, can_retranslate=True),
                    }
                ),
            ]
        }
    )
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        view.translation_text.setPlainText("stale local chunk draft")

        view.unit_list.setCurrentRow(1)
        view.translation_text.setPlainText("stale local page draft")
        view.unit_list.setCurrentRow(0)

        service.translation = state.model_copy(
            update={
                "units": [
                    state.units[0].model_copy(update={"translated_text": "fresh backend chunk result"}),
                    state.units[1].model_copy(update={"translated_text": "fresh backend page result"}),
                ]
            }
        )

        _chrome_signal(view, "translateRequested").emit()

        assert view.translation_text.toPlainText() == "fresh backend chunk result"
        view.unit_list.setCurrentRow(1)
        assert view.translation_text.toPlainText() == "fresh backend page result"
    finally:
        view.deleteLater()


def test_document_translation_view_shows_queue_message_over_progress_text():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state().model_copy(
        update={
            "progress": ProgressInfo(current=2, total=5, label="Running translation"),
            "active_task_id": "task-42",
        }
    )
    service = FakeDocumentService(
        workspace=state.workspace,
        translation=state,
        command_result=AcceptedCommand(
            command_name="run_translation",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Translation queued."),
        ),
    )
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        initial_progress = view.viewmodel.progress_text
        assert initial_progress == "Running translation | Progress: 2/5 | Active task: task-42"

        _chrome_signal(view, "translateRequested").emit()

        assert view.viewmodel.progress_text == "Translation queued."
    finally:
        view.deleteLater()


def test_document_translation_view_clears_transient_queue_message_on_refresh():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    running_state = _make_state().model_copy(
        update={
            "progress": ProgressInfo(current=2, total=5, label="Running translation"),
            "active_task_id": "task-42",
        }
    )
    service = FakeDocumentService(
        workspace=running_state.workspace,
        translation=running_state,
        command_result=AcceptedCommand(
            command_name="run_translation",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Translation queued."),
        ),
    )
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()

        _chrome_signal(view, "translateRequested").emit()

        assert view.viewmodel.progress_text == "Translation queued."

        service.translation = running_state.model_copy(
            update={"progress": ProgressInfo(current=3, total=5, label="Running translation")}
        )
        view.refresh()

        assert view.viewmodel.progress_text == "Running translation | Progress: 3/5 | Active task: task-42"
    finally:
        view.deleteLater()


def test_document_translation_view_find_next_keeps_match_below_floating_panel():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    lines = [f"line {index:03d}" for index in range(120)]
    lines[40] = "needle target line"
    translation_text = "\n".join(lines)
    state = _make_state()
    state = state.model_copy(
        update={
            "units": [
                state.units[0].model_copy(
                    update={
                        "source_text": _multiline_text("Source", 120),
                        "translated_text": translation_text,
                        "line_count": 120,
                    }
                ),
                state.units[1],
            ]
        }
    )
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.resize(1280, 760)
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()

        view._show_find_panel()
        view.find_input.setText("needle")
        cursor = view.translation_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        view.translation_text.setTextCursor(cursor)

        view.find_next_button.click()
        _QAPPLICATION.processEvents()

        panel_bottom = (
            view.translation_text.viewport()
            .mapFromGlobal(view.find_panel.mapToGlobal(view.find_panel.rect().bottomLeft()))
            .y()
        )
        assert view.translation_text.cursorRect().top() >= max(0, panel_bottom + 12)
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_text_edits_remain_undoable_after_layout_sync():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    state = state.model_copy(
        update={
            "units": [
                state.units[0].model_copy(
                    update={
                        "source_text": "\n".join([("wrapped source " * 16).strip() for _ in range(8)]),
                        "translated_text": _multiline_text("translation", 8),
                        "line_count": 8,
                    }
                ),
                state.units[1],
            ]
        }
    )
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.resize(1280, 760)
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()

        cursor = view.translation_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        view.translation_text.setTextCursor(cursor)
        view.translation_text.insertPlainText("!")
        _QAPPLICATION.processEvents()
        assert view.translation_text.toPlainText().endswith("!")

        view.translation_text.undo()
        _QAPPLICATION.processEvents()
        assert not view.translation_text.toPlainText().endswith("!")
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_find_next_keeps_cross_unit_match_visible_after_line_sync():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    long_source_lines = [("wrapped source " * 20).strip() for _ in range(40)] + ["needle source line"]
    translated_lines = [f"line {index:03d}" for index in range(40)] + ["needle target line"]
    state = _make_state()
    state = state.model_copy(
        update={
            "units": [
                state.units[0].model_copy(update={"translated_text": "alpha beta gamma"}),
                state.units[1].model_copy(
                    update={
                        "status": SurfaceStatus.READY,
                        "unit_kind": TranslationUnitKind.CHUNK,
                        "source_text": "\n".join(long_source_lines),
                        "translated_text": "\n".join(translated_lines),
                        "line_count": len(translated_lines),
                        "blocker": None,
                        "actions": TranslationUnitActionState(can_save=True, can_retranslate=True),
                    }
                ),
            ]
        }
    )
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.resize(1280, 760)
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()

        view._show_find_panel()
        view.find_input.setText("needle")
        view.find_next_button.click()
        _QAPPLICATION.processEvents()

        cursor_rect = view.translation_text.cursorRect()
        viewport_rect = view.translation_text.viewport().rect()
        panel_bottom = (
            view.translation_text.viewport()
            .mapFromGlobal(view.find_panel.mapToGlobal(view.find_panel.rect().bottomLeft()))
            .y()
        )
        assert view.unit_list.currentRow() == 1
        assert cursor_rect.top() >= max(0, panel_bottom + 12)
        assert cursor_rect.bottom() <= viewport_rect.bottom()
    finally:
        view.close()
        view.deleteLater()


def test_document_translation_view_keeps_source_and_translation_scroll_in_sync():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    dense_source = _multiline_text("Source", 120)
    dense_translation = _multiline_text("Translation", 120)
    state = state.model_copy(
        update={
            "units": [
                state.units[0].model_copy(
                    update={
                        "source_text": dense_source,
                        "translated_text": dense_translation,
                    }
                ),
                state.units[1],
            ]
        }
    )
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.resize(1280, 760)
        view.show()
        view.refresh()
        _QAPPLICATION.processEvents()

        source_bar = view.source_text.verticalScrollBar()
        translation_bar = view.translation_text.verticalScrollBar()
        assert source_bar.maximum() > 0
        assert translation_bar.maximum() > 0

        translation_bar.setValue(translation_bar.maximum() // 2)
        _QAPPLICATION.processEvents()
        assert abs(_top_visible_block_number(view.source_text) - _top_visible_block_number(view.translation_text)) <= 1

        source_bar.setValue(source_bar.maximum())
        _QAPPLICATION.processEvents()
        assert abs(_top_visible_block_number(view.source_text) - _top_visible_block_number(view.translation_text)) <= 1
    finally:
        view.close()
        view.deleteLater()
