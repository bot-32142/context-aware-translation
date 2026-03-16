from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.ui.viewmodels.base import ViewModelBase

_PROJECT_TIP_TEXT = (
    "Terms are shared across the project. Build terms from document pages in "
    "document Terms, then translate, review, filter, import, or export them here."
)
_DOCUMENT_TIP_TEXT = (
    "Terms here are scoped to the current document. Build terms from page text, "
    "then translate, review, or filter only this document's glossary candidates."
)


class TermsPaneViewModel(ViewModelBase):
    """QML-facing chrome state for project or document terms surfaces."""

    labels_changed = Signal()
    chrome_state_changed = Signal()

    def __init__(self, *, document_scope: bool, embedded: bool, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._document_scope = document_scope
        self._embedded = embedded
        self._can_build = False
        self._can_translate = False
        self._can_review = False
        self._can_filter = False
        self._can_import = False
        self._can_export = False
        self._build_tooltip = ""
        self._translate_tooltip = ""
        self._review_tooltip = ""
        self._filter_tooltip = ""
        self._import_tooltip = ""
        self._export_tooltip = ""

    @Property(str, notify=labels_changed)
    def title(self) -> str:
        return QCoreApplication.translate("TermsView", "Terms")

    @Property(bool, notify=labels_changed)
    def show_title(self) -> bool:
        return not self._embedded

    @Property(str, notify=labels_changed)
    def tip_text(self) -> str:
        tip_text = _DOCUMENT_TIP_TEXT if self._document_scope else _PROJECT_TIP_TEXT
        return QCoreApplication.translate("TermsView", tip_text)

    @Property(str, notify=labels_changed)
    def build_label(self) -> str:
        return QCoreApplication.translate("TermsView", "Build Terms")

    @Property(str, notify=labels_changed)
    def translate_label(self) -> str:
        return QCoreApplication.translate("TermsView", "Translate Untranslated")

    @Property(str, notify=labels_changed)
    def review_label(self) -> str:
        return QCoreApplication.translate("TermsView", "Review Terms")

    @Property(str, notify=labels_changed)
    def filter_label(self) -> str:
        return QCoreApplication.translate("TermsView", "Filter Rare")

    @Property(str, notify=labels_changed)
    def import_label(self) -> str:
        return QCoreApplication.translate("TermsView", "Import Terms")

    @Property(str, notify=labels_changed)
    def export_label(self) -> str:
        return QCoreApplication.translate("TermsView", "Export Terms")

    @Property(bool, notify=labels_changed)
    def show_build(self) -> bool:
        return self._document_scope

    @Property(bool, notify=labels_changed)
    def show_import(self) -> bool:
        return not self._document_scope

    @Property(bool, notify=labels_changed)
    def show_export(self) -> bool:
        return not self._document_scope

    @Property(bool, notify=chrome_state_changed)
    def can_build(self) -> bool:
        return self._can_build

    @Property(bool, notify=chrome_state_changed)
    def can_translate(self) -> bool:
        return self._can_translate

    @Property(bool, notify=chrome_state_changed)
    def can_review(self) -> bool:
        return self._can_review

    @Property(bool, notify=chrome_state_changed)
    def can_filter(self) -> bool:
        return self._can_filter

    @Property(bool, notify=chrome_state_changed)
    def can_import(self) -> bool:
        return self._can_import

    @Property(bool, notify=chrome_state_changed)
    def can_export(self) -> bool:
        return self._can_export

    @Property(str, notify=chrome_state_changed)
    def build_tooltip(self) -> str:
        return self._build_tooltip

    @Property(str, notify=chrome_state_changed)
    def translate_tooltip(self) -> str:
        return self._translate_tooltip

    @Property(str, notify=chrome_state_changed)
    def review_tooltip(self) -> str:
        return self._review_tooltip

    @Property(str, notify=chrome_state_changed)
    def filter_tooltip(self) -> str:
        return self._filter_tooltip

    @Property(str, notify=chrome_state_changed)
    def import_tooltip(self) -> str:
        return self._import_tooltip

    @Property(str, notify=chrome_state_changed)
    def export_tooltip(self) -> str:
        return self._export_tooltip

    def apply_toolbar_state(
        self,
        *,
        can_build: bool,
        can_translate: bool,
        can_review: bool,
        can_filter: bool,
        can_import: bool,
        can_export: bool,
        build_tooltip: str,
        translate_tooltip: str,
        review_tooltip: str,
        filter_tooltip: str,
        import_tooltip: str,
        export_tooltip: str,
    ) -> None:
        next_state = (
            can_build,
            can_translate,
            can_review,
            can_filter,
            can_import,
            can_export,
            build_tooltip,
            translate_tooltip,
            review_tooltip,
            filter_tooltip,
            import_tooltip,
            export_tooltip,
        )
        current_state = (
            self._can_build,
            self._can_translate,
            self._can_review,
            self._can_filter,
            self._can_import,
            self._can_export,
            self._build_tooltip,
            self._translate_tooltip,
            self._review_tooltip,
            self._filter_tooltip,
            self._import_tooltip,
            self._export_tooltip,
        )
        if next_state == current_state:
            return
        (
            self._can_build,
            self._can_translate,
            self._can_review,
            self._can_filter,
            self._can_import,
            self._can_export,
            self._build_tooltip,
            self._translate_tooltip,
            self._review_tooltip,
            self._filter_tooltip,
            self._import_tooltip,
            self._export_tooltip,
        ) = next_state
        self.chrome_state_changed.emit()
        self.mark_changed()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.mark_changed()
