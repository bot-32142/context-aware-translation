from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from context_aware_translation.ui.shell_hosts.hybrid import HybridDialogHost
from context_aware_translation.ui.viewmodels.project_settings_dialog import ProjectSettingsDialogViewModel


class ProjectSettingsDialogHost(HybridDialogHost):
    """Dialog host that wraps the project-settings body with QML chrome."""

    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self.viewmodel = ProjectSettingsDialogViewModel(parent)
        super().__init__(
            "dialogs/project_settings/ProjectSettingsDialogChrome.qml",
            context_objects={"projectSettingsDialog": self.viewmodel},
            parent=parent,
        )
        self.setModal(False)
        self.setWindowTitle(self.viewmodel.title)
        self.resize(1120, 760)
        self.finished.connect(lambda _result: self.viewmodel.dismiss())
        self._connect_qml_signals()

    def set_project_settings_widget(self, widget: QWidget) -> QWidget:
        return self.set_body_widget(widget)

    def set_project_setup_widget(self, widget: QWidget) -> QWidget:
        return self.set_project_settings_widget(widget)

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
