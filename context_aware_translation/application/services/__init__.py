"""Application service interfaces."""

from context_aware_translation.application.services.app_setup import AppSetupService
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.application.services.project_setup import ProjectSetupService
from context_aware_translation.application.services.projects import ProjectsService
from context_aware_translation.application.services.queue import QueueService
from context_aware_translation.application.services.terms import TermsService
from context_aware_translation.application.services.work import WorkService

__all__ = [
    "AppSetupService",
    "DocumentService",
    "ProjectSetupService",
    "ProjectsService",
    "QueueService",
    "TermsService",
    "WorkService",
]
