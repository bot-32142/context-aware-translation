"""New shell-oriented UI feature containers."""

from context_aware_translation.ui.features.app_setup_view import AppSetupView
from context_aware_translation.ui.features.project_setup_view import ProjectSetupView
from context_aware_translation.ui.features.project_shell_view import ProjectShellView
from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView
from context_aware_translation.ui.features.terms_view import TermsView
from context_aware_translation.ui.features.work_view import DocumentWorkspaceView, WorkView

__all__ = [
    "AppSetupView",
    "ProjectSetupView",
    "ProjectShellView",
    "WorkView",
    "DocumentWorkspaceView",
    "TermsView",
    "QueueDrawerView",
]
