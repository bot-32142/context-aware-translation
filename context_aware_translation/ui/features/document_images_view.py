from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt, Signal
from PySide6.QtGui import QImage, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import NavigationTargetKind
from context_aware_translation.application.contracts.document import (
    DocumentImagesState,
    ImageAssetState,
    RunImageReinsertionRequest,
)
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.ui.utils import create_tip_label
from context_aware_translation.ui.widgets import ImageViewer, ProgressWidget


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
        self._current_index: int | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tip_label = create_tip_label(
            self.tr(
                "Image actions are explicit. Review one image, reinsert pending images, or rerun everything for this document."
            )
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

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_label = QLabel(self.tr("Original"))
        self.left_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_label.setStyleSheet("font-weight: 600;")
        left_layout.addWidget(self.left_label)
        self.image_viewer = ImageViewer(self)
        left_layout.addWidget(self.image_viewer, 1)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        header_layout = QHBoxLayout()
        self.right_label = QLabel(self.tr("Reembedded"))
        self.right_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_label.setStyleSheet("font-weight: 600;")
        header_layout.addWidget(self.right_label, 1)
        self.toggle_button = QPushButton(self.tr("Show Text"))
        self.toggle_button.setToolTip(self.tr("Toggle between reembedded image and translated text"))
        self.toggle_button.clicked.connect(self._toggle_right_panel)
        self.toggle_button.setFixedWidth(100)
        header_layout.addWidget(self.toggle_button)
        right_layout.addLayout(header_layout)

        self.right_stack = QStackedWidget(self)
        self.reembedded_viewer = ImageViewer(self)
        self.right_stack.addWidget(self.reembedded_viewer)
        self.text_panel = QTextEdit()
        self.text_panel.setReadOnly(True)
        self.text_panel.setPlaceholderText(self.tr("Translated text for the selected image appears here."))
        self.right_stack.addWidget(self.text_panel)
        self.right_stack.setCurrentWidget(self.reembedded_viewer)
        right_layout.addWidget(self.right_stack, 1)
        splitter.addWidget(right_panel)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)

        nav_layout = QHBoxLayout()
        self.first_button = QPushButton("|<")
        self.first_button.setToolTip(self.tr("First image"))
        self.first_button.clicked.connect(self._go_first)
        nav_layout.addWidget(self.first_button)
        self.prev_button = QPushButton("<")
        self.prev_button.setToolTip(self.tr("Previous image"))
        self.prev_button.clicked.connect(self._go_prev)
        nav_layout.addWidget(self.prev_button)
        self.page_label = QLabel(self.tr("Image 0 of 0"))
        nav_layout.addWidget(self.page_label)
        self.status_label = QLabel()
        nav_layout.addWidget(self.status_label)
        self.next_button = QPushButton(">")
        self.next_button.setToolTip(self.tr("Next image"))
        self.next_button.clicked.connect(self._go_next)
        nav_layout.addWidget(self.next_button)
        self.last_button = QPushButton(">|")
        self.last_button.setToolTip(self.tr("Last image"))
        self.last_button.clicked.connect(self._go_last)
        nav_layout.addWidget(self.last_button)
        nav_layout.addSpacing(8)
        self.go_to_label = QLabel(self.tr("Go to:"))
        nav_layout.addWidget(self.go_to_label)
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.setFixedWidth(64)
        self.page_spinbox.setToolTip(self.tr("Enter image number"))
        nav_layout.addWidget(self.page_spinbox)
        self.go_button = QPushButton(self.tr("Go"))
        self.go_button.setToolTip(self.tr("Jump to image"))
        self.go_button.clicked.connect(self._go_to_entered)
        nav_layout.addWidget(self.go_button)
        nav_layout.addStretch(1)
        layout.addLayout(nav_layout)

        actions = QHBoxLayout()
        self.run_selected_button = QPushButton(self.tr("Reembed This Image"))
        self.run_selected_button.clicked.connect(self._run_selected)
        actions.addWidget(self.run_selected_button)
        self.run_pending_button = QPushButton(self.tr("Reembed Pending"))
        self.run_pending_button.clicked.connect(self._run_pending)
        actions.addWidget(self.run_pending_button)
        self.force_all_button = QPushButton(self.tr("Force Reembed All"))
        self.force_all_button.clicked.connect(self._force_all)
        actions.addWidget(self.force_all_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.message_label = QLabel()
        self.message_label.hide()
        layout.addWidget(self.message_label)

        self.progress_widget = ProgressWidget(self)
        self.progress_widget.setVisible(False)
        self.progress_widget.cancelled.connect(self._cancel)
        layout.addWidget(self.progress_widget)

        self.empty_label = create_tip_label(self.tr("No reembeddable images are available for this document."))
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

    def refresh(self) -> None:
        previous_asset_id = self._selected_asset_id()
        self._apply_state(
            self._service.get_images(self._project_id, self._document_id), previous_asset_id=previous_asset_id
        )

    def get_running_operations(self) -> list[str]:
        if self._state is not None and self._state.active_task_id is not None:
            return [self.tr("Put text back into images")]
        return []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        if include_engine_tasks and self._state is not None and self._state.active_task_id is not None:
            self._cancel()

    def _apply_state(self, state: DocumentImagesState, *, previous_asset_id: str | None) -> None:
        self._state = state
        self._assets = list(state.assets)
        self._render_progress(state)
        self._update_current_index(previous_asset_id)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()

    def _update_current_index(self, previous_asset_id: str | None) -> None:
        if not self._assets:
            self._current_index = None
            self.page_spinbox.setMaximum(1)
            return
        selected_index = 0
        if previous_asset_id is not None:
            for index, asset in enumerate(self._assets):
                if asset.asset_id == previous_asset_id:
                    selected_index = index
                    break
        self._current_index = selected_index
        self.page_spinbox.setMaximum(len(self._assets))
        self.page_spinbox.setValue(selected_index + 1)

    def _selected_asset(self) -> ImageAssetState | None:
        if self._current_index is None:
            return None
        if self._current_index < 0 or self._current_index >= len(self._assets):
            return None
        return self._assets[self._current_index]

    def _selected_asset_id(self) -> str | None:
        asset = self._selected_asset()
        return asset.asset_id if asset is not None else None

    def _render_current_asset(self) -> None:
        asset = self._selected_asset()
        if asset is None:
            self.empty_label.show()
            self.page_label.setText(self.tr("Image 0 of 0"))
            self.status_label.clear()
            self.status_label.setStyleSheet("")
            self.image_viewer.clear_image()
            self.reembedded_viewer.clear_image()
            self.text_panel.clear()
            self.right_label.setText(self.tr("Reembedded"))
            self.toggle_button.setText(self.tr("Show Text"))
            self.toggle_button.setEnabled(False)
            self.go_to_label.setEnabled(False)
            self.page_spinbox.setEnabled(False)
            self.go_button.setEnabled(False)
            self.first_button.setEnabled(False)
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.last_button.setEnabled(False)
            return

        self.empty_label.hide()
        assert self._current_index is not None
        self.page_label.setText(
            self.tr("Image %1 of %2").replace("%1", str(self._current_index + 1)).replace("%2", str(len(self._assets)))
        )
        self.go_to_label.setEnabled(True)
        self.page_spinbox.setEnabled(True)
        self.go_button.setEnabled(True)
        self.first_button.setEnabled(self._current_index > 0)
        self.prev_button.setEnabled(self._current_index > 0)
        self.next_button.setEnabled(self._current_index < len(self._assets) - 1)
        self.last_button.setEnabled(self._current_index < len(self._assets) - 1)

        image_bytes = asset.original_image_bytes
        if image_bytes is None and asset.source_id is not None:
            try:
                image_bytes = self._service.get_ocr_page_image(self._project_id, self._document_id, asset.source_id)
            except ApplicationError:
                image_bytes = None
        if image_bytes:
            self.image_viewer.set_image(self._prepare_preview_image(image_bytes))
        else:
            self.image_viewer.clear_image()

        self.text_panel.setPlainText(asset.translated_text or "")
        self.text_panel.moveCursor(QTextCursor.MoveOperation.Start)

        reembedded_bytes = asset.reembedded_image_bytes or self._load_reembedded_image(asset)
        if reembedded_bytes is not None:
            self.reembedded_viewer.set_image(self._prepare_preview_image(reembedded_bytes))
            self.right_stack.setCurrentWidget(self.reembedded_viewer)
            self.right_label.setText(self.tr("Reembedded"))
            self.toggle_button.setText(self.tr("Show Text"))
            self.toggle_button.setEnabled(True)
            self.status_label.setText(self.tr("Reembedded"))
            self.status_label.setStyleSheet("color: green; font-weight: 600;")
        else:
            self.reembedded_viewer.clear_image()
            self.right_stack.setCurrentWidget(self.text_panel)
            self.right_label.setText(self.tr("Translated Text"))
            self.toggle_button.setText(self.tr("Show Image"))
            self.toggle_button.setEnabled(False)
            self.status_label.setText(self.tr("Pending"))
            self.status_label.setStyleSheet("color: #b54708; font-weight: 600;")

    def _load_reembedded_image(self, asset: ImageAssetState) -> bytes | None:
        if not asset.output_path:
            return None
        output_path = Path(asset.output_path)
        if not output_path.exists() or not output_path.is_file():
            return None
        try:
            return output_path.read_bytes()
        except OSError:
            return None

    def _prepare_preview_image(self, data: bytes) -> bytes:
        image = QImage()
        if not image.loadFromData(data):
            return data
        trimmed = self._trim_transparent_margins(image)
        if trimmed is None:
            return data
        payload = QByteArray()
        buffer = QBuffer(payload)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        trimmed.save(buffer, "PNG")
        return bytes(payload)

    @staticmethod
    def _trim_transparent_margins(image: QImage) -> QImage | None:
        if not image.hasAlphaChannel():
            return None
        bounds = QRect()
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() == 0:
                    continue
                bounds = QRect(x, y, 1, 1) if bounds.isNull() else bounds.united(QRect(x, y, 1, 1))
        if bounds.isNull():
            return None
        if bounds.width() == image.width() and bounds.height() == image.height():
            return None
        return image.copy(bounds)

    def _toggle_right_panel(self) -> None:
        if self.right_stack.currentWidget() is self.text_panel:
            self.right_stack.setCurrentWidget(self.reembedded_viewer)
            self.right_label.setText(self.tr("Reembedded"))
            self.toggle_button.setText(self.tr("Show Text"))
        else:
            self.right_stack.setCurrentWidget(self.text_panel)
            self.right_label.setText(self.tr("Translated Text"))
            self.toggle_button.setText(self.tr("Show Reembedded"))

    def _render_progress(self, state: DocumentImagesState) -> None:
        if state.active_task_id is None:
            self.progress_widget.reset()
            self.progress_widget.setVisible(False)
            return
        self.progress_widget.reset()
        self.progress_widget.setVisible(True)
        self.progress_widget.set_cancellable(state.toolbar.can_cancel)
        if state.progress is None or state.progress.current is None or state.progress.total is None:
            self.progress_widget.progress_bar.setMinimum(0)
            self.progress_widget.progress_bar.setMaximum(0)
            self.progress_widget.message_label.setText(
                state.progress.label if state.progress is not None and state.progress.label else self.tr("Reembedding")
            )
            self.progress_widget.eta_label.clear()
        else:
            self.progress_widget.set_progress(
                state.progress.current,
                state.progress.total,
                state.progress.label or self.tr("Reembedding"),
            )

    def _update_action_buttons(self) -> None:
        state = self._state
        asset = self._selected_asset()
        if state is None:
            self.run_selected_button.setEnabled(False)
            self.run_pending_button.setEnabled(False)
            self.force_all_button.setEnabled(False)
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

    def _go_first(self) -> None:
        if not self._assets:
            return
        self._current_index = 0
        self.page_spinbox.setValue(1)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()

    def _go_prev(self) -> None:
        if self._current_index is None or self._current_index <= 0:
            return
        self._current_index -= 1
        self.page_spinbox.setValue(self._current_index + 1)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()

    def _go_next(self) -> None:
        if self._current_index is None or self._current_index >= len(self._assets) - 1:
            return
        self._current_index += 1
        self.page_spinbox.setValue(self._current_index + 1)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()

    def _go_last(self) -> None:
        if not self._assets:
            return
        self._current_index = len(self._assets) - 1
        self.page_spinbox.setValue(self._current_index + 1)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()

    def _go_to_entered(self) -> None:
        if not self._assets:
            return
        self._current_index = max(0, min(len(self._assets) - 1, self.page_spinbox.value() - 1))
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()

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
