from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionSummary,
    ConnectionTestRequest,
    ConnectionTestResult,
    SaveWorkflowProfileRequest,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.services.app_setup import AppSetupService
from context_aware_translation.ui.chrome_sizing import sync_qml_host_height
from context_aware_translation.ui.features.app_setup_view import (
    _NEW_PROFILE_ROUTE_SPECS,
    _PROVIDER_LABELS,
    ConnectionEditorDialog,
    SetupWizardDialog,
)
from context_aware_translation.ui.features.workflow_profile_editor import (
    ConnectionChoice,
    WorkflowProfileEditorDialog,
)
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.viewmodels.app_settings_pane import AppSettingsPaneViewModel
from context_aware_translation.ui.widgets.table_support import (
    apply_header_resize_modes,
    configure_readonly_row_table,
    fit_table_min_width,
)


class AppSettingsPane(QWidget):
    """Hybrid app-settings body with QML tabs/actions and hosted tables."""

    def __init__(self, service: AppSetupService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._state: AppSetupState | None = None
        self._current_tab = "connections"
        self.viewmodel = AppSettingsPaneViewModel(self)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.chrome_host = QmlChromeHost(
            "dialogs/app_settings/AppSettingsPane.qml",
            context_objects={"appSettingsPane": self.viewmodel},
            parent=self,
        )
        layout.addWidget(self.chrome_host)

        self.content_stack = QStackedWidget(self)
        layout.addWidget(self.content_stack, 1)

        self.connections_page = QWidget(self)
        connections_layout = QVBoxLayout(self.connections_page)
        connections_layout.setContentsMargins(0, 12, 0, 0)
        self.connections_table = QTableWidget(0, 5)
        self.connections_table.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Provider"), self.tr("Status"), self.tr("Model"), self.tr("Base URL")]
        )
        configure_readonly_row_table(self.connections_table, vertical_policy=QSizePolicy.Policy.Expanding)
        apply_header_resize_modes(
            self.connections_table,
            (
                (0, QHeaderView.ResizeMode.ResizeToContents),
                (1, QHeaderView.ResizeMode.ResizeToContents),
                (2, QHeaderView.ResizeMode.ResizeToContents),
                (3, QHeaderView.ResizeMode.Interactive),
                (4, QHeaderView.ResizeMode.Interactive),
            ),
            column_widths=((3, 320), (4, 500)),
        )
        self.connections_table.itemSelectionChanged.connect(self._sync_viewmodel)
        self.connections_table.cellDoubleClicked.connect(self._on_connection_double_clicked)
        connections_layout.addWidget(self.connections_table)
        self.content_stack.addWidget(self.connections_page)

        self.profiles_page = QWidget(self)
        profiles_layout = QVBoxLayout(self.profiles_page)
        profiles_layout.setContentsMargins(0, 12, 0, 0)
        self.profiles_table = QTableWidget(0, 3)
        self.profiles_table.setHorizontalHeaderLabels([self.tr("Name"), self.tr("Target language"), self.tr("Default")])
        configure_readonly_row_table(self.profiles_table, vertical_policy=QSizePolicy.Policy.Expanding)
        apply_header_resize_modes(
            self.profiles_table,
            (
                (0, QHeaderView.ResizeMode.Interactive),
                (1, QHeaderView.ResizeMode.Interactive),
                (2, QHeaderView.ResizeMode.ResizeToContents),
            ),
            column_widths=((0, 360), (1, 220)),
        )
        self.profiles_table.itemSelectionChanged.connect(self._sync_viewmodel)
        self.profiles_table.cellDoubleClicked.connect(self._on_profile_double_clicked)
        profiles_layout.addWidget(self.profiles_table)
        self.content_stack.addWidget(self.profiles_page)

        self._connect_qml_signals()
        self._schedule_chrome_resize()

    def refresh(self) -> None:
        self._state = self._service.get_state()
        self._populate_connections(self._state.connections)
        self._populate_profiles(self._state)
        self._sync_tab_widget()
        self._sync_viewmodel()
        self._schedule_chrome_resize()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.connections_table.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Provider"), self.tr("Status"), self.tr("Model"), self.tr("Base URL")]
        )
        self.profiles_table.setHorizontalHeaderLabels([self.tr("Name"), self.tr("Target language"), self.tr("Default")])
        if self._state is not None:
            self._populate_connections(self._state.connections)
            self._populate_profiles(self._state)
        self.viewmodel.retranslate()
        self._sync_viewmodel()
        self._schedule_chrome_resize()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._schedule_chrome_resize()

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.tabRequested.connect(self._on_tab_requested)
        root.actionRequested.connect(self._on_action_requested)

    def _on_tab_requested(self, tab_name: str) -> None:
        if tab_name not in {"connections", "profiles"} or tab_name == self._current_tab:
            return
        self._current_tab = tab_name
        self._sync_tab_widget()
        self._sync_viewmodel()

    def _sync_tab_widget(self) -> None:
        self.content_stack.setCurrentWidget(
            self.connections_page if self._current_tab == "connections" else self.profiles_page
        )
        self._schedule_chrome_resize()

    def _sync_viewmodel(self) -> None:
        self.viewmodel.apply_state(current_tab=self._current_tab, action_buttons=self._action_buttons())
        self._schedule_chrome_resize()

    def _schedule_chrome_resize(self) -> None:
        self._sync_chrome_height()
        QTimer.singleShot(0, self._sync_chrome_height)

    def _sync_chrome_height(self) -> None:
        sync_qml_host_height(self.chrome_host)

    def _action_buttons(self) -> list[dict[str, object]]:
        if self._current_tab == "profiles":
            has_connections = bool(self._state and self._state.connections)
            selected_profile = self._selected_profile()
            selected = selected_profile is not None
            return [
                {"action": "add_profile", "label": self.tr("Add Profile"), "enabled": has_connections, "primary": True},
                {"action": "duplicate_profile", "label": self.tr("Duplicate"), "enabled": selected, "primary": False},
                {
                    "action": "set_default_profile",
                    "label": self.tr("Set Default"),
                    "enabled": selected and not bool(selected_profile and selected_profile.is_default),
                    "primary": False,
                },
                {"action": "delete_profile", "label": self.tr("Delete"), "enabled": selected, "primary": False},
            ]

        selected_connection = self._selected_connection()
        selected = selected_connection is not None
        return [
            {
                "action": "run_wizard",
                "label": self.tr("Run Setup Wizard")
                if self._state is not None and not self._state.connections
                else self.tr("Open Setup Wizard"),
                "enabled": True,
                "primary": True,
            },
            {"action": "add_connection", "label": self.tr("Add Connection"), "enabled": True, "primary": False},
            {"action": "duplicate_connection", "label": self.tr("Duplicate"), "enabled": selected, "primary": False},
            {
                "action": "delete_connection",
                "label": self.tr("Delete"),
                "enabled": selected and not bool(selected_connection and selected_connection.is_managed),
                "primary": False,
            },
        ]

    def _on_action_requested(self, action_name: str) -> None:
        actions: dict[str, Callable[[], None]] = {
            "run_wizard": self._on_run_wizard,
            "add_connection": self._on_add_connection,
            "duplicate_connection": self._on_duplicate_connection,
            "delete_connection": self._on_delete_connection,
            "add_profile": self._on_add_profile,
            "duplicate_profile": self._on_duplicate_profile,
            "set_default_profile": self._on_set_default_profile,
            "delete_profile": self._on_delete_profile,
        }
        action = actions.get(action_name)
        if action is None:
            return
        action()

    def _populate_connections(self, connections: Sequence[ConnectionSummary]) -> None:
        self.connections_table.setRowCount(0)
        for connection in connections:
            row = self.connections_table.rowCount()
            self.connections_table.insertRow(row)
            name_item = self._set_table_item(
                self.connections_table, row, 0, connection.display_name, connection.connection_id
            )
            if connection.is_managed:
                name_item.setToolTip(self.tr("Managed by the setup wizard. Duplicate it if you need an editable copy."))
            provider_label = _PROVIDER_LABELS.get(connection.provider, connection.provider.value)
            self._set_table_item(self.connections_table, row, 1, provider_label)
            self._set_table_item(self.connections_table, row, 2, connection.status.value.replace("_", " ").title())
            self._set_table_item(self.connections_table, row, 3, connection.default_model or "")
            self._set_table_item(self.connections_table, row, 4, connection.base_url or "")
        self._finalize_table(self.connections_table)

    def _populate_profiles(self, state: AppSetupState) -> None:
        self.profiles_table.setRowCount(0)
        default_row = 0
        for profile in state.shared_profiles:
            row = self.profiles_table.rowCount()
            self.profiles_table.insertRow(row)
            self._set_table_item(self.profiles_table, row, 0, profile.name, profile.profile_id)
            self._set_table_item(self.profiles_table, row, 1, profile.target_language)
            self._set_table_item(self.profiles_table, row, 2, self.tr("Yes") if profile.is_default else "")
            if profile.is_default:
                default_row = row
        self._finalize_table(self.profiles_table)
        if state.shared_profiles:
            self.profiles_table.selectRow(default_row)

    def _selected_table_row(self, table: QTableWidget) -> int | None:
        rows = table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return row if row >= 0 else None

    def _selected_connection(self) -> ConnectionSummary | None:
        if self._state is None:
            return None
        row = self._selected_table_row(self.connections_table)
        if row is None or row >= len(self._state.connections):
            return None
        return self._state.connections[row]

    def _selected_profile(self) -> WorkflowProfileDetail | None:
        if self._state is None:
            return None
        row = self._selected_table_row(self.profiles_table)
        if row is None or row >= len(self._state.shared_profiles):
            return None
        return self._state.shared_profiles[row]

    def _on_run_wizard(self) -> None:
        dialog = SetupWizardDialog(
            self._service,
            self._service.get_wizard_state(),
            parent=self._dialog_parent(),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _on_add_connection(self) -> None:
        self._edit_connection()

    def _edit_connection(self, connection: ConnectionSummary | None = None) -> None:
        connection = connection or self._selected_connection()
        dialog_kwargs: dict[str, object] = {
            "test_callback": self._test_connection_draft,
            "parent": self._dialog_parent(),
        }
        if connection is None:
            dialog = ConnectionEditorDialog(**dialog_kwargs)
        else:
            dialog_kwargs.update(
                draft=ConnectionDraft(
                    display_name=connection.display_name,
                    provider=connection.provider,
                    description=connection.description,
                    base_url=connection.base_url,
                    default_model=connection.default_model,
                    temperature=connection.temperature,
                    timeout=connection.timeout,
                    max_retries=connection.max_retries,
                    concurrency=connection.concurrency,
                    token_limit=connection.token_limit,
                    input_token_limit=connection.input_token_limit,
                    output_token_limit=connection.output_token_limit,
                    custom_parameters_json=connection.custom_parameters_json,
                ),
                connection_id=connection.connection_id,
                connection_summary=connection,
                reset_tokens_callback=self._reset_connection_tokens,
            )
            dialog = ConnectionEditorDialog(**dialog_kwargs)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._mutate(lambda: self._service.save_connection(dialog.request()))

    def _on_delete_connection(self) -> None:
        connection = self._selected_connection()
        if connection is None:
            return
        if not self._confirm(
            self.tr("Delete Connection"),
            self.tr(
                "Delete the selected connection? Existing profiles or projects may stop working until setup is fixed."
            ),
        ):
            return
        self._mutate(lambda: self._service.delete_connection(connection.connection_id))

    def _on_duplicate_connection(self) -> None:
        connection = self._selected_connection()
        if connection is None:
            return
        self._mutate(lambda: self._service.duplicate_connection(connection.connection_id))

    def _on_add_profile(self) -> None:
        if self._state is None or not self._state.connections:
            return
        self._edit_profile(self._new_profile_template())

    def _edit_profile(self, profile: WorkflowProfileDetail | None = None) -> None:
        if self._state is None:
            return
        current_profile = profile or self._selected_profile()
        if current_profile is None:
            return
        dialog = WorkflowProfileEditorDialog(
            profile=current_profile,
            connection_choices=self._connection_choices(),
            allow_name_edit=True,
            parent=self._dialog_parent(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._mutate(
            lambda: self._service.save_workflow_profile(
                SaveWorkflowProfileRequest(
                    profile=dialog.profile(),
                    set_as_default=bool(current_profile.is_default),
                )
            )
        )

    def _on_delete_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        if not self._confirm(
            self.tr("Delete Workflow Profile"),
            self.tr("Delete the selected workflow profile? Projects using it will need setup first."),
        ):
            return
        try:
            self._mutate(lambda: self._service.delete_workflow_profile(profile.profile_id))
        except Exception as exc:
            QMessageBox.warning(self, self.tr("App Setup"), str(exc))

    def _on_duplicate_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        self._mutate(lambda: self._service.duplicate_workflow_profile(profile.profile_id))

    def _on_set_default_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        self._mutate(
            lambda: self._service.save_workflow_profile(
                SaveWorkflowProfileRequest(
                    profile=profile.model_copy(update={"is_default": True}),
                    set_as_default=True,
                )
            )
        )

    def _on_profile_double_clicked(self, _row: int, _column: int) -> None:
        self._edit_profile()

    def _on_connection_double_clicked(self, _row: int, _column: int) -> None:
        connection = self._selected_connection()
        if connection is None or connection.is_managed:
            return
        self._edit_connection(connection)

    def _test_connection_draft(self, draft: ConnectionDraft) -> ConnectionTestResult:
        return self._service.test_connection(ConnectionTestRequest(connection=draft))

    def _reset_connection_tokens(self, connection_id: str) -> ConnectionSummary:
        updated = self._service.reset_connection_tokens(connection_id)
        self.refresh()
        return updated

    def _connection_choices(self) -> list[ConnectionChoice]:
        if self._state is None:
            return []
        return [
            ConnectionChoice(
                connection_id=connection.connection_id,
                label=connection.display_name,
                default_model=connection.default_model,
            )
            for connection in self._state.connections
        ]

    def _new_profile_template(self) -> WorkflowProfileDetail:
        assert self._state is not None
        base_profile = self._selected_profile() or (
            self._state.shared_profiles[0] if self._state.shared_profiles else None
        )
        if base_profile is not None:
            return base_profile.model_copy(
                update={
                    "profile_id": "__new__",
                    "name": self.tr("New Workflow Profile"),
                    "kind": WorkflowProfileKind.SHARED,
                    "is_default": False,
                }
            )

        first_connection = self._state.connections[0]
        routes = [
            WorkflowStepRoute(
                step_id=step_id,
                step_label=label,
                connection_id=(
                    first_connection.connection_id if step_id is not WorkflowStepId.TRANSLATOR_BATCH else None
                ),
                connection_label=(
                    first_connection.display_name if step_id is not WorkflowStepId.TRANSLATOR_BATCH else None
                ),
                model=(first_connection.default_model if step_id is not WorkflowStepId.TRANSLATOR_BATCH else None),
                step_config={},
            )
            for step_id, label in _NEW_PROFILE_ROUTE_SPECS
        ]
        return WorkflowProfileDetail(
            profile_id="__new__",
            name=self.tr("New Workflow Profile"),
            kind=WorkflowProfileKind.SHARED,
            target_language="English",
            routes=routes,
            is_default=False,
        )

    def _confirm(self, title: str, text: str) -> bool:
        return (
            QMessageBox.question(
                self,
                title,
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _dialog_parent(self) -> QWidget:
        parent = self.window()
        return parent if isinstance(parent, QWidget) else self

    def _mutate(self, callback: Callable[[], object]) -> None:
        callback()
        self.refresh()

    def _set_table_item(
        self, table: QTableWidget, row: int, column: int, text: str, user_data: str | None = None
    ) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if user_data is not None:
            item.setData(Qt.ItemDataRole.UserRole, user_data)
        table.setItem(row, column, item)
        return item

    def _finalize_table(self, table: QTableWidget) -> None:
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        fit_table_min_width(table)
