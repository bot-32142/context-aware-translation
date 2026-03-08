from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from context_aware_translation.application.runtime import ApplicationRuntime
from context_aware_translation.application.services.app_setup import AppSetupService, DefaultAppSetupService
from context_aware_translation.application.services.document import DefaultDocumentService, DocumentService
from context_aware_translation.application.services.project_setup import DefaultProjectSetupService, ProjectSetupService
from context_aware_translation.application.services.projects import DefaultProjectsService, ProjectsService
from context_aware_translation.application.services.queue import DefaultQueueService, QueueService
from context_aware_translation.application.services.terms import DefaultTermsService, TermsService
from context_aware_translation.application.services.work import DefaultWorkService, WorkService
from context_aware_translation.llm.token_tracker import TokenTracker
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.task_store import TaskStore
from context_aware_translation.workflow.task_runtime import build_task_engine


@dataclass(frozen=True)
class ApplicationServices:
    projects: ProjectsService
    app_setup: AppSetupService
    project_setup: ProjectSetupService
    work: WorkService
    terms: TermsService
    document: DocumentService
    queue: QueueService


@dataclass(frozen=True)
class ApplicationContext:
    runtime: ApplicationRuntime
    services: ApplicationServices

    def close(self) -> None:
        self.runtime.task_engine.stop_autorun()
        self.runtime.task_store.close()
        self.runtime.book_manager.close()


def build_application_context(
    *,
    library_root: Path | None = None,
    task_parent: Any | None = None,
) -> ApplicationContext:
    """Build the application-layer composition root.

    This is the only place the UI should need to request infrastructure-backed
    service instances from.
    """

    book_manager = BookManager(library_root)
    book_manager.seed_system_defaults()
    TokenTracker.initialize(book_manager.registry)

    task_store = TaskStore(book_manager.library_root / "task_store.db")
    task_engine, worker_deps = build_task_engine(
        book_manager=book_manager,
        task_store=task_store,
        parent=task_parent,
    )

    runtime = ApplicationRuntime(
        book_manager=book_manager,
        task_store=task_store,
        task_engine=task_engine,
        worker_deps=worker_deps,
    )
    services = ApplicationServices(
        projects=DefaultProjectsService(runtime),
        app_setup=DefaultAppSetupService(runtime),
        project_setup=DefaultProjectSetupService(runtime),
        work=DefaultWorkService(runtime),
        terms=DefaultTermsService(runtime),
        document=DefaultDocumentService(runtime),
        queue=DefaultQueueService(runtime),
    )
    return ApplicationContext(runtime=runtime, services=services)
