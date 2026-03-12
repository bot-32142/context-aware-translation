from __future__ import annotations

import io
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
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
from shiboken6 import isValid

from context_aware_translation.application.contracts.common import NavigationTargetKind
from context_aware_translation.application.contracts.document import (
    DocumentImagesState,
    ImageAssetState,
    RunImageReinsertionRequest,
)
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.document_images_pane import DocumentImagesPaneViewModel
from context_aware_translation.ui.widgets.image_viewer import ImageViewer
from context_aware_translation.ui.widgets.progress_widget import ProgressWidget


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
        self._preview_cache: dict[tuple[str, str], bytes] = {}
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.timeout.connect(self._refit_viewers)
        self._chrome_resize_timer = QTimer(self)
        self._chrome_resize_timer.setSingleShot(True)
        self._chrome_resize_timer.timeout.connect(self._sync_chrome_height)
        self.viewmodel = DocumentImagesPaneViewModel(self)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._init_compatibility_controls()

        self._content_widget = QWidget(self)
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

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
        self.toggle_button.setFixedWidth(120)
        self.toggle_button.hide()
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
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 500])
        content_layout.addWidget(splitter, 1)

        self.empty_label = create_tip_label(self.tr("No reembeddable images are available for this document."))
        self.empty_label.hide()
        content_layout.addWidget(self.empty_label)

        layout.addWidget(self._content_widget, 1)
        self.chrome_host = QmlChromeHost(
            "document/images/DocumentImagesPaneChrome.qml",
            context_objects={"imagesPane": self.viewmodel},
            parent=self,
        )
        layout.addWidget(self.chrome_host)
        self._connect_qml_signals()
        self._sync_chrome_state()
        self._schedule_chrome_resize()

    def _init_compatibility_controls(self) -> None:
        self.tip_label = create_tip_label(
            self.tr(
                "Image actions are explicit. Review one image, reinsert pending images, or rerun everything for this document."
            )
        )
        self.tip_label.setParent(self)
        self.tip_label.hide()

        self.blocker_strip = QFrame(self)
        self.blocker_strip.setFrameShape(QFrame.Shape.StyledPanel)
        self.blocker_strip.setStyleSheet(
            "QFrame { border: 1px solid #fed7aa; background-color: #fff7ed; border-radius: 6px; }"
        )
        blocker_layout = QHBoxLayout(self.blocker_strip)
        blocker_layout.setContentsMargins(0, 0, 0, 0)
        self.blocker_label = QLabel(self.blocker_strip)
        self.blocker_label.setWordWrap(True)
        self.blocker_action_button = QPushButton(self.blocker_strip)
        self.blocker_action_button.clicked.connect(self._open_blocker_target)
        blocker_layout.addWidget(self.blocker_label, 1)
        blocker_layout.addWidget(self.blocker_action_button)
        self.blocker_strip.hide()

        self.first_button = QPushButton("|<", self)
        self.first_button.setToolTip(self.tr("First image"))
        self.first_button.clicked.connect(self._go_first)
        self.first_button.hide()
        self.prev_button = QPushButton("<", self)
        self.prev_button.setToolTip(self.tr("Previous image"))
        self.prev_button.clicked.connect(self._go_prev)
        self.prev_button.hide()
        self.page_label = QLabel(self.tr("Image 0 of 0"), self)
        self.page_label.hide()
        self.status_label = QLabel(self)
        self.status_label.hide()
        self.go_to_label = QLabel(self.tr("Go to:"), self)
        self.go_to_label.hide()
        self.next_button = QPushButton(">", self)
        self.next_button.setToolTip(self.tr("Next image"))
        self.next_button.clicked.connect(self._go_next)
        self.next_button.hide()
        self.last_button = QPushButton(">|", self)
        self.last_button.setToolTip(self.tr("Last image"))
        self.last_button.clicked.connect(self._go_last)
        self.last_button.hide()
        self.page_spinbox = QSpinBox(self)
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.setFixedWidth(64)
        self.page_spinbox.setToolTip(self.tr("Enter image number"))
        self.page_spinbox.hide()
        self.go_button = QPushButton(self.tr("Go"), self)
        self.go_button.setToolTip(self.tr("Jump to image"))
        self.go_button.clicked.connect(self._go_to_entered)
        self.go_button.hide()

        self.run_selected_button = QPushButton(self.tr("Reembed This Image"), self)
        self.run_selected_button.clicked.connect(self._run_selected)
        self.run_selected_button.hide()
        self.run_pending_button = QPushButton(self.tr("Reembed Pending"), self)
        self.run_pending_button.clicked.connect(self._run_pending)
        self.run_pending_button.hide()
        self.force_all_button = QPushButton(self.tr("Force Reembed All"), self)
        self.force_all_button.clicked.connect(self._force_all)
        self.force_all_button.hide()

        self.message_label = QLabel(self)
        self.message_label.hide()

        self.progress_widget = ProgressWidget(self)
        self.progress_widget.setVisible(False)
        self.progress_widget.cancelled.connect(self._cancel)
        self.progress_widget.hide()

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

    def activate_view(self) -> None:
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()
        self._sync_chrome_state()
        self._schedule_refit()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.left_label.setText(self.tr("Original"))
        self.toggle_button.setToolTip(self.tr("Toggle between reembedded image and translated text"))
        self.first_button.setToolTip(self.tr("First image"))
        self.prev_button.setToolTip(self.tr("Previous image"))
        self.next_button.setToolTip(self.tr("Next image"))
        self.last_button.setToolTip(self.tr("Last image"))
        self.page_spinbox.setToolTip(self.tr("Enter image number"))
        self.go_button.setToolTip(self.tr("Jump to image"))
        self.text_panel.setPlaceholderText(self.tr("Translated text for the selected image appears here."))
        self.empty_label.setText(self.tr("No reembeddable images are available for this document."))
        self.viewmodel.retranslate()
        self._render_current_asset()
        self._update_blocker_strip()
        self._sync_chrome_state()

    def _apply_state(self, state: DocumentImagesState, *, previous_asset_id: str | None) -> None:
        self._state = state
        self._preview_cache.clear()
        self._assets = list(state.assets)
        self._render_progress(state)
        self._update_current_index(previous_asset_id)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()
        self._sync_chrome_state()

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
            self.image_viewer.set_image(self._prepare_preview_image(asset, "original", image_bytes))
        else:
            self.image_viewer.clear_image()

        self.text_panel.setPlainText(asset.translated_text or "")
        self.text_panel.moveCursor(QTextCursor.MoveOperation.Start)

        reembedded_bytes = asset.reembedded_image_bytes or self._load_reembedded_image(asset)
        if reembedded_bytes is not None:
            self.reembedded_viewer.set_image(self._prepare_preview_image(asset, "reembedded", reembedded_bytes))
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
        self._schedule_refit()

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

    def _prepare_preview_image(self, asset: ImageAssetState, kind: str, data: bytes) -> bytes:
        cache_key = (asset.asset_id, kind)
        cached = self._preview_cache.get(cache_key)
        if cached is not None:
            return cached
        trimmed = self._trim_transparent_margins_fast(data)
        preview = trimmed if trimmed is not None else data
        self._preview_cache[cache_key] = preview
        return preview

    @staticmethod
    def _trim_transparent_margins_fast(data: bytes) -> bytes | None:
        try:
            from PIL import Image
        except Exception:
            return None

        try:
            with Image.open(io.BytesIO(data)) as image:
                if "A" not in image.getbands():
                    return None
                bounds = image.getchannel("A").getbbox()
                if bounds is None or bounds == (0, 0, image.width, image.height):
                    return None
                trimmed = image.crop(bounds)
                output = io.BytesIO()
                trimmed.save(output, format="PNG")
                return output.getvalue()
        except Exception:
            return None

    def _toggle_right_panel(self) -> None:
        if self.right_stack.currentWidget() is self.text_panel:
            self.right_stack.setCurrentWidget(self.reembedded_viewer)
            self.right_label.setText(self.tr("Reembedded"))
            self.toggle_button.setText(self.tr("Show Text"))
        else:
            self.right_stack.setCurrentWidget(self.text_panel)
            self.right_label.setText(self.tr("Translated Text"))
            self.toggle_button.setText(self.tr("Show Reembedded"))
        self._sync_chrome_state()
        self._schedule_refit()

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
        self._sync_chrome_state()

    def _go_first(self) -> None:
        if not self._assets:
            return
        self._current_index = 0
        self.page_spinbox.setValue(1)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()
        self._sync_chrome_state()

    def _go_prev(self) -> None:
        if self._current_index is None or self._current_index <= 0:
            return
        self._current_index -= 1
        self.page_spinbox.setValue(self._current_index + 1)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()
        self._sync_chrome_state()

    def _go_next(self) -> None:
        if self._current_index is None or self._current_index >= len(self._assets) - 1:
            return
        self._current_index += 1
        self.page_spinbox.setValue(self._current_index + 1)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()
        self._sync_chrome_state()

    def _go_last(self) -> None:
        if not self._assets:
            return
        self._current_index = len(self._assets) - 1
        self.page_spinbox.setValue(self._current_index + 1)
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()
        self._sync_chrome_state()

    def _go_to_entered(self) -> None:
        if not self._assets:
            return
        self._current_index = max(0, min(len(self._assets) - 1, self.page_spinbox.value() - 1))
        self._render_current_asset()
        self._update_action_buttons()
        self._update_blocker_strip()
        self._sync_chrome_state()

    def _go_to_requested(self, page_text: str) -> None:
        try:
            page_number = int(page_text)
        except (TypeError, ValueError):
            page_number = self.page_spinbox.value()
        self.page_spinbox.setValue(page_number)
        self._go_to_entered()

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

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._schedule_chrome_resize()
        self._schedule_refit()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_chrome_resize()
        self._schedule_refit()

    def _schedule_refit(self) -> None:
        if self.isVisible():
            self._refit_viewers()
        self._refit_timer.start(75)

    def _schedule_chrome_resize(self) -> None:
        self._sync_chrome_height()
        self._chrome_resize_timer.start(0)

    def _sync_chrome_height(self) -> None:
        if not isValid(self.chrome_host):
            return
        root = self.chrome_host.rootObject()
        if root is None:
            return
        implicit_height = root.property("implicitHeight")
        try:
            chrome_height = max(int(float(implicit_height)), 0)
        except (TypeError, ValueError):
            return
        if chrome_height <= 0:
            return
        self.chrome_host.setMinimumHeight(chrome_height)
        self.chrome_host.setMaximumHeight(chrome_height)
        self.chrome_host.updateGeometry()

    def _refit_viewers(self) -> None:
        if not self.isVisible():
            return
        if self.image_viewer.pixmap_item is not None:
            self.image_viewer.fit_to_window()
        if self.right_stack.currentWidget() is self.reembedded_viewer and self.reembedded_viewer.pixmap_item is not None:
            self.reembedded_viewer.fit_to_window()

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.blockerActionRequested.connect(self._open_blocker_target)
        root.firstRequested.connect(self._go_first)
        root.previousRequested.connect(self._go_prev)
        root.nextRequested.connect(self._go_next)
        root.lastRequested.connect(self._go_last)
        root.goRequested.connect(self._go_to_requested)
        root.toggleRequested.connect(self._toggle_right_panel)
        root.runSelectedRequested.connect(self._run_selected)
        root.runPendingRequested.connect(self._run_pending)
        root.forceAllRequested.connect(self._force_all)
        root.cancelRequested.connect(self._cancel)

    def _sync_chrome_state(self) -> None:
        status_style = self.status_label.styleSheet()
        if "green" in status_style:
            status_color = "#15803d"
        elif "#b54708" in status_style:
            status_color = "#b54708"
        else:
            status_color = "#5f5447"
        self.viewmodel.apply_state(
            blocker_text=self.blocker_label.text().strip(),
            has_blocker=not self.blocker_strip.isHidden(),
            blocker_action_label=self.blocker_action_button.text().strip(),
            has_blocker_action=not self.blocker_action_button.isHidden(),
            page_label=self.page_label.text().strip(),
            page_input_text=str(self.page_spinbox.value()),
            status_text=self.status_label.text().strip(),
            status_color=status_color,
            toggle_label=self.toggle_button.text().strip(),
            toggle_enabled=self.toggle_button.isEnabled(),
            first_enabled=self.first_button.isEnabled(),
            previous_enabled=self.prev_button.isEnabled(),
            next_enabled=self.next_button.isEnabled(),
            last_enabled=self.last_button.isEnabled(),
            go_enabled=self.go_button.isEnabled(),
            run_selected_enabled=self.run_selected_button.isEnabled(),
            run_pending_enabled=self.run_pending_button.isEnabled(),
            force_all_enabled=self.force_all_button.isEnabled(),
            message_text=self.message_label.text().strip(),
            progress_visible=not self.progress_widget.isHidden(),
            progress_text=self.progress_widget.message_label.text().strip(),
            progress_can_cancel=not self.progress_widget.cancel_button.isHidden(),
            empty_visible=not self.empty_label.isHidden(),
        )
        self._schedule_chrome_resize()


__all__ = ["DocumentImagesView"]
