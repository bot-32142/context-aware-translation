"""Views for the application."""

from context_aware_translation.ui.views.book_workspace import BookWorkspace
from context_aware_translation.ui.views.config_profile_view import ConfigProfileView
from context_aware_translation.ui.views.endpoint_profile_view import EndpointProfileView
from context_aware_translation.ui.views.export_view import ExportView
from context_aware_translation.ui.views.glossary_view import GlossaryView
from context_aware_translation.ui.views.import_view import ImportView
from context_aware_translation.ui.views.library_view import LibraryView
from context_aware_translation.ui.views.manga_review_widget import MangaReviewWidget
from context_aware_translation.ui.views.ocr_review_view import OCRReviewView
from context_aware_translation.ui.views.profile_view import ProfileView
from context_aware_translation.ui.views.reembedding_view import ReembeddingView
from context_aware_translation.ui.views.translation_view import TranslationView

__all__ = [
    "BookWorkspace",
    "ConfigProfileView",
    "EndpointProfileView",
    "ExportView",
    "GlossaryView",
    "ImportView",
    "LibraryView",
    "MangaReviewWidget",
    "OCRReviewView",
    "ProfileView",
    "ReembeddingView",
    "TranslationView",
]
