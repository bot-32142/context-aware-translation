from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
    DocumentRef,
    ProjectRef,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.terms import (
    ExportTermsRequest,
    TermsScope,
    TermsScopeKind,
    TermsTableState,
    TermStatus,
    TermsToolbarState,
    TermTableRow,
)
from context_aware_translation.application.events import (
    InMemoryApplicationEventBus,
    SetupInvalidatedEvent,
    TermsInvalidatedEvent,
)
from tests.application.fakes import FakeTermsService

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFileDialog, QHeaderView, QMessageBox, QPushButton, QWidget

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
def _close_terms_top_levels():
    yield
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QWidget):
            widget.close()
            widget.deleteLater()
    QApplication.processEvents()


def _make_state(*, can_review: bool = False, can_export: bool = False, document_scope: bool = False) -> TermsTableState:
    return TermsTableState(
        scope=TermsScope(
            kind=TermsScopeKind.DOCUMENT if document_scope else TermsScopeKind.PROJECT,
            project=ProjectRef(project_id="proj-1", name="One Piece"),
            document=DocumentRef(document_id=4, order_index=4, label="04.png") if document_scope else None,
        ),
        toolbar=TermsToolbarState(
            can_build=document_scope,
            can_translate_pending=True,
            can_review=can_review,
            can_filter_noise=True,
            can_add_terms=not document_scope,
            can_import=not document_scope,
            can_export=(can_export and not document_scope),
            review_blocker=(
                None if can_review else BlockerInfo(code=BlockerCode.NEEDS_SETUP, message="Review config missing.")
            ),
            export_blocker=(
                None
                if can_export and not document_scope
                else BlockerInfo(code=BlockerCode.NOTHING_TO_DO, message="No terms ready for export.")
            ),
        ),
        rows=[
            TermTableRow(
                term_id=1,
                term_key="ルフィ",
                term="ルフィ",
                term_type="character",
                translation="Luffy",
                description="Main character",
                description_tooltip="1: Main character\n2: Captain of the Straw Hat Pirates",
                occurrences=4,
                votes=2,
                reviewed=False,
                ignored=False,
                status=TermStatus.NEEDS_REVIEW,
            ),
            TermTableRow(
                term_id=2,
                term_key="ニカ",
                term="ニカ",
                term_type="other",
                translation=None,
                description="Sun god",
                occurrences=1,
                votes=1,
                reviewed=False,
                ignored=False,
                status=TermStatus.NEEDS_TRANSLATION,
            ),
        ],
    )


def test_terms_view_renders_backend_state_and_local_filters():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        assert view.title_label.text() == view.tr("Terms")
        assert "shared" in view.scope_label.text().lower()
        assert view.proxy_model.rowCount() == 2
        assert view.translate_button.isEnabled()
        assert not view.review_button.isEnabled()
        assert not view.export_button.isEnabled()
        assert view.review_button.toolTip() == "Review config missing."
        assert not view.edit_selected_action.isEnabled()
        assert view.table_view.itemDelegateForColumn(1).__class__.__name__ == "_TranslationDelegate"
        assert view.table_view.horizontalHeader().sectionResizeMode(3) is QHeaderView.ResizeMode.Interactive
        assert view.table_view.horizontalHeader().sectionResizeMode(4) is QHeaderView.ResizeMode.Interactive
        assert view.table_view.horizontalHeader().sectionResizeMode(5) is QHeaderView.ResizeMode.Interactive
        assert view.table_view.horizontalHeader().sectionResizeMode(6) is QHeaderView.ResizeMode.Interactive

        view.search_input.setText("luffy")
        assert view.proxy_model.rowCount() == 1

        view.search_input.clear()
        view.filter_combo.setCurrentIndex(view.filter_combo.findData("untranslated"))
        assert view.proxy_model.rowCount() == 1
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_loads_qml_project_chrome_and_routes_toolbar_actions():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(
        project_state=_make_state(can_review=True, can_export=True),
        command_result=AcceptedCommand(
            command_name="terms-task",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "termsPaneChrome"
        assert root.property("titleText") == "Terms"
        assert root.property("showAdd") is True
        assert root.property("canAdd") is True
        assert root.property("canTranslate") is True
        assert root.property("canReview") is True
        assert root.property("canExport") is True
        assert root.property("addTooltipText") == "Add or update a shared term translation for this project."
        assert root.property("translateTooltipText") == (
            "Translate all currently untranslated glossary terms for the current scope."
        )
        assert root.property("reviewTooltipText") == (
            "Run an LLM review pass on unreviewed glossary terms for the current scope."
        )
        assert root.property("filterTooltipText") == (
            "Automatically ignore terms that occurred only once or were recognized by the LLM in only one chunk."
        )
        assert view.import_button.isHidden()
        assert view.export_button.isHidden()
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))
        assert view.import_button.isVisible() is False
        assert view.export_button.isVisible() is False
        assert view.import_button.isWindow() is False
        assert view.export_button.isWindow() is False

        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(QFileDialog, "getOpenFileName", return_value=("/tmp/glossary.json", "JSON Files (*.json)")),
            patch.object(QFileDialog, "getSaveFileName", return_value=("/tmp/out.json", "JSON Files (*.json)")),
        ):
            root.addRequested.emit()
            root.translateRequested.emit()
            root.reviewRequested.emit()
            root.filterRequested.emit()
            root.importRequested.emit()
            root.exportRequested.emit()

        call_names = [name for name, _payload in service.calls]
        assert "upsert_project_term" not in call_names
        assert "translate_pending" in call_names
        assert "review_terms" in call_names
        assert "filter_noise" in call_names
        assert "import_terms" in call_names
        assert "export_terms" in call_names

        root.setProperty("width", 220)
        root.setProperty(
            "tipText",
            "Terms are shared across the project and this explanatory copy should wrap once the chrome narrows.",
        )
        root.setProperty("translateLabelText", "Translate All Untranslated Project Terms Right Now")
        root.setProperty("reviewLabelText", "Review Terms With The Current Shared Workflow Profile")
        QApplication.processEvents()
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_export_warns_and_mentions_background_queue():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(
        project_state=_make_state(can_review=True, can_export=True),
        command_result=AcceptedCommand(command_name="export_terms"),
    )
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as question,
            patch.object(QFileDialog, "getSaveFileName", return_value=("/tmp/out.json", "JSON Files (*.json)")),
            patch.object(view, "_show_message") as show_message,
        ):
            view.export_button.click()

        question.assert_called_once()
        assert (
            "export_terms",
            ExportTermsRequest(project_id="proj-1", output_path="/tmp/out.json", document_id=None),
        ) in service.calls
        show_message.assert_called_once()
        severity, text = show_message.call_args.args
        assert severity is UserMessageSeverity.INFO
        assert "background" in text.lower()
        assert "queue" in text.lower()
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_export_cancel_skips_file_dialog_and_service():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state(can_review=True, can_export=True))
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No),
            patch.object(QFileDialog, "getSaveFileName") as get_save_file_name,
        ):
            view.export_button.click()

        get_save_file_name.assert_not_called()
        assert not any(name == "export_terms" for name, _payload in service.calls)
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_loads_qml_document_chrome_and_routes_document_actions():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(
        project_state=_make_state(document_scope=False),
        document_state=_make_state(document_scope=True, can_review=True),
        command_result=AcceptedCommand(
            command_name="terms-task",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus, document_id=4, embedded=True)
    try:
        view.refresh()
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "termsPaneChrome"
        assert root.property("showBuild") is True
        assert root.property("showAdd") is False
        assert root.property("showImport") is False
        assert root.property("showExport") is False
        assert root.property("canBuild") is True
        assert root.property("canTranslate") is True
        assert root.property("canReview") is True
        assert root.property("buildTooltipText") == "Extract terms from this document."
        assert root.property("filterTooltipText") == "Ignore rare terms for this document."
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            root.buildRequested.emit()
            root.translateRequested.emit()
            root.reviewRequested.emit()
            root.filterRequested.emit()

        call_names = [name for name, _payload in service.calls]
        assert "build_terms" in call_names
        assert "translate_pending" in call_names
        assert "review_terms" in call_names
        assert "filter_noise" in call_names

        root.setProperty("width", 220)
        root.setProperty(
            "tipText",
            "Terms here are scoped to the current document and this copy should wrap when the chrome narrows.",
        )
        root.setProperty("buildLabelText", "Build Terms From The Current Document Before Review")
        QApplication.processEvents()
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_add_terms_dialog_batches_rows_and_applies_from_popup():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state(can_review=True, can_export=True))
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        view.show()
        QApplication.processEvents()
        root = view.chrome_host.rootObject()
        assert root is not None

        root.addRequested.emit()
        dialog = view._add_terms_dialog
        assert dialog is not None
        assert dialog.isVisible() is True

        dialog.term_input.setText("ギア5")
        dialog.translation_input.setText("Gear 5")
        dialog.add_button.click()
        assert dialog.pending_terms() == [("ギア5", "Gear 5")]
        assert not any(name == "upsert_project_term" for name, _payload in service.calls)

        dialog.term_input.setText("ニカ")
        dialog.translation_input.setText("Nika")
        dialog.add_button.click()
        assert dialog.pending_terms() == [("ギア5", "Gear 5"), ("ニカ", "Nika")]

        delete_buttons = dialog.findChildren(QPushButton, "termsAddDeleteButton")
        assert len(delete_buttons) == 2
        delete_buttons[0].click()
        assert dialog.pending_terms() == [("ニカ", "Nika")]

        dialog.term_input.setText("ルフィ")
        dialog.translation_input.setText("Monkey D. Luffy")
        dialog.add_button.click()
        assert dialog.pending_terms() == [("ニカ", "Nika"), ("ルフィ", "Monkey D. Luffy")]

        dialog.apply_button.click()

        upsert_requests = [payload for name, payload in service.calls if name == "upsert_project_term"]
        assert [request.term for request in upsert_requests] == ["ニカ", "ルフィ"]
        assert [request.translation for request in upsert_requests] == ["Nika", "Monkey D. Luffy"]
        assert dialog.isVisible() is True
        assert dialog.term_input.text() == ""
        assert dialog.translation_input.text() == ""
        assert dialog.pending_terms() == []
        assert dialog.status_label.text() == "Terms saved."
        assert any(
            row.term_key == "ルフィ" and row.translation == "Monkey D. Luffy" and row.reviewed and not row.ignored
            for row in view.table_panel.rows_snapshot()
        )
        assert any(
            row.term_key == "ニカ" and row.translation == "Nika" and row.reviewed and not row.ignored
            for row in view.table_panel.rows_snapshot()
        )
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_add_terms_dialog_validates_required_fields():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state(can_review=True, can_export=True))
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        view.show()
        QApplication.processEvents()
        view._open_add_terms_dialog()
        dialog = view._add_terms_dialog
        assert dialog is not None

        dialog.add_button.click()
        assert dialog.status_label.text() == "Term is required."

        dialog.term_input.setText("ギア5")
        dialog.add_button.click()
        assert dialog.status_label.text() == "Translation is required."
        assert not any(name == "upsert_project_term" for name, _payload in service.calls)
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_loads_qml_document_chrome_and_routes_build_actions():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(
        project_state=_make_state(),
        document_state=_make_state(document_scope=True),
        command_result=AcceptedCommand(
            command_name="terms-task",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )
    view = TermsView("proj-1", service, None, document_id=4, embedded=True)
    try:
        view.refresh()
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "termsPaneChrome"
        assert root.property("showTitle") is False
        assert root.property("showBuild") is True
        assert root.property("showImport") is False
        assert root.property("showExport") is False
        assert root.property("canBuild") is True

        root.buildRequested.emit()
        root.translateRequested.emit()

        call_names = [name for name, _payload in service.calls]
        assert "build_terms" in call_names
        assert "translate_pending" in call_names
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_routes_edits_and_toolbar_actions_through_service():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(
        project_state=_make_state(can_review=True, can_export=True),
        command_result=AcceptedCommand(
            command_name="terms-task",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(QFileDialog, "getOpenFileName", return_value=("/tmp/glossary.json", "JSON Files (*.json)")),
            patch.object(QFileDialog, "getSaveFileName", return_value=("/tmp/out.json", "JSON Files (*.json)")),
        ):
            view.translate_button.click()
            view.review_button.click()
            view.filter_noise_button.click()
            view.import_button.click()
            view.export_button.click()

            translation_item = view.table_model.item(0, 1)
            translation_item.setText("Monkey D. Luffy")
            description_item = view.table_model.item(0, 2)
            assert not description_item.isEditable()
            ignored_item = view.table_model.item(0, 5)
            ignored_item.setCheckState(Qt.CheckState.Checked)
            reviewed_item = view.table_model.item(0, 6)
            reviewed_item.setCheckState(Qt.CheckState.Checked)
            bulk_proxy_row = next(
                row for row in range(view.proxy_model.rowCount()) if view.proxy_model.index(row, 0).data() == "ニカ"
            )
            view.table_view.selectRow(bulk_proxy_row)
            assert view.edit_selected_action.isEnabled()
            view.bulk_mark_reviewed_action.trigger()

        call_names = [name for name, _payload in service.calls]
        assert "translate_pending" in call_names
        assert "review_terms" in call_names
        assert "filter_noise" in call_names
        assert "import_terms" in call_names
        assert "export_terms" in call_names
        assert "update_term_rows" in call_names
        assert "bulk_update_terms" in call_names

        update_requests = [payload for name, payload in service.calls if name == "update_term_rows"]
        assert any(payload.rows[0].translation == "Monkey D. Luffy" for payload in update_requests)
        assert any(payload.rows[0].ignored is True for payload in update_requests)
        assert any(payload.rows[0].reviewed is True for payload in update_requests)
        nika_source_row = next(
            row for row in range(view.table_model.rowCount()) if view.table_model.item(row, 0).text() == "ニカ"
        )
        assert view.table_model.item(nika_source_row, 6).checkState() == Qt.CheckState.Checked
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_refreshes_on_terms_and_setup_invalidations():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        view.show()
        QApplication.processEvents()
        bus.publish(TermsInvalidatedEvent(project_id="proj-1"))
        bus.publish(SetupInvalidatedEvent(project_id="proj-1"))

        get_state_calls = [name for name, _payload in service.calls if name == "get_project_terms"]
        assert len(get_state_calls) == 3
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_refreshes_toolbar_after_local_review_toggle_without_full_reload():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state(can_review=True, can_export=True))
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        initial_get_terms = [name for name, _payload in service.calls if name == "get_project_terms"]
        assert len(initial_get_terms) == 1
        assert view.review_button.isEnabled()
        assert view.filter_noise_button.isEnabled()

        reviewed_item = view.table_model.item(0, 6)
        reviewed_item.setCheckState(Qt.CheckState.Checked)

        assert (
            view.review_button.isEnabled()
            == service.get_toolbar_state(
                "proj-1",
                rows=view.table_panel.rows_snapshot(),
            ).can_review
        )
        expected_toolbar = service.get_toolbar_state(
            "proj-1",
            rows=view.table_panel.rows_snapshot(),
        )
        assert view.filter_noise_button.isEnabled() == expected_toolbar.can_filter_noise
        assert [name for name, _payload in service.calls if name == "get_toolbar_state"] == [
            "get_toolbar_state",
            "get_toolbar_state",
            "get_toolbar_state",
        ]
        assert [name for name, _payload in service.calls if name == "get_project_terms"] == initial_get_terms
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_description_tooltip_and_header_tooltips_are_restored():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        description_index = view.table_model.index(0, 2)
        assert (
            view.table_model.data(description_index, Qt.ItemDataRole.ToolTipRole)
            == "1: Main character\n2: Captain of the Straw Hat Pirates"
        )

        header_tooltip = view.table_model.headerData(2, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
        assert "only context summaries ending at or before the current chunk are sent" in header_tooltip
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_defers_hidden_document_refresh_until_activated():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(
        project_state=_make_state(),
        document_state=_make_state(document_scope=True),
    )
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus, document_id=4, embedded=True)
    try:
        view.show()
        view.refresh()
        QApplication.processEvents()
        assert [name for name, _payload in service.calls if name == "get_document_terms"] == ["get_document_terms"]

        view.hide()
        QApplication.processEvents()
        bus.publish(TermsInvalidatedEvent(project_id="proj-1"))
        assert [name for name, _payload in service.calls if name == "get_document_terms"] == ["get_document_terms"]

        view.activate_view()
        assert [name for name, _payload in service.calls if name == "get_document_terms"] == [
            "get_document_terms",
            "get_document_terms",
        ]
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_sorting_and_live_updates_follow_legacy_glossary_behavior():
    from context_aware_translation.ui.features.terms_view import TermsView

    state = TermsTableState(
        scope=TermsScope(
            kind=TermsScopeKind.PROJECT,
            project=ProjectRef(project_id="proj-1", name="One Piece"),
        ),
        toolbar=TermsToolbarState(),
        rows=[
            TermTableRow(
                term_id=1,
                term_key="a",
                term="A",
                term_type="other",
                translation="",
                description="desc a",
                description_sort_key=3,
                occurrences=2,
                votes=2,
                ignored=False,
                reviewed=False,
                status=TermStatus.NEEDS_REVIEW,
            ),
            TermTableRow(
                term_id=3,
                term_key="c",
                term="C",
                term_type="character",
                translation="",
                description="desc c",
                description_sort_key=1,
                occurrences=2,
                votes=1,
                ignored=False,
                reviewed=True,
                status=TermStatus.READY,
            ),
            TermTableRow(
                term_id=2,
                term_key="b",
                term="B",
                term_type="organization",
                translation="",
                description="desc b",
                description_sort_key=2,
                occurrences=3,
                votes=1,
                ignored=False,
                reviewed=False,
                status=TermStatus.NEEDS_REVIEW,
            ),
            TermTableRow(
                term_id=4,
                term_key="d",
                term="D",
                term_type="other",
                translation="",
                description="desc d",
                description_sort_key=4,
                occurrences=1,
                votes=1,
                ignored=True,
                reviewed=False,
                status=TermStatus.IGNORED,
            ),
        ],
    )
    service = FakeTermsService(project_state=state)

    def _update_term_rows(request):  # noqa: ANN001
        service.calls.append(("update_term_rows", request))
        updates_by_key = {row.term_key: row for row in request.rows}
        service.project_state = service.project_state.model_copy(
            update={"rows": [updates_by_key.get(row.term_key, row) for row in service.project_state.rows]}
        )
        return None

    service.update_term_rows = _update_term_rows
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        view.table_view.sortByColumn(3, Qt.SortOrder.AscendingOrder)
        ordered_terms = [view.proxy_model.index(row, 0).data() for row in range(view.proxy_model.rowCount())]
        assert ordered_terms == ["D", "A", "C", "B"]

        view.table_view.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        ordered_terms = [view.proxy_model.index(row, 0).data() for row in range(view.proxy_model.rowCount())]
        assert ordered_terms == ["B", "A", "C", "D"]

        view.table_view.sortByColumn(4, Qt.SortOrder.AscendingOrder)
        ordered_terms = [view.proxy_model.index(row, 0).data() for row in range(view.proxy_model.rowCount())]
        assert ordered_terms == ["B", "C", "D", "A"]

        view.table_view.sortByColumn(6, Qt.SortOrder.AscendingOrder)
        ordered_terms = [view.proxy_model.index(row, 0).data() for row in range(view.proxy_model.rowCount())]
        assert ordered_terms == ["B", "D", "A", "C"]

        view.table_view.sortByColumn(5, Qt.SortOrder.AscendingOrder)
        ordered_terms = [view.proxy_model.index(row, 0).data() for row in range(view.proxy_model.rowCount())]
        assert ordered_terms == ["B", "A", "C", "D"]

        view.table_view.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        ordered_terms = [view.proxy_model.index(row, 0).data() for row in range(view.proxy_model.rowCount())]
        assert ordered_terms == ["C", "B", "A", "D"]

        view.table_model.item(3, 1).setText("Ace")
        view.table_model.item(0, 1).setText("Luffy")
        view.table_model.item(3, 5).setCheckState(Qt.CheckState.Unchecked)

        view.filter_combo.setCurrentIndex(view.filter_combo.findData("translated"))
        view.table_view.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        ordered_terms = [view.proxy_model.index(row, 0).data() for row in range(view.proxy_model.rowCount())]
        assert ordered_terms == ["D", "A"]

        view.filter_combo.setCurrentIndex(view.filter_combo.findData("ignored"))
        assert view.proxy_model.rowCount() == 0
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_context_menu_selects_row_and_copies_description():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        view.show()
        QApplication.processEvents()
        first_rect = view.table_view.visualRect(view.proxy_model.index(0, 0))
        expected_term = view.proxy_model.index(0, 0).data()
        with patch.object(QApplication.clipboard(), "setText") as set_text:
            view._show_context_menu(first_rect.center())
            assert view.edit_selected_action.isEnabled()
            assert view.table_panel.selected_rows()[0].term == expected_term
            actions = {action.text(): action for action in view._context_menu.actions() if action.text()}
            assert "Edit Selected" in actions
            assert "Copy Description" in actions
            actions["Copy Description"].trigger()
        expected_description = view.proxy_model.index(0, 2).data(Qt.ItemDataRole.ToolTipRole)
        set_text.assert_called_once_with(expected_description)
    finally:
        view.cleanup()
        view.deleteLater()


def test_terms_view_context_menu_preserves_multi_selection_and_edit_selected_opens_editors():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        view.show()
        QApplication.processEvents()
        second_rect = view.table_view.visualRect(view.proxy_model.index(1, 0))

        view.table_panel._toggle_row_selection(0)
        view.table_panel._toggle_row_selection(1)
        QApplication.processEvents()

        assert len(view.table_panel.selected_rows()) == 2

        view._show_context_menu(second_rect.center())
        assert len(view.table_panel.selected_rows()) == 2

        view.edit_selected_action.trigger()
        QApplication.processEvents()
        assert view.table_view.isPersistentEditorOpen(view.proxy_model.index(0, 1))
        assert view.table_view.isPersistentEditorOpen(view.proxy_model.index(1, 1))
    finally:
        view.cleanup()
        view.deleteLater()
