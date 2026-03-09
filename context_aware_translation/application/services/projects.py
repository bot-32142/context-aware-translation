from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.projects import (
    CreateProjectRequest,
    ProjectsScreenState,
    ProjectSummary,
    UpdateProjectRequest,
)
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    build_project_summary,
    raise_application_error,
)
from context_aware_translation.storage.book import BookStatus


class ProjectsService(Protocol):
    def list_projects(self) -> ProjectsScreenState: ...

    def get_project(self, project_id: str) -> ProjectSummary: ...

    def create_project(self, request: CreateProjectRequest) -> ProjectSummary: ...

    def update_project(self, request: UpdateProjectRequest) -> ProjectSummary: ...

    def delete_project(self, project_id: str, *, permanent: bool = True) -> None: ...


class DefaultProjectsService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def list_projects(self) -> ProjectsScreenState:
        books = self._runtime.book_manager.list_books(status=BookStatus.ACTIVE)
        return ProjectsScreenState(items=[build_project_summary(self._runtime.book_manager, book) for book in books])

    def get_project(self, project_id: str) -> ProjectSummary:
        book = self._runtime.get_book(project_id)
        return build_project_summary(self._runtime.book_manager, book)

    def create_project(self, request: CreateProjectRequest) -> ProjectSummary:
        try:
            book = self._runtime.book_manager.create_book(request.name)
        except ValueError as exc:
            raise_application_error(ApplicationErrorCode.PRECONDITION, str(exc), project_name=request.name)
        if request.target_language:
            self.update_project(UpdateProjectRequest(project_id=book.book_id, target_language=request.target_language))
            book = self._runtime.get_book(book.book_id)
        self._runtime.invalidate_projects()
        self._runtime.invalidate_setup(book.book_id)
        self._runtime.invalidate_workboard(book.book_id)
        return build_project_summary(self._runtime.book_manager, book)

    def update_project(self, request: UpdateProjectRequest) -> ProjectSummary:
        if request.name is not None:
            updated = self._runtime.book_manager.update_book(request.project_id, name=request.name)
            if updated is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Project not found: {request.project_id}")
        if request.target_language is not None:
            config = self._runtime.get_effective_config_payload(request.project_id)
            config["translation_target_language"] = request.target_language
            self._runtime.book_manager.set_book_custom_config(request.project_id, config)
        self._runtime.invalidate_projects()
        self._runtime.invalidate_setup(request.project_id)
        self._runtime.invalidate_workboard(request.project_id)
        return self.get_project(request.project_id)

    def delete_project(self, project_id: str, *, permanent: bool = True) -> None:
        deleted = self._runtime.book_manager.delete_book(project_id, permanent=permanent)
        if not deleted:
            raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Project not found: {project_id}")
        self._runtime.invalidate_projects()
