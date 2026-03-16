from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from context_aware_translation.ui.shell_hosts.hybrid import HybridDialogHost
from context_aware_translation.ui.viewmodels.app_settings_dialog import AppSettingsDialogViewModel


class AppSettingsDialogHost(HybridDialogHost):
    """Dialog host that wraps the app-settings body with QML chrome."""

    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self.viewmodel = AppSettingsDialogViewModel(parent)
        super().__init__(
            "dialogs/app_settings/AppSettingsDialogChrome.qml",
            context_objects={"appSettingsDialog": self.viewmodel},
            parent=parent,
        )
        self.setModal(False)
        self.setWindowTitle(self.viewmodel.title)
        self.resize(1120, 760)
        self.finished.connect(lambda _result: self.viewmodel.dismiss())
        self._connect_qml_signals()

    def set_app_settings_widget(self, widget: QWidget) -> QWidget:
        return self.set_body_widget(widget)

    def set_app_setup_widget(self, widget: QWidget) -> QWidget:
        return self.set_app_settings_widget(widget)

    def present(self) -> None:
        self.viewmodel.present()
        self.show()
        self.raise_()
        self.activateWindow()

    def dismiss(self) -> None:
        self.close()

    def retranslate(self) -> None:
        self.viewmodel.retranslate()
        self.setWindowTitle(self.viewmodel.title)

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.closeRequested.connect(self._on_close_requested)

    def _on_close_requested(self) -> None:
        self.close_requested.emit()
        self.close()
