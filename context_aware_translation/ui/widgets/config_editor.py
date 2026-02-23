"""Reusable configuration editor widget."""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.llm.image_generator import ImageBackend
from context_aware_translation.storage.book_manager import BookManager

from ..utils import create_tip_label
from .collapsible_section import CollapsibleSection
from .language_dropdown import LanguageDropdown


class ConfigEditorWidget(QWidget):
    """
    Reusable widget for editing configuration settings.

    This widget contains all the collapsible sections for configuring:
    - Target language
    - Extractor settings
    - Summarizer settings
    - Glossary translation settings
    - Translator settings
    - Translator batch settings (optional, Gemini-only)
    - Review settings
    - OCR settings
    - Image reembedding settings
    """

    def __init__(self, book_manager: BookManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self._setup_ui()

    def _get_endpoint_profiles(self) -> list[tuple[str, str | None]]:
        """Get list of endpoint profiles for dropdowns."""
        profiles = self.book_manager.list_endpoint_profiles()
        return [(self.tr("(None)"), None)] + [(p.name, p.profile_id) for p in profiles]

    def _create_endpoint_dropdown(self) -> QComboBox:
        """Create an endpoint profile dropdown."""
        combo = QComboBox()
        for name, profile_id in self._get_endpoint_profiles():
            combo.addItem(name, profile_id)
        return combo

    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for the form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(4)

        def style_form(form: QFormLayout) -> None:
            form.setContentsMargins(16, 8, 8, 8)
            form.setVerticalSpacing(8)
            form.setHorizontalSpacing(12)

        def add_hint(form: QFormLayout, text: str):
            hint = create_tip_label(text)
            form.addRow(hint)
            return hint

        # === Target Language Section ===
        self._language_section = CollapsibleSection(self.tr("Target Language"))
        self._language_layout = QFormLayout()
        style_form(self._language_layout)
        language_widget = QWidget()
        language_widget.setLayout(self._language_layout)

        self._language_hint = add_hint(self._language_layout, self._language_hint_text())
        self.language_dropdown = LanguageDropdown()
        self._language_layout.addRow(self.tr("Target Language*:"), self.language_dropdown)

        self._language_section.set_content(language_widget)
        self._language_section.set_expanded(True)
        layout.addWidget(self._language_section)

        # === Extractor Section ===
        self._extractor_section = CollapsibleSection(self.tr("Extractor (Term Extraction)"))
        self._extractor_layout = QFormLayout()
        style_form(self._extractor_layout)
        extractor_widget = QWidget()
        extractor_widget.setLayout(self._extractor_layout)

        self._extractor_hint = add_hint(self._extractor_layout, self._extractor_hint_text())
        self.extractor_endpoint = self._create_endpoint_dropdown()
        self._extractor_layout.addRow(self.tr("Endpoint Profile:"), self.extractor_endpoint)

        self.max_gleaning_spin = QSpinBox()
        self.max_gleaning_spin.setRange(0, 10)
        self.max_gleaning_spin.setValue(3)
        self.max_gleaning_spin.setToolTip(self.tr("Number of extraction passes to find more terms"))
        self._extractor_layout.addRow(self.tr("Max Gleaning:"), self.max_gleaning_spin)

        self.max_term_name_spin = QSpinBox()
        self.max_term_name_spin.setRange(10, 500)
        self.max_term_name_spin.setValue(200)
        self.max_term_name_spin.setToolTip(self.tr("Maximum character length for term names"))
        self._extractor_layout.addRow(self.tr("Max Term Name Length:"), self.max_term_name_spin)

        self._extractor_section.set_content(extractor_widget)
        layout.addWidget(self._extractor_section)

        # === Summarizer Section ===
        self._summarizer_section = CollapsibleSection(self.tr("Summarizer (Term Description)"))
        self._summarizer_layout = QFormLayout()
        style_form(self._summarizer_layout)
        summarizer_widget = QWidget()
        summarizer_widget.setLayout(self._summarizer_layout)

        self._summarizer_hint = add_hint(self._summarizer_layout, self._summarizer_hint_text())
        self.summarizer_endpoint = self._create_endpoint_dropdown()
        self._summarizer_layout.addRow(self.tr("Endpoint Profile:"), self.summarizer_endpoint)

        self._summarizer_section.set_content(summarizer_widget)
        layout.addWidget(self._summarizer_section)

        # === Glossary Translation Section ===
        self._glossary_section = CollapsibleSection(self.tr("Glossary Translation"))
        self._glossary_layout = QFormLayout()
        style_form(self._glossary_layout)
        glossary_widget = QWidget()
        glossary_widget.setLayout(self._glossary_layout)

        self._glossary_hint = add_hint(self._glossary_layout, self._glossary_hint_text())
        self.glossary_endpoint = self._create_endpoint_dropdown()
        self._glossary_layout.addRow(self.tr("Endpoint Profile:"), self.glossary_endpoint)

        self._glossary_section.set_content(glossary_widget)
        layout.addWidget(self._glossary_section)

        # === Translator Section ===
        self._translator_section = CollapsibleSection(self.tr("Translator (Main Translation)"))
        self._translator_layout = QFormLayout()
        style_form(self._translator_layout)
        translator_widget = QWidget()
        translator_widget.setLayout(self._translator_layout)

        self._translator_hint = add_hint(self._translator_layout, self._translator_hint_text())
        self.translator_endpoint = self._create_endpoint_dropdown()
        self._translator_layout.addRow(self.tr("Endpoint Profile:"), self.translator_endpoint)

        self.enable_polish_check = QCheckBox()
        self.enable_polish_check.setChecked(True)
        self.enable_polish_check.setToolTip(self.tr("Enable post-translation polishing pass"))
        self._translator_layout.addRow(self.tr("Enable Polish:"), self.enable_polish_check)

        self.chunks_per_call_spin = QSpinBox()
        self.chunks_per_call_spin.setRange(1, 20)
        self.chunks_per_call_spin.setValue(5)
        self.chunks_per_call_spin.setToolTip(self.tr("Number of chunks to translate per LLM call"))
        self._translator_layout.addRow(self.tr("Chunks per Call:"), self.chunks_per_call_spin)

        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(100, 5000)
        self.chunk_size_spin.setValue(1000)
        self.chunk_size_spin.setToolTip(self.tr("Maximum token size per chunk"))
        self._translator_layout.addRow(self.tr("Chunk Size:"), self.chunk_size_spin)

        self._translator_section.set_content(translator_widget)
        layout.addWidget(self._translator_section)

        # === Translator Batch Section ===
        self._translator_batch_section = CollapsibleSection(self.tr("Translator Batch (Optional)"))
        self._translator_batch_layout = QFormLayout()
        style_form(self._translator_batch_layout)
        translator_batch_widget = QWidget()
        translator_batch_widget.setLayout(self._translator_batch_layout)

        self._translator_batch_hint = add_hint(self._translator_batch_layout, self._translator_batch_hint_text())
        self.translator_batch_provider = QComboBox()
        self.translator_batch_provider.addItem(self.tr("Disabled"), "")
        self.translator_batch_provider.addItem(self.tr("Gemini AI Studio"), "gemini_ai_studio")
        self._translator_batch_layout.addRow(self.tr("Provider:"), self.translator_batch_provider)

        self.translator_batch_api_key = QLineEdit()
        self.translator_batch_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.translator_batch_api_key.setPlaceholderText(self.tr("AIza..."))
        self._translator_batch_layout.addRow(self.tr("API Key:"), self.translator_batch_api_key)

        self.translator_batch_model = QLineEdit()
        self.translator_batch_model.setPlaceholderText(self.tr("gemini-2.5-flash"))
        self._translator_batch_layout.addRow(self.tr("Model:"), self.translator_batch_model)

        self.translator_batch_size_spin = QSpinBox()
        self.translator_batch_size_spin.setRange(1, 5000)
        self.translator_batch_size_spin.setValue(500)
        self._translator_batch_layout.addRow(self.tr("Batch Size:"), self.translator_batch_size_spin)

        self.translator_batch_thinking_mode = QComboBox()
        self.translator_batch_thinking_mode.addItem(self.tr("Auto"), "auto")
        self.translator_batch_thinking_mode.addItem(self.tr("Off"), "off")
        self.translator_batch_thinking_mode.addItem(self.tr("Low"), "low")
        self.translator_batch_thinking_mode.addItem(self.tr("Medium"), "medium")
        self.translator_batch_thinking_mode.addItem(self.tr("High"), "high")
        self._translator_batch_layout.addRow(self.tr("Thinking Mode:"), self.translator_batch_thinking_mode)

        self._translator_batch_section.set_content(translator_batch_widget)
        layout.addWidget(self._translator_batch_section)

        # === Review Section ===
        self._review_section = CollapsibleSection(self.tr("Review (Optional)"))
        self._review_layout = QFormLayout()
        style_form(self._review_layout)
        review_widget = QWidget()
        review_widget.setLayout(self._review_layout)

        self._review_hint = add_hint(self._review_layout, self._review_hint_text())
        self.review_endpoint = self._create_endpoint_dropdown()
        self._review_layout.addRow(self.tr("Endpoint Profile:"), self.review_endpoint)

        self._review_section.set_content(review_widget)
        layout.addWidget(self._review_section)

        # === OCR Section ===
        self._ocr_section = CollapsibleSection(self.tr("OCR (Optional)"))
        self._ocr_layout = QFormLayout()
        style_form(self._ocr_layout)
        ocr_widget = QWidget()
        ocr_widget.setLayout(self._ocr_layout)

        self._ocr_hint = add_hint(self._ocr_layout, self._ocr_hint_text())
        self.ocr_endpoint = self._create_endpoint_dropdown()
        self._ocr_layout.addRow(self.tr("Endpoint Profile:"), self.ocr_endpoint)

        self.ocr_dpi_spin = QSpinBox()
        self.ocr_dpi_spin.setRange(72, 600)
        self.ocr_dpi_spin.setValue(150)
        self.ocr_dpi_spin.setToolTip(self.tr("DPI for image compression before OCR"))
        self._ocr_layout.addRow(self.tr("OCR DPI:"), self.ocr_dpi_spin)

        self.strip_artifacts_check = QCheckBox()
        self.strip_artifacts_check.setChecked(True)
        self.strip_artifacts_check.setToolTip(self.tr("Remove LLM artifacts from OCR output"))
        self._ocr_layout.addRow(self.tr("Strip Artifacts:"), self.strip_artifacts_check)

        self.enable_reembedding_check = QCheckBox()
        self.enable_reembedding_check.setChecked(False)
        self.enable_reembedding_check.setToolTip(self.tr("Re-embed images in translated output"))
        self._ocr_layout.addRow(self.tr("Enable Image Re-embedding:"), self.enable_reembedding_check)

        self._ocr_section.set_content(ocr_widget)
        layout.addWidget(self._ocr_section)

        # === Image Reembedding Section ===
        self._reembedding_section = CollapsibleSection(self.tr("Image Reembedding (Optional)"))
        self._reembedding_layout = QFormLayout()
        style_form(self._reembedding_layout)
        reembedding_widget = QWidget()
        reembedding_widget.setLayout(self._reembedding_layout)

        self._reembedding_hint = add_hint(self._reembedding_layout, self._reembedding_hint_text())
        self.reembedding_backend_combo = QComboBox()
        self.reembedding_backend_combo.addItem("Gemini", ImageBackend.GEMINI.value)
        self.reembedding_backend_combo.addItem("OpenAI", ImageBackend.OPENAI.value)
        self.reembedding_backend_combo.addItem("Qwen", ImageBackend.QWEN.value)
        self.reembedding_backend_combo.setToolTip(self.tr("Backend service for image text replacement"))
        self._reembedding_layout.addRow(self.tr("Backend:"), self.reembedding_backend_combo)

        self.reembedding_endpoint = self._create_endpoint_dropdown()
        self._reembedding_layout.addRow(self.tr("Endpoint Profile:"), self.reembedding_endpoint)

        self._reembedding_section.set_content(reembedding_widget)
        layout.addWidget(self._reembedding_section)

        # === Manga Translator Section ===
        self._manga_section = CollapsibleSection(self.tr("Manga Translator (Optional)"))
        self._manga_layout = QFormLayout()
        style_form(self._manga_layout)
        manga_widget = QWidget()
        manga_widget.setLayout(self._manga_layout)

        self._manga_hint = add_hint(self._manga_layout, self._manga_hint_text())
        self.manga_endpoint = self._create_endpoint_dropdown()
        self._manga_layout.addRow(self.tr("Endpoint Profile:"), self.manga_endpoint)

        self.manga_pages_per_call_spin = QSpinBox()
        self.manga_pages_per_call_spin.setRange(1, 50)
        self.manga_pages_per_call_spin.setValue(10)
        self.manga_pages_per_call_spin.setToolTip(self.tr("Number of manga pages to send per LLM call"))
        self._manga_layout.addRow(self.tr("Pages per Call:"), self.manga_pages_per_call_spin)

        self._manga_section.set_content(manga_widget)
        layout.addWidget(self._manga_section)

        layout.addStretch()

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)
        self._apply_tooltips()

    def changeEvent(self, event: QEvent) -> None:
        """Handle change events including language changes."""
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        """Retranslate all UI strings."""
        # Section titles
        self._language_section.toggle_button.setText(self.tr("Target Language"))
        self._extractor_section.toggle_button.setText(self.tr("Extractor (Term Extraction)"))
        self._summarizer_section.toggle_button.setText(self.tr("Summarizer (Term Description)"))
        self._glossary_section.toggle_button.setText(self.tr("Glossary Translation"))
        self._translator_section.toggle_button.setText(self.tr("Translator (Main Translation)"))
        self._translator_batch_section.toggle_button.setText(self.tr("Translator Batch (Optional)"))
        self._review_section.toggle_button.setText(self.tr("Review (Optional)"))
        self._ocr_section.toggle_button.setText(self.tr("OCR (Optional)"))
        self._reembedding_section.toggle_button.setText(self.tr("Image Reembedding (Optional)"))
        self._manga_section.toggle_button.setText(self.tr("Manga Translator (Optional)"))

        self._language_hint.setText(self._language_hint_text())
        self._extractor_hint.setText(self._extractor_hint_text())
        self._summarizer_hint.setText(self._summarizer_hint_text())
        self._glossary_hint.setText(self._glossary_hint_text())
        self._translator_hint.setText(self._translator_hint_text())
        self._translator_batch_hint.setText(self._translator_batch_hint_text())
        self._review_hint.setText(self._review_hint_text())
        self._ocr_hint.setText(self._ocr_hint_text())
        self._reembedding_hint.setText(self._reembedding_hint_text())
        self._manga_hint.setText(self._manga_hint_text())

        # Helper to safely update a form label
        def _set_label(layout, widget, text):
            label = layout.labelForField(widget)
            if label:
                label.setText(text)

        # Target Language form labels
        _set_label(self._language_layout, self.language_dropdown, self.tr("Target Language*:"))

        # Extractor form labels
        _set_label(self._extractor_layout, self.extractor_endpoint, self.tr("Endpoint Profile:"))
        _set_label(self._extractor_layout, self.max_gleaning_spin, self.tr("Max Gleaning:"))
        _set_label(self._extractor_layout, self.max_term_name_spin, self.tr("Max Term Name Length:"))

        # Summarizer form labels
        _set_label(self._summarizer_layout, self.summarizer_endpoint, self.tr("Endpoint Profile:"))

        # Glossary form labels
        _set_label(self._glossary_layout, self.glossary_endpoint, self.tr("Endpoint Profile:"))

        # Translator form labels
        _set_label(self._translator_layout, self.translator_endpoint, self.tr("Endpoint Profile:"))
        _set_label(self._translator_layout, self.enable_polish_check, self.tr("Enable Polish:"))
        _set_label(self._translator_layout, self.chunks_per_call_spin, self.tr("Chunks per Call:"))
        _set_label(self._translator_layout, self.chunk_size_spin, self.tr("Chunk Size:"))

        # Translator batch form labels
        _set_label(self._translator_batch_layout, self.translator_batch_provider, self.tr("Provider:"))
        _set_label(self._translator_batch_layout, self.translator_batch_api_key, self.tr("API Key:"))
        _set_label(self._translator_batch_layout, self.translator_batch_model, self.tr("Model:"))
        _set_label(self._translator_batch_layout, self.translator_batch_size_spin, self.tr("Batch Size:"))
        _set_label(self._translator_batch_layout, self.translator_batch_thinking_mode, self.tr("Thinking Mode:"))
        self.translator_batch_provider.setItemText(0, self.tr("Disabled"))
        self.translator_batch_provider.setItemText(1, self.tr("Gemini AI Studio"))
        self.translator_batch_thinking_mode.setItemText(0, self.tr("Auto"))
        self.translator_batch_thinking_mode.setItemText(1, self.tr("Off"))
        self.translator_batch_thinking_mode.setItemText(2, self.tr("Low"))
        self.translator_batch_thinking_mode.setItemText(3, self.tr("Medium"))
        self.translator_batch_thinking_mode.setItemText(4, self.tr("High"))

        # Review form labels
        _set_label(self._review_layout, self.review_endpoint, self.tr("Endpoint Profile:"))

        # OCR form labels
        _set_label(self._ocr_layout, self.ocr_endpoint, self.tr("Endpoint Profile:"))
        _set_label(self._ocr_layout, self.ocr_dpi_spin, self.tr("OCR DPI:"))
        _set_label(self._ocr_layout, self.strip_artifacts_check, self.tr("Strip Artifacts:"))
        _set_label(self._ocr_layout, self.enable_reembedding_check, self.tr("Enable Image Re-embedding:"))

        # Reembedding form labels
        _set_label(self._reembedding_layout, self.reembedding_backend_combo, self.tr("Backend:"))
        _set_label(self._reembedding_layout, self.reembedding_endpoint, self.tr("Endpoint Profile:"))

        # Manga form labels
        _set_label(self._manga_layout, self.manga_endpoint, self.tr("Endpoint Profile:"))
        _set_label(self._manga_layout, self.manga_pages_per_call_spin, self.tr("Pages per Call:"))

        self._apply_tooltips()

    def _language_hint_text(self) -> str:
        return self.tr("Output language used by glossary translation and final translation.")

    def _extractor_hint_text(self) -> str:
        return self.tr(
            "Extracts candidate terms from imported text. "
            "We strongly recommend using the cheapest model with input caching (e.g. DeepSeek) "
            "as this step processes large volumes of text repeatedly."
        )

    def _summarizer_hint_text(self) -> str:
        return self.tr(
            "Builds term descriptions from accumulated context. Earlier imports influence later summaries. "
            "We strongly recommend using the cheapest model with input caching (e.g. DeepSeek) "
            "as this step re-reads all accumulated context for each term."
        )

    def _glossary_hint_text(self) -> str:
        return self.tr("Translates extracted terms into the target language before main translation.")

    def _translator_hint_text(self) -> str:
        return self.tr(
            "Main document translation. Uses glossary plus accumulated context from earlier imported content."
        )

    def _translator_batch_hint_text(self) -> str:
        return self.tr(
            "Optional Gemini AI Studio config for async batch translation tasks. "
            "Initial translation and polish calls are sent through provider batch jobs."
        )

    def _review_hint_text(self) -> str:
        return self.tr("Optional LLM review pass for glossary quality before translation.")

    def _ocr_hint_text(self) -> str:
        return self.tr("For image-based documents. Run OCR before glossary build.")

    def _reembedding_hint_text(self) -> str:
        return self.tr("Optional: write translated text back into images.")

    def _manga_hint_text(self) -> str:
        return self.tr("Optional manga-specific translation path for image pages.")

    def _set_field_tooltip(self, layout: QFormLayout, widget: QWidget, text: str) -> None:
        """Apply a tooltip to both field widget and its label."""
        widget.setToolTip(text)
        label = layout.labelForField(widget)
        if label:
            label.setToolTip(text)

    def _apply_tooltips(self) -> None:
        """Apply hover explanations for all profile config options."""
        self._set_field_tooltip(
            self._language_layout,
            self.language_dropdown,
            self.tr("Target language used for glossary and final translation output."),
        )

        self._set_field_tooltip(
            self._extractor_layout,
            self.extractor_endpoint,
            self.tr("Endpoint profile used for term extraction."),
        )
        self._set_field_tooltip(
            self._extractor_layout,
            self.max_gleaning_spin,
            self.tr("Number of extraction passes to find more terms."),
        )
        self._set_field_tooltip(
            self._extractor_layout,
            self.max_term_name_spin,
            self.tr("Maximum character length for extracted term names."),
        )

        self._set_field_tooltip(
            self._summarizer_layout,
            self.summarizer_endpoint,
            self.tr("Endpoint profile used to build term descriptions from context."),
        )

        self._set_field_tooltip(
            self._glossary_layout,
            self.glossary_endpoint,
            self.tr("Endpoint profile used to translate glossary terms."),
        )

        self._set_field_tooltip(
            self._translator_layout,
            self.translator_endpoint,
            self.tr("Endpoint profile used for main text translation."),
        )
        self._set_field_tooltip(
            self._translator_layout,
            self.enable_polish_check,
            self.tr("Run an additional polishing pass after translation."),
        )
        self._set_field_tooltip(
            self._translator_layout,
            self.chunks_per_call_spin,
            self.tr("Number of text chunks sent per translation request."),
        )
        self._set_field_tooltip(
            self._translator_layout,
            self.chunk_size_spin,
            self.tr("Maximum token size for each translation chunk."),
        )

        self._set_field_tooltip(
            self._translator_batch_layout,
            self.translator_batch_provider,
            self.tr("Batch provider used for async translation/polish tasks. Leave disabled to turn off batch tasks."),
        )
        self._set_field_tooltip(
            self._translator_batch_layout,
            self.translator_batch_api_key,
            self.tr("API key used for provider batch submission."),
        )
        self._set_field_tooltip(
            self._translator_batch_layout,
            self.translator_batch_model,
            self.tr("Model used for async translation and polish batch jobs."),
        )
        self._set_field_tooltip(
            self._translator_batch_layout,
            self.translator_batch_size_spin,
            self.tr("Maximum number of requests submitted per provider batch job."),
        )
        self._set_field_tooltip(
            self._translator_batch_layout,
            self.translator_batch_thinking_mode,
            self.tr("Thinking policy for Gemini batch jobs."),
        )

        self._set_field_tooltip(
            self._review_layout,
            self.review_endpoint,
            self.tr("Endpoint profile used for optional glossary review."),
        )

        self._set_field_tooltip(
            self._ocr_layout,
            self.ocr_endpoint,
            self.tr("Endpoint profile used for OCR on image-based content."),
        )
        self._set_field_tooltip(
            self._ocr_layout,
            self.ocr_dpi_spin,
            self.tr("DPI used when compressing images before OCR."),
        )
        self._set_field_tooltip(
            self._ocr_layout,
            self.strip_artifacts_check,
            self.tr("Remove common LLM artifact patterns from OCR text."),
        )
        self._set_field_tooltip(
            self._ocr_layout,
            self.enable_reembedding_check,
            self.tr("Enable writing translated text back into images."),
        )

        self._set_field_tooltip(
            self._reembedding_layout,
            self.reembedding_backend_combo,
            self.tr("Backend service used for image text replacement."),
        )
        self._set_field_tooltip(
            self._reembedding_layout,
            self.reembedding_endpoint,
            self.tr("Endpoint profile used by the image reembedding backend."),
        )

        self._set_field_tooltip(
            self._manga_layout,
            self.manga_endpoint,
            self.tr("Endpoint profile used for manga page translation."),
        )
        self._set_field_tooltip(
            self._manga_layout,
            self.manga_pages_per_call_spin,
            self.tr("Number of manga pages sent per translation request."),
        )

    def _set_endpoint_dropdown(self, combo: QComboBox, profile_ref: str | None) -> None:
        """Set endpoint dropdown by profile reference (profile ID)."""
        if not profile_ref:
            combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            if combo.itemData(i) == profile_ref:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)

    def _get_endpoint_name(self, combo: QComboBox) -> str | None:
        """Get endpoint profile reference (stable profile ID) from dropdown."""
        data = combo.currentData()
        return str(data) if data is not None else None

    def get_config(self) -> dict:
        """
        Get configuration from form fields.

        Returns:
            Configuration dictionary
        """
        config: dict = {
            "translation_target_language": self.language_dropdown.get_value(),
        }

        # Extractor config
        extractor_endpoint = self._get_endpoint_name(self.extractor_endpoint)
        if extractor_endpoint:
            config["extractor_config"] = {
                "endpoint_profile": extractor_endpoint,
                "max_gleaning": self.max_gleaning_spin.value(),
                "max_term_name_length": self.max_term_name_spin.value(),
            }

        # Summarizer config
        # NOTE: "summarizor_config" is a legacy misspelling used throughout the codebase
        summarizer_endpoint = self._get_endpoint_name(self.summarizer_endpoint)
        if summarizer_endpoint:
            config["summarizor_config"] = {
                "endpoint_profile": summarizer_endpoint,
            }

        # Glossary config
        glossary_endpoint = self._get_endpoint_name(self.glossary_endpoint)
        if glossary_endpoint:
            config["glossary_config"] = {
                "endpoint_profile": glossary_endpoint,
            }

        # Translator config
        translator_endpoint = self._get_endpoint_name(self.translator_endpoint)
        if translator_endpoint:
            config["translator_config"] = {
                "endpoint_profile": translator_endpoint,
                "enable_polish": self.enable_polish_check.isChecked(),
                "num_of_chunks_per_llm_call": self.chunks_per_call_spin.value(),
                "chunk_size": self.chunk_size_spin.value(),
            }

        translator_batch_provider = str(self.translator_batch_provider.currentData() or "")
        if translator_batch_provider:
            config["translator_batch_config"] = {
                "provider": translator_batch_provider,
                "api_key": self.translator_batch_api_key.text().strip(),
                "model": self.translator_batch_model.text().strip(),
                "batch_size": self.translator_batch_size_spin.value(),
                "thinking_mode": str(self.translator_batch_thinking_mode.currentData() or "auto"),
            }

        # Review config
        review_endpoint = self._get_endpoint_name(self.review_endpoint)
        if review_endpoint:
            config["review_config"] = {
                "endpoint_profile": review_endpoint,
            }

        # OCR config
        ocr_endpoint = self._get_endpoint_name(self.ocr_endpoint)
        if ocr_endpoint:
            config["ocr_config"] = {
                "endpoint_profile": ocr_endpoint,
                "ocr_dpi": self.ocr_dpi_spin.value(),
                "strip_llm_artifacts": self.strip_artifacts_check.isChecked(),
                "enable_image_reembedding": self.enable_reembedding_check.isChecked(),
            }

        # Image reembedding config - save when enabled OR endpoint selected (preserves pre-config)
        reembedding_endpoint = self._get_endpoint_name(self.reembedding_endpoint)
        if self.enable_reembedding_check.isChecked() or reembedding_endpoint:
            config["image_reembedding_config"] = {
                "endpoint_profile": reembedding_endpoint,
                "backend": self.reembedding_backend_combo.currentData(),
            }

        # Manga translator config
        manga_endpoint = self._get_endpoint_name(self.manga_endpoint)
        if manga_endpoint:
            config["manga_translator_config"] = {
                "endpoint_profile": manga_endpoint,
                "pages_per_call": self.manga_pages_per_call_spin.value(),
            }

        return config

    def set_config(self, config: dict) -> None:
        """
        Populate form fields from configuration dictionary.

        Args:
            config: Configuration dictionary
        """
        # Target language
        target_language = config.get("translation_target_language", "")
        if target_language:
            self.language_dropdown.set_value(target_language)

        # Extractor config
        extractor = config.get("extractor_config", {})
        if extractor:
            self._set_endpoint_dropdown(self.extractor_endpoint, extractor.get("endpoint_profile"))
            self.max_gleaning_spin.setValue(extractor.get("max_gleaning", 3))
            self.max_term_name_spin.setValue(extractor.get("max_term_name_length", 200))

        # Summarizer config
        # NOTE: "summarizor_config" is a legacy misspelling used throughout the codebase
        summarizer = config.get("summarizor_config", {})
        if summarizer:
            self._set_endpoint_dropdown(self.summarizer_endpoint, summarizer.get("endpoint_profile"))

        # Glossary config
        glossary = config.get("glossary_config", {})
        if glossary:
            self._set_endpoint_dropdown(self.glossary_endpoint, glossary.get("endpoint_profile"))

        # Translator config
        translator = config.get("translator_config", {})
        if translator:
            self._set_endpoint_dropdown(self.translator_endpoint, translator.get("endpoint_profile"))
            self.enable_polish_check.setChecked(translator.get("enable_polish", True))
            self.chunks_per_call_spin.setValue(translator.get("num_of_chunks_per_llm_call", 5))
            self.chunk_size_spin.setValue(translator.get("chunk_size", 1000))

        translator_batch = config.get("translator_batch_config", {})
        if isinstance(translator_batch, dict) and translator_batch:
            provider_value = str(translator_batch.get("provider") or "")
            provider_index = 0
            for i in range(self.translator_batch_provider.count()):
                if str(self.translator_batch_provider.itemData(i) or "") == provider_value:
                    provider_index = i
                    break
            self.translator_batch_provider.setCurrentIndex(provider_index)

            self.translator_batch_api_key.setText(str(translator_batch.get("api_key") or ""))
            self.translator_batch_model.setText(str(translator_batch.get("model") or ""))
            self.translator_batch_size_spin.setValue(int(translator_batch.get("batch_size", 500)))

            thinking_value = str(translator_batch.get("thinking_mode") or "auto")
            for i in range(self.translator_batch_thinking_mode.count()):
                if str(self.translator_batch_thinking_mode.itemData(i) or "") == thinking_value:
                    self.translator_batch_thinking_mode.setCurrentIndex(i)
                    break

        # Review config
        review = config.get("review_config", {})
        if review:
            self._set_endpoint_dropdown(self.review_endpoint, review.get("endpoint_profile"))

        # OCR config
        ocr = config.get("ocr_config", {})
        if ocr:
            self._set_endpoint_dropdown(self.ocr_endpoint, ocr.get("endpoint_profile"))
            self.ocr_dpi_spin.setValue(ocr.get("ocr_dpi", 150))
            self.strip_artifacts_check.setChecked(ocr.get("strip_llm_artifacts", True))
            self.enable_reembedding_check.setChecked(ocr.get("enable_image_reembedding", False))

        # Image reembedding config
        reembedding = config.get("image_reembedding_config", {})
        if reembedding:
            self._set_endpoint_dropdown(self.reembedding_endpoint, reembedding.get("endpoint_profile"))
            # Set backend dropdown by value
            backend_value = reembedding.get("backend", ImageBackend.GEMINI.value)
            for i in range(self.reembedding_backend_combo.count()):
                if self.reembedding_backend_combo.itemData(i) == backend_value:
                    self.reembedding_backend_combo.setCurrentIndex(i)
                    break

        # Manga translator config
        manga = config.get("manga_translator_config", {})
        if manga:
            self._set_endpoint_dropdown(self.manga_endpoint, manga.get("endpoint_profile"))
            self.manga_pages_per_call_spin.setValue(manga.get("pages_per_call", 10))

    def validate(self) -> str | None:
        """
        Validate the configuration.

        Returns:
            Error message if invalid, None if valid
        """
        if not self.language_dropdown.get_value():
            return self.tr("Target language is required.")

        translator_batch_provider = str(self.translator_batch_provider.currentData() or "")
        if translator_batch_provider:
            if not self.translator_batch_api_key.text().strip():
                return self.tr("Translator batch API key is required when provider is enabled.")
            if not self.translator_batch_model.text().strip():
                return self.tr("Translator batch model is required when provider is enabled.")

        # Validate image reembedding requires endpoint when enabled
        if self.enable_reembedding_check.isChecked() and not self._get_endpoint_name(self.reembedding_endpoint):
            return self.tr("Image reembedding is enabled but no endpoint profile is selected.")

        return None
