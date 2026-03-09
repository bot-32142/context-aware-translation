from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import (
    BindingSource,
    CapabilityAvailability,
    CapabilityCode,
    NavigationTargetKind,
    PresetCode,
)
from context_aware_translation.application.contracts.project_setup import (
    ProjectCapabilityCard,
    ProjectCapabilityOverride,
    ProjectSetupState,
    SaveProjectSetupRequest,
)
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import ApplicationEventSubscriber, SetupInvalidatedEvent
from context_aware_translation.application.services.project_setup import ProjectSetupService
from context_aware_translation.ui.adapters import QtApplicationEventBridge
from context_aware_translation.ui.constants import LANGUAGES
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.utils import create_tip_label


class _CapabilityCardWidget(QFrame):
    open_app_setup_requested = Signal()

    def __init__(self, capability: CapabilityCode, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.capability = capability
        self._card: ProjectCapabilityCard | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("QFrame { border: 1px solid #d8dee9; border-radius: 6px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.title_label)

        meta_layout = QFormLayout()
        meta_layout.setContentsMargins(0, 0, 0, 0)
        self.status_value = QLabel()
        self.source_value = QLabel()
        self.connection_value = QLabel()
        meta_layout.addRow(self.tr("Status"), self.status_value)
        meta_layout.addRow(self.tr("Source"), self.source_value)
        meta_layout.addRow(self.tr("Connection"), self.connection_value)
        layout.addLayout(meta_layout)

        self.blocker_label = create_tip_label("")
        self.blocker_label.setStyleSheet("QLabel { color: #b42318; font-size: 12px; }")
        self.blocker_label.hide()
        layout.addWidget(self.blocker_label)

        self.override_checkbox = QCheckBox(self.tr("Override for this project"))
        self.override_checkbox.toggled.connect(self._sync_override_state)
        layout.addWidget(self.override_checkbox)

        self.override_row = QHBoxLayout()
        self.connection_combo = QComboBox()
        self.connection_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.open_app_setup_button = QPushButton(self.tr("Open App Setup"))
        self.open_app_setup_button.clicked.connect(self.open_app_setup_requested.emit)
        self.override_row.addWidget(self.connection_combo, 1)
        self.override_row.addWidget(self.open_app_setup_button)
        layout.addLayout(self.override_row)

    def set_card(self, card: ProjectCapabilityCard) -> None:
        self._card = card
        self.title_label.setText(self._capability_label(card.capability))
        self.status_value.setText(self._availability_label(card.availability))
        self.source_value.setText(self._source_label(card.source))
        self.connection_value.setText(card.connection_label or self.tr("Use app defaults"))

        self.connection_combo.blockSignals(True)
        self.connection_combo.clear()
        for option in card.options:
            self.connection_combo.addItem(option.connection_label, option.connection_id)
        if card.connection_id is not None:
            index = self.connection_combo.findData(card.connection_id)
            if index >= 0:
                self.connection_combo.setCurrentIndex(index)
        self.connection_combo.blockSignals(False)

        is_override = card.source is BindingSource.PROJECT_OVERRIDE and card.connection_id is not None
        self.override_checkbox.blockSignals(True)
        self.override_checkbox.setChecked(is_override)
        self.override_checkbox.blockSignals(False)

        blocker_text = card.blocker.message if card.blocker is not None else ""
        self.blocker_label.setText(blocker_text)
        self.blocker_label.setVisible(bool(blocker_text))

        needs_app_setup = (
            card.blocker is not None
            and card.blocker.target is not None
            and card.blocker.target.kind is NavigationTargetKind.APP_SETUP
        ) or (card.availability is CapabilityAvailability.MISSING and not card.options)
        self.open_app_setup_button.setVisible(needs_app_setup)
        self._sync_override_state(self.override_checkbox.isChecked())

    def build_override(self) -> ProjectCapabilityOverride | None:
        if not self.override_checkbox.isChecked():
            return None
        connection_id = self.connection_combo.currentData()
        if isinstance(connection_id, str) and connection_id:
            return ProjectCapabilityOverride(capability=self.capability, connection_id=connection_id)
        return None

    def has_invalid_override(self) -> bool:
        return self.override_checkbox.isChecked() and self.connection_combo.currentData() in {None, ""}

    def retranslateUi(self) -> None:
        self.status_value.setText(self._availability_label(self._card.availability) if self._card is not None else "")
        self.source_value.setText(self._source_label(self._card.source) if self._card is not None else "")
        self.connection_value.setText(
            self._card.connection_label
            if self._card is not None and self._card.connection_label
            else self.tr("Use app defaults")
        )
        self.override_checkbox.setText(self.tr("Override for this project"))
        self.open_app_setup_button.setText(self.tr("Open App Setup"))
        if self._card is not None:
            self.title_label.setText(self._capability_label(self._card.capability))
            self.blocker_label.setText(self._card.blocker.message if self._card.blocker is not None else "")

    def _sync_override_state(self, checked: bool) -> None:
        has_options = self.connection_combo.count() > 0
        self.connection_combo.setVisible(checked and has_options)
        self.connection_combo.setEnabled(checked and has_options)
        self.open_app_setup_button.setEnabled(self.open_app_setup_button.isVisible())

    def _capability_label(self, capability: CapabilityCode) -> str:
        labels = {
            CapabilityCode.TRANSLATION: self.tr("Translation"),
            CapabilityCode.IMAGE_TEXT_READING: self.tr("Image text reading"),
            CapabilityCode.IMAGE_EDITING: self.tr("Image editing"),
            CapabilityCode.REASONING_AND_REVIEW: self.tr("Reasoning and review"),
        }
        return labels[capability]

    def _availability_label(self, availability: CapabilityAvailability) -> str:
        labels = {
            CapabilityAvailability.READY: self.tr("Ready"),
            CapabilityAvailability.MISSING: self.tr("Missing"),
            CapabilityAvailability.PARTIAL: self.tr("Partial"),
            CapabilityAvailability.UNSUPPORTED_FOR_WORKFLOW: self.tr("Unsupported for this workflow"),
        }
        return labels[availability]

    def _source_label(self, source: BindingSource) -> str:
        labels = {
            BindingSource.APP_DEFAULT: self.tr("App default"),
            BindingSource.PROJECT_OVERRIDE: self.tr("Project override"),
            BindingSource.MISSING: self.tr("Missing"),
        }
        return labels[source]


class ProjectSetupView(QWidget):
    """Project-scoped setup surface backed by application contracts."""

    open_app_setup_requested = Signal()
    save_completed = Signal(str)

    def __init__(
        self,
        project_id: str,
        service: ProjectSetupService,
        events: ApplicationEventSubscriber,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self._service = service
        self._state: ProjectSetupState | None = None
        self._card_widgets: dict[CapabilityCode, _CapabilityCardWidget] = {}
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        self.message_label = QLabel()
        self.message_label.hide()
        layout.addWidget(self.message_label)

        self.summary_label = create_tip_label("")
        layout.addWidget(self.summary_label)

        form_group = QGroupBox(self.tr("Project defaults"))
        form_layout = QFormLayout(form_group)

        self.target_language_combo = QComboBox()
        self.target_language_combo.setEditable(True)
        seen_languages: set[str] = set()
        for display_name, _code in LANGUAGES:
            if display_name in seen_languages:
                continue
            seen_languages.add(display_name)
            self.target_language_combo.addItem(display_name)
        form_layout.addRow(self.tr("Target language"), self.target_language_combo)

        self.preset_combo = QComboBox()
        self.preset_combo.addItem(self.tr("Fast"), PresetCode.FAST.value)
        self.preset_combo.addItem(self.tr("Balanced"), PresetCode.BALANCED.value)
        self.preset_combo.addItem(self.tr("Best quality"), PresetCode.BEST.value)
        form_layout.addRow(self.tr("Preset"), self.preset_combo)
        layout.addWidget(form_group)

        self.cards_group = QGroupBox(self.tr("Capability cards"))
        cards_layout = QVBoxLayout(self.cards_group)
        cards_layout.setContentsMargins(12, 12, 12, 12)

        cards_container = QWidget()
        self.cards_container_layout = QVBoxLayout(cards_container)
        self.cards_container_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_container_layout.setSpacing(12)
        self.cards_container_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(cards_container)
        cards_layout.addWidget(scroll)
        layout.addWidget(self.cards_group, 1)

        self.advanced_group = QGroupBox(self.tr("Advanced override notes"))
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        advanced_layout = QVBoxLayout(self.advanced_group)
        self.advanced_note = create_tip_label(self._advanced_note_text())
        advanced_layout.addWidget(self.advanced_note)
        layout.addWidget(self.advanced_group)

        actions_layout = QHBoxLayout()
        self.open_app_setup_button = QPushButton(self.tr("Open App Setup"))
        self.open_app_setup_button.clicked.connect(self.open_app_setup_requested.emit)
        actions_layout.addWidget(self.open_app_setup_button)
        actions_layout.addStretch()
        self.save_button = QPushButton(self.tr("Save"))
        self.save_button.clicked.connect(self._save)
        actions_layout.addWidget(self.save_button)
        layout.addLayout(actions_layout)

    def refresh(self) -> None:
        self._apply_state(self._service.get_state(self.project_id))

    def cleanup(self) -> None:
        self._event_bridge.close()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.cards_group.setTitle(self.tr("Capability cards"))
        self.advanced_group.setTitle(self.tr("Advanced override notes"))
        self.advanced_note.setText(self._advanced_note_text())
        self.open_app_setup_button.setText(self.tr("Open App Setup"))
        self.save_button.setText(self.tr("Save"))
        self.summary_label.setText(self._summary_text(self._state.bindings if self._state is not None else []))
        self.title_label.setText(self._title_text())
        self.message_label.setText(self.message_label.text())
        for index, (label, preset) in enumerate(
            [
                (self.tr("Fast"), PresetCode.FAST),
                (self.tr("Balanced"), PresetCode.BALANCED),
                (self.tr("Best quality"), PresetCode.BEST),
            ]
        ):
            self.preset_combo.setItemText(index, label)
            self.preset_combo.setItemData(index, preset.value)
        for card_widget in self._card_widgets.values():
            card_widget.retranslateUi()

    def _apply_state(self, state: ProjectSetupState) -> None:
        self._state = state
        self.title_label.setText(self._title_text())
        self.summary_label.setText(self._summary_text(state.bindings))

        self.target_language_combo.blockSignals(True)
        target_language = state.target_language or ""
        index = self.target_language_combo.findText(target_language)
        if index >= 0:
            self.target_language_combo.setCurrentIndex(index)
        else:
            self.target_language_combo.setEditText(target_language)
        self.target_language_combo.blockSignals(False)

        preset_index = self.preset_combo.findData(state.preset.value)
        self.preset_combo.setCurrentIndex(max(preset_index, 0))

        for capability in CapabilityCode:
            card = next((item for item in state.capability_cards if item.capability is capability), None)
            if card is None:
                continue
            widget = self._card_widgets.get(capability)
            if widget is None:
                widget = _CapabilityCardWidget(capability, parent=self.cards_group)
                widget.open_app_setup_requested.connect(self.open_app_setup_requested.emit)
                self._card_widgets[capability] = widget
                self.cards_container_layout.insertWidget(self.cards_container_layout.count() - 1, widget)
            widget.set_card(card)
        self._show_message("", is_error=False)

    def _save(self) -> None:
        target_language = self.target_language_combo.currentText().strip()
        if not target_language:
            self._show_message(self.tr("Target language is required."), is_error=True)
            return

        overrides: list[ProjectCapabilityOverride] = []
        invalid_labels: list[str] = []
        for widget in self._card_widgets.values():
            override = widget.build_override()
            if widget.has_invalid_override():
                invalid_labels.append(widget.title_label.text())
            elif override is not None:
                overrides.append(override)

        if invalid_labels:
            self._show_message(
                qarg(self.tr("Select a connection for %1 before saving."), ", ".join(invalid_labels)),
                is_error=True,
            )
            return

        raw_preset = self.preset_combo.currentData()
        try:
            preset = PresetCode(str(raw_preset))
        except ValueError:
            preset = PresetCode.BALANCED

        try:
            state = self._service.save(
                SaveProjectSetupRequest(
                    project_id=self.project_id,
                    target_language=target_language,
                    preset=preset,
                    overrides=overrides,
                )
            )
        except BlockedOperationError as exc:
            self._show_message(exc.payload.message, is_error=True)
            return
        except ApplicationError as exc:
            self._show_message(exc.payload.message, is_error=True)
            return

        self._apply_state(state)
        self._show_message(self.tr("Project setup saved."), is_error=False)
        self.save_completed.emit(self.project_id)

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self.project_id}:
            return
        self.refresh()

    def _show_message(self, text: str, *, is_error: bool) -> None:
        if not text:
            self.message_label.hide()
            self.message_label.clear()
            return
        color = "#b42318" if is_error else "#027a48"
        self.message_label.setStyleSheet(f"QLabel {{ color: {color}; font-weight: 600; }}")
        self.message_label.setText(text)
        self.message_label.show()

    def _title_text(self) -> str:
        if self._state is None:
            return self.tr("Project Setup")
        return qarg(self.tr("Setup for %1"), self._state.project.name)

    def _summary_text(self, bindings: Iterable[object]) -> str:
        bindings_list = list(bindings)
        missing = sum(
            1 for binding in bindings_list if getattr(binding, "availability", None) is CapabilityAvailability.MISSING
        )
        overrides = sum(
            1 for binding in bindings_list if getattr(binding, "source", None) is BindingSource.PROJECT_OVERRIDE
        )
        if missing:
            return qarg(
                self.tr("%1 capabilities need app-level setup. Open App Setup to add shared connections."),
                missing,
            )
        if overrides:
            return qarg(self.tr("Using app defaults with %1 project overrides."), overrides)
        return self.tr("Using app defaults for all available capabilities.")

    def _tip_text(self) -> str:
        return self.tr(
            "Project Setup controls target language, preset, and whether each capability inherits the shared app defaults or uses a project-specific override."
        )

    def _advanced_note_text(self) -> str:
        return self.tr(
            "Overrides are opt-in. Leave a capability on app defaults unless this project needs a different shared connection. Raw endpoint editing stays in App Setup."
        )
