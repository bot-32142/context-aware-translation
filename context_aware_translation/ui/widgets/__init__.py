"""Reusable UI widgets for the application."""

from context_aware_translation.ui.widgets.collapsible_section import CollapsibleSection
from context_aware_translation.ui.widgets.config_editor import ConfigEditorWidget
from context_aware_translation.ui.widgets.image_viewer import ImageViewer
from context_aware_translation.ui.widgets.language_dropdown import LanguageDropdown
from context_aware_translation.ui.widgets.ocr_element_card import OCRElementCard
from context_aware_translation.ui.widgets.ocr_element_list import OCRElementList
from context_aware_translation.ui.widgets.progress_widget import ProgressWidget
from context_aware_translation.ui.widgets.task_activity_panel import TaskActivityPanel
from context_aware_translation.ui.widgets.task_status_card import TaskStatusCard, TaskStatusStrip

__all__ = [
    "CollapsibleSection",
    "ConfigEditorWidget",
    "ImageViewer",
    "LanguageDropdown",
    "OCRElementCard",
    "OCRElementList",
    "ProgressWidget",
    "TaskActivityPanel",
    "TaskStatusCard",
    "TaskStatusStrip",
]
