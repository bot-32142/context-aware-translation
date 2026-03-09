"""Combined profile view with tabs."""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.ui.utils import create_tip_label
from context_aware_translation.ui.views.config_profile_view import ConfigProfileView
from context_aware_translation.ui.views.endpoint_profile_view import EndpointProfileView


class ProfileView(QWidget):
    """Combined view for profile management with tabs."""

    def __init__(self, book_manager: BookManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        self.tab_widget = QTabWidget()

        # Endpoint Profiles tab
        self.endpoint_profile_view = EndpointProfileView(self.book_manager)
        self.tab_widget.addTab(self.endpoint_profile_view, self.tr("Endpoint Profiles"))

        # Config Profiles tab
        self.config_profile_view = ConfigProfileView(self.book_manager)
        self.tab_widget.addTab(self.config_profile_view, self.tr("Config Profiles"))

        layout.addWidget(self.tab_widget)

    def refresh(self) -> None:
        """Refresh all profile views."""
        self.endpoint_profile_view.refresh()
        self.config_profile_view.refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.tab_widget.setTabText(0, self.tr("Endpoint Profiles"))
        self.tab_widget.setTabText(1, self.tr("Config Profiles"))

    def _tip_text(self) -> str:
        return self.tr(
            "App Setup manages shared connections and default routing. Endpoint Profiles store API/model settings; Config Profiles decide which connection each step uses."
        )
