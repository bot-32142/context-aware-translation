"""Unit tests for ConfigEditorWidget."""

from unittest.mock import MagicMock

import pytest

# Check if PySide6 is available
try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

# Skip all tests in this module if PySide6 is not available
pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


class TestImageBackendEnum:
    """Tests for ImageBackend enum values."""

    def test_image_backend_enum_values(self):
        """Verify ImageBackend enum values match expected strings."""
        from context_aware_translation.llm.image_generator import ImageBackend

        assert ImageBackend.GEMINI.value == "gemini"
        assert ImageBackend.OPENAI.value == "openai"
        assert ImageBackend.QWEN.value == "qwen"


@pytest.fixture(scope="module")
def qapp():
    """Create a QApplication for testing Qt widgets."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_book_manager():
    """Create a mock BookManager."""
    manager = MagicMock()
    profile1 = MagicMock()
    profile1.name = "GPT-4"
    profile1.profile_id = "gpt4-profile"
    profile2 = MagicMock()
    profile2.name = "Claude"
    profile2.profile_id = "claude-profile"
    manager.list_endpoint_profiles.return_value = [profile1, profile2]
    return manager


@pytest.fixture
def widget(qapp, mock_book_manager):  # noqa: ARG001 - qapp fixture required for Qt
    """Create a ConfigEditorWidget for testing."""
    from context_aware_translation.ui.widgets.config_editor import ConfigEditorWidget

    widget = ConfigEditorWidget(mock_book_manager)
    yield widget
    widget.deleteLater()


class TestGetConfig:
    """Tests for get_config() method."""

    def test_get_config_returns_target_language(self, widget):
        """get_config should always include target language."""
        # Note: set_value expects the language code (e.g., "日语"), not the display name
        widget.language_dropdown.set_value("日语")

        config = widget.get_config()

        assert config["translation_target_language"] == "日语"

    def test_get_config_saves_image_reembedding_when_endpoint_selected(self, widget):
        """get_config should save image_reembedding_config when endpoint is selected."""
        from context_aware_translation.llm.image_generator import ImageBackend

        widget.reembedding_endpoint.setCurrentIndex(1)
        # Set backend to OpenAI (index 1)
        widget.reembedding_backend_combo.setCurrentIndex(1)

        config = widget.get_config()

        assert "image_reembedding_config" in config
        assert config["image_reembedding_config"]["endpoint_profile"] == "gpt4-profile"
        assert config["image_reembedding_config"]["backend"] == ImageBackend.OPENAI.value

    def test_get_config_saves_image_reembedding_endpoint_backend_pair(self, widget):
        """get_config should persist endpoint/backend pair for image reembedding config."""
        # Select an endpoint (index 1 = first actual profile after "(None)")
        widget.reembedding_endpoint.setCurrentIndex(1)
        # Set backend to Qwen (index 2)
        widget.reembedding_backend_combo.setCurrentIndex(2)

        config = widget.get_config()

        assert "image_reembedding_config" in config
        assert config["image_reembedding_config"]["endpoint_profile"] == "gpt4-profile"
        assert config["image_reembedding_config"]["backend"] == "qwen"

    def test_get_config_no_image_reembedding_when_no_endpoint(self, widget):
        """get_config should NOT save image_reembedding_config when endpoint is not selected."""
        widget.reembedding_endpoint.setCurrentIndex(0)  # "(None)"

        config = widget.get_config()

        # Config should NOT include image_reembedding_config
        assert "image_reembedding_config" not in config

    def test_get_config_saves_ocr_config_without_reembedding_flag(self, widget):
        """get_config should not include legacy enable_image_reembedding in ocr_config."""
        # Set OCR endpoint
        widget.ocr_endpoint.setCurrentIndex(1)  # First actual profile

        config = widget.get_config()

        assert "ocr_config" in config
        assert "enable_image_reembedding" not in config["ocr_config"]

    def test_get_config_saves_translator_batch_fields(self, widget):
        """get_config should include translator batch settings."""
        widget.translator_batch_provider.setCurrentIndex(1)  # Gemini AI Studio
        widget.translator_batch_api_key.setText("test-key")
        widget.translator_batch_model.setText("gemini-2.5-flash")
        widget.translator_batch_size_spin.setValue(256)
        widget.translator_batch_thinking_mode.setCurrentIndex(3)  # medium

        config = widget.get_config()

        assert "translator_batch_config" in config
        translator_batch = config["translator_batch_config"]
        assert translator_batch["provider"] == "gemini_ai_studio"
        assert translator_batch["api_key"] == "test-key"
        assert translator_batch["model"] == "gemini-2.5-flash"
        assert translator_batch["batch_size"] == 256
        assert translator_batch["thinking_mode"] == "medium"


class TestSetConfig:
    """Tests for set_config() method."""

    def test_set_config_loads_image_reembedding_config(self, widget):
        """set_config should populate image reembedding fields from config."""
        config = {
            "translation_target_language": "Korean",
            "image_reembedding_config": {
                "endpoint_profile": "gpt4-profile",
                "backend": "openai",
            },
        }

        widget.set_config(config)

        # Verify backend was set to OpenAI (index 1)
        assert widget.reembedding_backend_combo.currentIndex() == 1
        # Verify endpoint was set
        assert widget.reembedding_endpoint.currentText() == "GPT-4"

    def test_set_config_defaults_to_gemini_backend(self, widget):
        """set_config should default to Gemini if backend not specified."""
        config = {
            "translation_target_language": "Korean",
            "image_reembedding_config": {
                "endpoint_profile": "gpt4-profile",
                # No backend - should default to gemini
            },
        }

        widget.set_config(config)

        # Verify backend defaults to Gemini (index 0)
        assert widget.reembedding_backend_combo.currentIndex() == 0

    def test_set_config_handles_missing_image_reembedding_config(self, widget):
        """set_config should handle missing image_reembedding_config gracefully."""
        # Set to non-default values first
        widget.reembedding_backend_combo.setCurrentIndex(1)
        widget.reembedding_endpoint.setCurrentIndex(1)

        config = {
            "translation_target_language": "Korean",
            # No image_reembedding_config
        }

        # Should not raise and should not change existing values
        widget.set_config(config)

        # Values should remain unchanged (still at index 1)
        assert widget.reembedding_backend_combo.currentIndex() == 1

    def test_set_config_loads_translator_batch_fields(self, widget):
        """set_config should load translator batch fields."""
        config = {
            "translation_target_language": "Korean",
            "translator_batch_config": {
                "provider": "gemini_ai_studio",
                "api_key": "batch-key",
                "model": "gemini-2.5-pro",
                "batch_size": 999,
                "thinking_mode": "high",
            },
        }

        widget.set_config(config)

        assert widget.translator_batch_provider.currentData() == "gemini_ai_studio"
        assert widget.translator_batch_api_key.text() == "batch-key"
        assert widget.translator_batch_model.text() == "gemini-2.5-pro"
        assert widget.translator_batch_size_spin.value() == 999
        assert widget.translator_batch_thinking_mode.currentData() == "high"


class TestValidate:
    """Tests for validate() method."""

    def test_validate_requires_target_language(self, widget):
        """validate should return error if no target language."""
        # The LanguageDropdown always has a default value (first item).
        # To test empty validation, we need to access the underlying combobox.
        widget.language_dropdown.setCurrentIndex(-1)  # No selection

        result = widget.validate()

        assert result == "Target language is required."

    def test_validate_allows_missing_reembedding_endpoint(self, widget):
        """validate should pass even when reembedding endpoint is not selected."""
        widget.language_dropdown.set_value("英语")
        widget.reembedding_endpoint.setCurrentIndex(0)  # "(None)"

        result = widget.validate()

        assert result is None

    def test_validate_requires_batch_api_key_when_provider_enabled(self, widget):
        widget.language_dropdown.set_value("英语")
        widget.translator_batch_provider.setCurrentIndex(1)
        widget.translator_batch_api_key.setText("")
        widget.translator_batch_model.setText("gemini-2.5-flash")

        result = widget.validate()

        assert result == "Translator batch API key is required when provider is enabled."

    def test_validate_requires_batch_model_when_provider_enabled(self, widget):
        widget.language_dropdown.set_value("英语")
        widget.translator_batch_provider.setCurrentIndex(1)
        widget.translator_batch_api_key.setText("k")
        widget.translator_batch_model.setText("")

        result = widget.validate()

        assert result == "Translator batch model is required when provider is enabled."

    def test_validate_passes_with_reembedding_endpoint_selected(self, widget):
        """validate should pass when reembedding endpoint is selected."""
        widget.language_dropdown.set_value("英语")
        widget.reembedding_endpoint.setCurrentIndex(1)  # First profile

        result = widget.validate()

        assert result is None


class TestConfigRoundTrip:
    """Tests for config get/set round-trip consistency."""

    def test_image_reembedding_config_roundtrip(self, widget):
        """Config should survive a get/set round-trip."""
        from context_aware_translation.llm.image_generator import ImageBackend

        # Set initial values
        widget.language_dropdown.set_value("英语")
        widget.reembedding_endpoint.setCurrentIndex(2)  # "Claude"
        widget.reembedding_backend_combo.setCurrentIndex(2)  # "Qwen"

        # Get config
        config = widget.get_config()

        # Verify extracted config
        assert config["image_reembedding_config"]["backend"] == ImageBackend.QWEN.value
        assert config["image_reembedding_config"]["endpoint_profile"] == "claude-profile"

        # Reset widget
        widget.reembedding_backend_combo.setCurrentIndex(0)
        widget.reembedding_endpoint.setCurrentIndex(0)

        # Set config back
        widget.set_config(config)

        # Verify values restored
        assert widget.reembedding_backend_combo.currentIndex() == 2  # Qwen
        assert widget.reembedding_endpoint.currentText() == "Claude"


class TestFieldTooltips:
    """Tests for config option hover explanations."""

    def test_all_config_option_fields_have_tooltips(self, widget):
        """Every config option in the profile editor should have a hover tooltip."""
        fields = [
            ("Target Language", widget.language_dropdown),
            ("Extractor Endpoint", widget.extractor_endpoint),
            ("Max Gleaning", widget.max_gleaning_spin),
            ("Max Term Name Length", widget.max_term_name_spin),
            ("Summarizer Endpoint", widget.summarizer_endpoint),
            ("Glossary Endpoint", widget.glossary_endpoint),
            ("Translator Endpoint", widget.translator_endpoint),
            ("Chunks per Call", widget.chunks_per_call_spin),
            ("Chunk Size", widget.chunk_size_spin),
            ("Translator Batch Provider", widget.translator_batch_provider),
            ("Translator Batch API Key", widget.translator_batch_api_key),
            ("Translator Batch Model", widget.translator_batch_model),
            ("Translator Batch Size", widget.translator_batch_size_spin),
            ("Translator Batch Thinking", widget.translator_batch_thinking_mode),
            ("Review Endpoint", widget.review_endpoint),
            ("OCR Endpoint", widget.ocr_endpoint),
            ("OCR DPI", widget.ocr_dpi_spin),
            ("Strip Artifacts", widget.strip_artifacts_check),
            ("Reembedding Backend", widget.reembedding_backend_combo),
            ("Reembedding Endpoint", widget.reembedding_endpoint),
            ("Manga Endpoint", widget.manga_endpoint),
            ("Manga Pages per Call", widget.manga_pages_per_call_spin),
        ]
        missing = [name for name, field in fields if not field.toolTip().strip()]
        assert missing == []
