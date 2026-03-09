from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import (
    NavigationTargetKind,
    SurfaceStatus,
)
from context_aware_translation.application.contracts.document import (
    DocumentImagesState,
    ImageAssetState,
    RunImageReinsertionRequest,
)
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.ui.utils import create_tip_label

_STATUS_LABELS: dict[SurfaceStatus, str] = {
    SurfaceStatus.READY: "Ready",
    SurfaceStatus.RUNNING: "Running",
    SurfaceStatus.BLOCKED: "Blocked",
    SurfaceStatus.FAILED: "Failed",
    SurfaceStatus.DONE: "Done",
    SurfaceStatus.CANCELLED: "Cancelled",
}


class DocumentImagesView(QWidget):
    open_app_setup_requested = Signal()
    open_project_setup_requested = Signal()

    def __init__(
        self,
        project_id: str,
        document_id: int,
        service: DocumentService,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self._document_id = document_id
        self._service = service
        self._state: DocumentImagesState | None = None
        self._assets: list[ImageAssetState] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tip_label = create_tip_label(
            self.tr(
                "Image actions are explicit. Review one image, reinsert pending images, or rerun everything for this document."
            ),
        )
        layout.addWidget(self.tip_label)

        self.blocker_strip = QFrame()
        self.blocker_strip.setFrameShape(QFrame.Shape.StyledPanel)
        self.blocker_strip.setStyleSheet(
            "QFrame { border: 1px solid #fed7aa; background-color: #fff7ed; border-radius: 6px; }"
        )
        blocker_layout = QHBoxLayout(self.blocker_strip)
        self.blocker_label = QLabel()
        self.blocker_label.setWordWrap(True)
        self.blocker_action_button = QPushButton()
        self.blocker_action_button.clicked.connect(self._open_blocker_target)
        blocker_layout.addWidget(self.blocker_label, 1)
        blocker_layout.addWidget(self.blocker_action_button)
        self.blocker_strip.hide()
        layout.addWidget(self.blocker_strip)

        self.progress_label = QLabel()
        self.progress_label.hide()
        layout.addWidget(self.progress_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.assets_table = QTableWidget(0, 3)
        self.assets_table.setHorizontalHeaderLabels([self.tr("Image"), self.tr("Status"), self.tr("Output")])
        self.assets_table.verticalHeader().setVisible(False)
        self.assets_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.assets_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.assets_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.assets_table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.assets_table)

        self.text_panel = QTextEdit()
        self.text_panel.setReadOnly(True)
        self.text_panel.setPlaceholderText(self.tr("Translated text for the selected image appears here."))
        splitter.addWidget(self.text_panel)
        splitter.setSizes([420, 520])
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.run_selected_button = QPushButton(self.tr("Reinsert Selected"))
        self.run_selected_button.clicked.connect(self._run_selected)
        actions.addWidget(self.run_selected_button)

        self.run_pending_button = QPushButton(self.tr("Reinsert Pending"))
        self.run_pending_button.clicked.connect(self._run_pending)
        actions.addWidget(self.run_pending_button)

        self.force_all_button = QPushButton(self.tr("Force Reinsert All"))
        self.force_all_button.clicked.connect(self._force_all)
        actions.addWidget(self.force_all_button)

        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.clicked.connect(self._cancel)
        actions.addWidget(self.cancel_button)

        actions.addStretch()
        layout.addLayout(actions)

        self.message_label = QLabel()
        self.message_label.hide()
        layout.addWidget(self.message_label)

    def refresh(self) -> None:
        self._apply_state(self._service.get_images(self._project_id, self._document_id))

    def get_running_operations(self) -> list[str]:
        if self._state is not None and self._state.active_task_id is not None:
            return [self.tr("Put text back into images")]
        return []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        if include_engine_tasks and self._state is not None and self._state.active_task_id is not None:
            self._cancel()

    def _apply_state(self, state: DocumentImagesState) -> None:
        previous_asset_id = self._selected_asset_id()
        self._state = state
        self._assets = list(state.assets)
        self._render_assets(previous_asset_id)
        self._render_progress(state)
        self._update_action_buttons()
        self._update_blocker_strip()

    def _render_assets(self, previous_asset_id: str | None) -> None:
        self.assets_table.setRowCount(0)
        selected_row = 0
        for row_index, asset in enumerate(self._assets):
            self.assets_table.insertRow(row_index)
            self.assets_table.setItem(row_index, 0, QTableWidgetItem(asset.label))
            self.assets_table.setItem(row_index, 1, QTableWidgetItem(self.tr(_STATUS_LABELS[asset.status])))
            output_text = self.tr("Available") if asset.status is SurfaceStatus.DONE else self.tr("Pending")
            self.assets_table.setItem(row_index, 2, QTableWidgetItem(output_text))
            if asset.asset_id == previous_asset_id:
                selected_row = row_index
        self.assets_table.resizeColumnsToContents()
        if self._assets:
            self.assets_table.selectRow(selected_row)
        else:
            self.text_panel.clear()

    def _render_progress(self, state: DocumentImagesState) -> None:
        if state.active_task_id is None:
            self.progress_label.hide()
            self.progress_label.clear()
            return
        if state.progress is None:
            self.progress_label.setText(self.tr("Image reinsertion is running for this document."))
        elif state.progress.current is not None and state.progress.total is not None:
            label = state.progress.label or self.tr("Processing")
            self.progress_label.setText(f"{label}: {state.progress.current}/{state.progress.total}")
        else:
            self.progress_label.setText(
                state.progress.label or self.tr("Image reinsertion is running for this document.")
            )
        self.progress_label.show()

    def _selected_asset(self) -> ImageAssetState | None:
        selected_ranges = self.assets_table.selectedRanges()
        if not selected_ranges:
            return self._assets[0] if self._assets else None
        row = selected_ranges[0].topRow()
        if row < 0 or row >= len(self._assets):
            return None
        return self._assets[row]

    def _selected_asset_id(self) -> str | None:
        asset = self._selected_asset()
        return asset.asset_id if asset is not None else None

    def _on_selection_changed(self) -> None:
        asset = self._selected_asset()
        self.text_panel.setPlainText(asset.translated_text or "" if asset is not None else "")
        self._update_action_buttons()
        self._update_blocker_strip()

    def _update_action_buttons(self) -> None:
        state = self._state
        asset = self._selected_asset()
        if state is None:
            self.run_selected_button.setEnabled(False)
            self.run_pending_button.setEnabled(False)
            self.force_all_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            return

        self.run_selected_button.setEnabled(asset.can_run if asset is not None else False)
        self.run_selected_button.setToolTip(
            asset.run_blocker.message if asset is not None and asset.run_blocker is not None else ""
        )

        toolbar = state.toolbar
        self.run_pending_button.setEnabled(toolbar.can_run_pending)
        self.run_pending_button.setToolTip(
            toolbar.run_pending_blocker.message if toolbar.run_pending_blocker is not None else ""
        )
        self.force_all_button.setEnabled(toolbar.can_force_all)
        self.force_all_button.setToolTip(
            toolbar.force_all_blocker.message if toolbar.force_all_blocker is not None else ""
        )
        self.cancel_button.setEnabled(toolbar.can_cancel)
        self.cancel_button.setToolTip(toolbar.cancel_blocker.message if toolbar.cancel_blocker is not None else "")

    def _update_blocker_strip(self) -> None:
        blocker = None
        asset = self._selected_asset()
        if asset is not None and not asset.can_run:
            blocker = asset.run_blocker
        if blocker is None and self._state is not None:
            blocker = (
                self._state.toolbar.run_pending_blocker
                or self._state.toolbar.force_all_blocker
                or self._state.toolbar.cancel_blocker
            )
        if blocker is None:
            self.blocker_strip.hide()
            return
        self.blocker_label.setText(blocker.message)
        target = blocker.target.kind if blocker.target is not None else None
        if target is NavigationTargetKind.APP_SETUP:
            self.blocker_action_button.setText(self.tr("Open App Setup"))
            self.blocker_action_button.show()
        elif target is NavigationTargetKind.PROJECT_SETUP:
            self.blocker_action_button.setText(self.tr("Open Setup"))
            self.blocker_action_button.show()
        else:
            self.blocker_action_button.hide()
        self.blocker_strip.show()

    def _open_blocker_target(self) -> None:
        blocker = None
        asset = self._selected_asset()
        if asset is not None and asset.run_blocker is not None:
            blocker = asset.run_blocker
        if blocker is None and self._state is not None:
            blocker = (
                self._state.toolbar.run_pending_blocker
                or self._state.toolbar.force_all_blocker
                or self._state.toolbar.cancel_blocker
            )
        if blocker is None or blocker.target is None:
            return
        if blocker.target.kind is NavigationTargetKind.APP_SETUP:
            self.open_app_setup_requested.emit()
        elif blocker.target.kind is NavigationTargetKind.PROJECT_SETUP:
            self.open_project_setup_requested.emit()

    def _set_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.show()

    def _run_selected(self) -> None:
        asset = self._selected_asset()
        if asset is None or asset.source_id is None:
            return
        try:
            result = self._service.run_image_reinsertion(
                RunImageReinsertionRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    source_id=asset.source_id,
                    pending_only=False,
                    force_all=True,
                )
            )
        except ApplicationError as exc:
            self._set_message(exc.payload.message)
            self.refresh()
            return
        self._set_message(result.message.text if result.message is not None else self.tr("Image reinsertion queued."))
        self.refresh()

    def _run_pending(self) -> None:
        try:
            result = self._service.run_image_reinsertion(
                RunImageReinsertionRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    pending_only=True,
                    force_all=False,
                )
            )
        except ApplicationError as exc:
            self._set_message(exc.payload.message)
            self.refresh()
            return
        self._set_message(
            result.message.text if result.message is not None else self.tr("Pending image reinsertion queued.")
        )
        self.refresh()

    def _force_all(self) -> None:
        try:
            result = self._service.run_image_reinsertion(
                RunImageReinsertionRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    pending_only=False,
                    force_all=True,
                )
            )
        except ApplicationError as exc:
            self._set_message(exc.payload.message)
            self.refresh()
            return
        self._set_message(
            result.message.text if result.message is not None else self.tr("Full image reinsertion queued.")
        )
        self.refresh()

    def _cancel(self) -> None:
        if self._state is None or self._state.active_task_id is None:
            return
        try:
            result = self._service.cancel_image_reinsertion(self._project_id, self._state.active_task_id)
        except ApplicationError as exc:
            self._set_message(exc.payload.message)
            self.refresh()
            return
        self._set_message(result.message.text if result.message is not None else self.tr("Cancellation requested."))
        self.refresh()


__all__ = ["DocumentImagesView"]
