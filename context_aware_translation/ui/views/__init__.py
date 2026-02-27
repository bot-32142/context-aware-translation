"""Views for the application."""

from .book_workspace import BookWorkspace
from .config_profile_view import ConfigProfileView
from .endpoint_profile_view import EndpointProfileView
from .export_view import ExportView
from .glossary_view import GlossaryView
from .import_view import ImportView
from .library_view import LibraryView
from .manga_review_widget import MangaReviewWidget
from .ocr_review_view import OCRReviewView
from .profile_view import ProfileView
from .reembedding_view import ReembeddingView
from .translation_view import TranslationView

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
