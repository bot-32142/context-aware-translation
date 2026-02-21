"""Dialog for creating/editing endpoint profiles."""

import json
import sqlite3

import httpx
from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.endpoint_profile import EndpointProfile


class ConnectionTestSignals(QObject):
    """Signals for connection test worker."""

    finished = Signal(bool, str)  # success, message


class ConnectionTestWorker(QRunnable):
    """Worker to test API connection in background thread."""

    def __init__(self, base_url: str, api_key: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.signals = ConnectionTestSignals()

    def run(self) -> None:
        """Run the connection test."""
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(
                    f"{self.base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if response.status_code == 200:
                    self.signals.finished.emit(True, "Connection successful!")
                else:
                    self.signals.finished.emit(False, f"Connection failed: HTTP {response.status_code}")
        except Exception as e:
            error_msg = str(e)
            if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
                self.signals.finished.emit(False, "Connection timed out.")
            else:
                self.signals.finished.emit(False, f"Connection error: {error_msg}")


class EndpointProfileDialog(QDialog):
    """Dialog for creating/editing endpoint profiles."""

    def __init__(
        self,
        book_manager: BookManager,
        profile: EndpointProfile | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self.profile = profile
        self._form_layout: QFormLayout | None = None
        self.setWindowTitle(self.tr("Edit Endpoint Profile") if profile else self.tr("New Endpoint Profile"))
        self.setMinimumWidth(450)
        self._setup_ui()
        if profile:
            self._populate_from_profile()

    def _create_token_limit_row(self) -> tuple[QWidget, QCheckBox, QSpinBox]:
        """Create a checkbox+spinner row for a token limit field."""
        layout = QHBoxLayout()
        checkbox = QCheckBox(self.tr("Enable"))
        layout.addWidget(checkbox)
        spinner = QSpinBox()
        spinner.setRange(1, 999_999_999)
        spinner.setValue(1_000_000)
        spinner.setEnabled(False)
        layout.addWidget(spinner)
        checkbox.toggled.connect(lambda checked: spinner.setEnabled(checked))
        widget = QWidget()
        widget.setLayout(layout)
        return widget, checkbox, spinner

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._form_layout = QFormLayout()

        # Name
        self.name_edit = QLineEdit()
        self._form_layout.addRow(self.tr("Name*:"), self.name_edit)

        # Description
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(60)
        self._form_layout.addRow(self.tr("Description:"), self.description_edit)

        # API Key (password mode)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText(self.tr("Leave empty to use environment variable"))
        self._form_layout.addRow(self.tr("API Key:"), self.api_key_edit)

        # Base URL
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        self._form_layout.addRow(self.tr("Base URL:"), self.base_url_edit)

        # Model
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("gpt-4")
        self._form_layout.addRow(self.tr("Model:"), self.model_edit)

        # Temperature
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.0)
        self._form_layout.addRow(self.tr("Temperature:"), self.temperature_spin)

        # Custom Parameters (kwargs)
        self.kwargs_edit = QTextEdit()
        self.kwargs_edit.setMaximumHeight(80)
        self.kwargs_edit.setPlaceholderText('{"reasoning_effort": "none"}')
        self._form_layout.addRow(self.tr("Custom Parameters:"), self.kwargs_edit)

        # Timeout
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setValue(300)
        self.timeout_spin.setSuffix(self.tr(" seconds"))
        self._form_layout.addRow(self.tr("Timeout:"), self.timeout_spin)

        # Max Retries
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(3)
        self._form_layout.addRow(self.tr("Max Retries:"), self.retries_spin)

        # Concurrency
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 50)
        self.concurrency_spin.setValue(5)
        self._form_layout.addRow(self.tr("Concurrency:"), self.concurrency_spin)

        # Total Token Limit
        self.total_limit_widget, self.total_limit_checkbox, self.total_limit_spin = self._create_token_limit_row()
        self._form_layout.addRow(self.tr("Total Token Limit:"), self.total_limit_widget)

        # Input Token Limit
        self.input_limit_widget, self.input_limit_checkbox, self.input_limit_spin = self._create_token_limit_row()
        self._form_layout.addRow(self.tr("Input Token Limit:"), self.input_limit_widget)

        # Output Token Limit
        self.output_limit_widget, self.output_limit_checkbox, self.output_limit_spin = self._create_token_limit_row()
        self._form_layout.addRow(self.tr("Output Token Limit:"), self.output_limit_widget)

        # Token usage labels (read-only, only shown in edit mode)
        if self.profile:
            self.total_used_label = QLabel("0")
            self._form_layout.addRow(self.tr("Total Used:"), self.total_used_label)

            self.input_used_label = QLabel("0")
            self._form_layout.addRow(self.tr("Input Used:"), self.input_used_label)

            self.cached_input_label = QLabel("0")
            self._form_layout.addRow(self.tr("  Cached Input:"), self.cached_input_label)

            self.uncached_input_label = QLabel("0")
            self._form_layout.addRow(self.tr("  Uncached Input:"), self.uncached_input_label)

            self.output_used_label = QLabel("0")
            self._form_layout.addRow(self.tr("Output Used:"), self.output_used_label)

        # Wrap form in a scroll area so the dialog doesn't overflow on small screens
        form_widget = QWidget()
        form_widget.setLayout(self._form_layout)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(form_widget)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll_area)

        # Test Connection button
        test_layout = QHBoxLayout()
        test_layout.addStretch()
        self.test_btn = QPushButton(self.tr("Test Connection"))
        self.test_btn.clicked.connect(self._on_test_connection)
        test_layout.addWidget(self.test_btn)
        layout.addLayout(test_layout)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._apply_tooltips()

    def _set_field_tooltip(self, widget: QWidget, text: str) -> None:
        """Apply tooltip to a field and its label in the form layout."""
        if self._form_layout is None:
            return
        widget.setToolTip(text)
        label = self._form_layout.labelForField(widget)
        if label:
            label.setToolTip(text)

    def _apply_tooltips(self) -> None:
        """Apply hover explanations for all endpoint profile options."""
        self._set_field_tooltip(self.name_edit, self.tr("Profile name shown in endpoint dropdowns."))
        self._set_field_tooltip(self.description_edit, self.tr("Optional notes to describe this endpoint profile."))
        self._set_field_tooltip(
            self.api_key_edit,
            self.tr("API key for this provider. Leave empty to rely on environment variables."),
        )
        self._set_field_tooltip(
            self.base_url_edit,
            self.tr("API base URL, for example https://api.openai.com/v1."),
        )
        self._set_field_tooltip(self.model_edit, self.tr("Model name sent to the API, such as gpt-4.1."))
        self._set_field_tooltip(
            self.temperature_spin,
            self.tr("Sampling temperature. Lower values are more deterministic."),
        )
        self._set_field_tooltip(
            self.kwargs_edit,
            self.tr('Additional API parameters as JSON. For example: {"reasoning_effort": "none"}'),
        )
        self._set_field_tooltip(
            self.timeout_spin,
            self.tr("Request timeout in seconds before a call is treated as failed."),
        )
        self._set_field_tooltip(
            self.retries_spin,
            self.tr("Maximum retry attempts after transient request failures."),
        )
        self._set_field_tooltip(
            self.concurrency_spin,
            self.tr("Maximum number of concurrent requests using this endpoint."),
        )

        self._set_field_tooltip(
            self.total_limit_widget,
            self.tr("Optional overall token budget cap for this endpoint profile."),
        )
        self.total_limit_checkbox.setToolTip(self.tr("Enable or disable the total token budget cap."))
        self.total_limit_spin.setToolTip(self.tr("Maximum total tokens allowed for this endpoint profile."))

        self._set_field_tooltip(
            self.input_limit_widget,
            self.tr("Optional input token budget cap for this endpoint profile."),
        )
        self.input_limit_checkbox.setToolTip(self.tr("Enable or disable the input token budget cap."))
        self.input_limit_spin.setToolTip(self.tr("Maximum input tokens allowed for this endpoint profile."))

        self._set_field_tooltip(
            self.output_limit_widget,
            self.tr("Optional output token budget cap for this endpoint profile."),
        )
        self.output_limit_checkbox.setToolTip(self.tr("Enable or disable the output token budget cap."))
        self.output_limit_spin.setToolTip(self.tr("Maximum output tokens allowed for this endpoint profile."))

        if self.profile:
            self._set_field_tooltip(self.total_used_label, self.tr("Total tokens already used by this profile."))
            self._set_field_tooltip(self.input_used_label, self.tr("Total input tokens used by this profile."))
            self._set_field_tooltip(
                self.cached_input_label,
                self.tr("Input tokens served from cache and billed at cached-token rates."),
            )
            self._set_field_tooltip(
                self.uncached_input_label,
                self.tr("Input tokens processed without cache for this profile."),
            )
            self._set_field_tooltip(self.output_used_label, self.tr("Total output tokens used by this profile."))

        self.test_btn.setToolTip(self.tr("Verify API key, base URL, and connectivity with a test request."))

    def _on_test_connection(self) -> None:
        """Test the API connection with current settings."""
        base_url = self.base_url_edit.text().strip() or "https://api.openai.com/v1"
        api_key = self.api_key_edit.text()

        if not api_key:
            QMessageBox.warning(self, self.tr("Test Connection"), self.tr("API Key is required for testing."))
            return

        self.test_btn.setEnabled(False)
        self.test_btn.setText(self.tr("Testing..."))

        # Run connection test in background thread
        worker = ConnectionTestWorker(base_url, api_key)
        worker.signals.finished.connect(self._on_test_connection_finished)
        QThreadPool.globalInstance().start(worker)

    def _on_test_connection_finished(self, success: bool, message: str) -> None:
        """Handle connection test completion."""
        self.test_btn.setEnabled(True)
        self.test_btn.setText(self.tr("Test Connection"))

        if success:
            QMessageBox.information(self, self.tr("Test Connection"), self.tr(message))
        else:
            QMessageBox.warning(self, self.tr("Test Connection"), self.tr(message))

    def _populate_from_profile(self) -> None:
        if not self.profile:
            return
        self.name_edit.setText(self.profile.name)
        self.description_edit.setPlainText(self.profile.description or "")
        self.api_key_edit.setText(self.profile.api_key)
        self.base_url_edit.setText(self.profile.base_url)
        self.model_edit.setText(self.profile.model)
        self.temperature_spin.setValue(self.profile.temperature)
        if self.profile.kwargs:
            self.kwargs_edit.setPlainText(json.dumps(self.profile.kwargs, indent=2, ensure_ascii=False))
        self.timeout_spin.setValue(self.profile.timeout)
        self.retries_spin.setValue(self.profile.max_retries)
        self.concurrency_spin.setValue(self.profile.concurrency)

        # Total token limit
        if self.profile.token_limit is not None:
            self.total_limit_checkbox.setChecked(True)
            self.total_limit_spin.setValue(self.profile.token_limit)
        else:
            self.total_limit_checkbox.setChecked(False)

        # Input token limit
        if self.profile.input_token_limit is not None:
            self.input_limit_checkbox.setChecked(True)
            self.input_limit_spin.setValue(self.profile.input_token_limit)
        else:
            self.input_limit_checkbox.setChecked(False)

        # Output token limit
        if self.profile.output_token_limit is not None:
            self.output_limit_checkbox.setChecked(True)
            self.output_limit_spin.setValue(self.profile.output_token_limit)
        else:
            self.output_limit_checkbox.setChecked(False)

        # Usage labels
        self.total_used_label.setText(f"{self.profile.tokens_used:,}")
        self.input_used_label.setText(f"{self.profile.input_tokens_used:,}")
        self.cached_input_label.setText(f"{self.profile.cached_input_tokens_used:,}")
        self.uncached_input_label.setText(f"{self.profile.uncached_input_tokens_used:,}")
        self.output_used_label.setText(f"{self.profile.output_tokens_used:,}")

    def changeEvent(self, event: QEvent) -> None:
        """Handle change events."""
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        """Retranslate UI strings."""
        self.setWindowTitle(self.tr("Edit Endpoint Profile") if self.profile else self.tr("New Endpoint Profile"))

        if self._form_layout:
            label = self._form_layout.labelForField(self.name_edit)
            if label:
                label.setText(self.tr("Name*:"))

            label = self._form_layout.labelForField(self.description_edit)
            if label:
                label.setText(self.tr("Description:"))

            label = self._form_layout.labelForField(self.api_key_edit)
            if label:
                label.setText(self.tr("API Key:"))

            label = self._form_layout.labelForField(self.base_url_edit)
            if label:
                label.setText(self.tr("Base URL:"))

            label = self._form_layout.labelForField(self.model_edit)
            if label:
                label.setText(self.tr("Model:"))

            label = self._form_layout.labelForField(self.temperature_spin)
            if label:
                label.setText(self.tr("Temperature:"))

            label = self._form_layout.labelForField(self.kwargs_edit)
            if label:
                label.setText(self.tr("Custom Parameters:"))

            label = self._form_layout.labelForField(self.timeout_spin)
            if label:
                label.setText(self.tr("Timeout:"))

            label = self._form_layout.labelForField(self.retries_spin)
            if label:
                label.setText(self.tr("Max Retries:"))

            label = self._form_layout.labelForField(self.concurrency_spin)
            if label:
                label.setText(self.tr("Concurrency:"))

            label = self._form_layout.labelForField(self.total_limit_widget)
            if label:
                label.setText(self.tr("Total Token Limit:"))

            label = self._form_layout.labelForField(self.input_limit_widget)
            if label:
                label.setText(self.tr("Input Token Limit:"))

            label = self._form_layout.labelForField(self.output_limit_widget)
            if label:
                label.setText(self.tr("Output Token Limit:"))

            if self.profile:
                label = self._form_layout.labelForField(self.total_used_label)
                if label:
                    label.setText(self.tr("Total Used:"))
                label = self._form_layout.labelForField(self.input_used_label)
                if label:
                    label.setText(self.tr("Input Used:"))
                label = self._form_layout.labelForField(self.cached_input_label)
                if label:
                    label.setText(self.tr("  Cached Input:"))
                label = self._form_layout.labelForField(self.uncached_input_label)
                if label:
                    label.setText(self.tr("  Uncached Input:"))
                label = self._form_layout.labelForField(self.output_used_label)
                if label:
                    label.setText(self.tr("Output Used:"))

        self.total_limit_checkbox.setText(self.tr("Enable"))
        self.input_limit_checkbox.setText(self.tr("Enable"))
        self.output_limit_checkbox.setText(self.tr("Enable"))
        self.api_key_edit.setPlaceholderText(self.tr("Leave empty to use environment variable"))
        self.base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        self.model_edit.setPlaceholderText("gpt-4")
        self.kwargs_edit.setPlaceholderText('{"reasoning_effort": "none"}')
        self.timeout_spin.setSuffix(self.tr(" seconds"))
        self.test_btn.setText(self.tr("Test Connection"))
        self._apply_tooltips()

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, self.tr("Validation Error"), self.tr("Name is required."))
            return

        # Validate base_url
        base_url = self.base_url_edit.text().strip()
        if not base_url:
            QMessageBox.warning(self, self.tr("Validation Error"), self.tr("Base URL is required."))
            return
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            QMessageBox.warning(
                self,
                self.tr("Validation Error"),
                self.tr("Base URL must start with http:// or https://"),
            )
            return

        # Validate model
        model = self.model_edit.text().strip()
        if not model:
            QMessageBox.warning(self, self.tr("Validation Error"), self.tr("Model is required."))
            return

        # Parse custom parameters
        kwargs_text = self.kwargs_edit.toPlainText().strip()
        kwargs = {}
        if kwargs_text:
            try:
                kwargs = json.loads(kwargs_text)
                if not isinstance(kwargs, dict):
                    QMessageBox.warning(
                        self, self.tr("Validation Error"), self.tr("Custom parameters must be a JSON object.")
                    )
                    return
            except json.JSONDecodeError as e:
                QMessageBox.warning(
                    self, self.tr("Validation Error"), self.tr("Invalid JSON in custom parameters: ") + str(e)
                )
                return

        token_limit = self.total_limit_spin.value() if self.total_limit_checkbox.isChecked() else None
        input_token_limit = self.input_limit_spin.value() if self.input_limit_checkbox.isChecked() else None
        output_token_limit = self.output_limit_spin.value() if self.output_limit_checkbox.isChecked() else None

        try:
            if self.profile:
                # Update existing
                self.book_manager.update_endpoint_profile(
                    self.profile.profile_id,
                    name=name,
                    description=self.description_edit.toPlainText().strip() or None,
                    api_key=self.api_key_edit.text(),
                    base_url=base_url,
                    model=model,
                    temperature=self.temperature_spin.value(),
                    kwargs=kwargs,
                    timeout=self.timeout_spin.value(),
                    max_retries=self.retries_spin.value(),
                    concurrency=self.concurrency_spin.value(),
                    token_limit=token_limit,
                    input_token_limit=input_token_limit,
                    output_token_limit=output_token_limit,
                )
            else:
                # Create new
                self.book_manager.create_endpoint_profile(
                    name=name,
                    description=self.description_edit.toPlainText().strip() or None,
                    api_key=self.api_key_edit.text(),
                    base_url=base_url,
                    model=model,
                    temperature=self.temperature_spin.value(),
                    kwargs=kwargs,
                    timeout=self.timeout_spin.value(),
                    max_retries=self.retries_spin.value(),
                    concurrency=self.concurrency_spin.value(),
                    token_limit=token_limit,
                    input_token_limit=input_token_limit,
                    output_token_limit=output_token_limit,
                )
            self.accept()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, self.tr("Error"), self.tr("An endpoint profile with this name already exists."))
        except Exception as e:
            QMessageBox.critical(self, self.tr("Save Error"), str(e))
