from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
    ProjectRef,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.terms import (
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
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

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


def _make_state(*, can_review: bool = False, can_export: bool = False) -> TermsTableState:
    return TermsTableState(
        scope=TermsScope(
            kind=TermsScopeKind.PROJECT,
            project=ProjectRef(project_id="proj-1", name="One Piece"),
        ),
        toolbar=TermsToolbarState(
            can_translate_pending=True,
            can_review=can_review,
            can_filter_noise=True,
            can_import=True,
            can_export=can_export,
            review_blocker=(
                None if can_review else BlockerInfo(code=BlockerCode.NEEDS_SETUP, message="Review config missing.")
            ),
            export_blocker=(
                None
                if can_export
                else BlockerInfo(code=BlockerCode.NOTHING_TO_DO, message="No terms ready for export.")
            ),
        ),
        rows=[
            TermTableRow(
                term_id=1,
                term_key="ルフィ",
                term="ルフィ",
                translation="Luffy",
                description="Main character",
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
        assert not view.bulk_button.isEnabled()
        assert view.table_view.itemDelegateForColumn(1).__class__.__name__ == "_TranslationDelegate"

        view.search_input.setText("luffy")
        assert view.proxy_model.rowCount() == 1

        view.search_input.clear()
        view.filter_combo.setCurrentIndex(view.filter_combo.findData("untranslated"))
        assert view.proxy_model.rowCount() == 1
    finally:
        view.cleanup()


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
            view.table_view.selectRow(0)
            assert view.bulk_button.isEnabled()
            view.bulk_mark_reviewed_action.trigger()

        call_names = [name for name, _payload in service.calls]
        assert "translate_pending" in call_names
        assert "review_terms" in call_names
        assert "filter_noise" in call_names
        assert "import_terms" in call_names
        assert "export_terms" in call_names
        assert "update_term" in call_names
        assert "bulk_update_terms" in call_names
    finally:
        view.cleanup()


def test_terms_view_refreshes_on_terms_and_setup_invalidations():
    from context_aware_translation.ui.features.terms_view import TermsView

    service = FakeTermsService(project_state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = TermsView("proj-1", service, bus)
    try:
        bus.publish(TermsInvalidatedEvent(project_id="proj-1"))
        bus.publish(SetupInvalidatedEvent(project_id="proj-1"))

        get_state_calls = [name for name, _payload in service.calls if name == "get_project_terms"]
        assert len(get_state_calls) == 3
    finally:
        view.cleanup()
