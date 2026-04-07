from __future__ import annotations

import sqlite3
from typing import Protocol

from context_aware_translation.application.contracts.projects import (
    CreateProjectRequest,
    ProjectsScreenState,
    ProjectSummary,
    UpdateProjectRequest,
    WorkflowProfileOption,
)
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    build_project_summary,
    raise_application_error,
)
from context_aware_translation.storage.models.book import BookStatus
from context_aware_translation.ui.constants import (
    display_target_language_name,
    storage_target_language_name,
)


class ProjectsService(Protocol):
    def list_projects(self) -> ProjectsScreenState: ...

    def get_project(self, project_id: str) -> ProjectSummary: ...

    def list_workflow_profiles(self) -> list[WorkflowProfileOption]: ...

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

    def list_workflow_profiles(self) -> list[WorkflowProfileOption]:
        return [
            WorkflowProfileOption(
                profile_id=profile.profile_id,
                name=profile.name,
                target_language=display_target_language_name(
                    str(profile.config.get("translation_target_language") or "English")
                )
                or "English",
                is_default=profile.is_default,
            )
            for profile in self._runtime.book_manager.list_profiles()
        ]

    def create_project(self, request: CreateProjectRequest) -> ProjectSummary:
        requested_profile = None
        if request.workflow_profile_id is not None:
            requested_profile = self._runtime.book_manager.get_profile(request.workflow_profile_id)
            if requested_profile is None:
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND,
                    f"Workflow profile not found: {request.workflow_profile_id}",
                    workflow_profile_id=request.workflow_profile_id,
                )

        requested_target_language = storage_target_language_name(request.target_language)
        profile_for_defaults = requested_profile or self._runtime.get_default_profile()
        default_target_language = None
        if profile_for_defaults is not None:
            default_target_language = storage_target_language_name(
                str(profile_for_defaults.config.get("translation_target_language") or "")
            )

        try:
            if (
                requested_target_language
                and default_target_language is not None
                and requested_target_language != default_target_language
            ):
                custom_config = dict(profile_for_defaults.config)
                custom_config["translation_target_language"] = requested_target_language
                custom_config["_ui_source_profile_id"] = profile_for_defaults.profile_id
                book = self._runtime.book_manager.create_book(request.name, custom_config=custom_config)
            else:
                book = self._runtime.book_manager.create_book(request.name, profile_id=request.workflow_profile_id)
        except ValueError as exc:
            raise_application_error(ApplicationErrorCode.PRECONDITION, str(exc), project_name=request.name)
        except sqlite3.IntegrityError as exc:
            raise_application_error(
                ApplicationErrorCode.CONFLICT,
                "A project with that name already exists.",
                project_name=request.name,
                reason=str(exc),
            )
        if requested_target_language and profile_for_defaults is None:
            self.update_project(UpdateProjectRequest(project_id=book.book_id, target_language=request.target_language))
            book = self._runtime.get_book(book.book_id)
        self._runtime.invalidate_projects()
        self._runtime.invalidate_setup(book.book_id)
        self._runtime.invalidate_workboard(book.book_id)
        return build_project_summary(self._runtime.book_manager, book)

    def update_project(self, request: UpdateProjectRequest) -> ProjectSummary:
        if request.name is not None:
            try:
                updated = self._runtime.book_manager.update_book(request.project_id, name=request.name)
            except sqlite3.IntegrityError as exc:
                raise_application_error(
                    ApplicationErrorCode.CONFLICT,
                    "A project with that name already exists.",
                    project_id=request.project_id,
                    project_name=request.name,
                    reason=str(exc),
                )
            if updated is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Project not found: {request.project_id}")
        if request.target_language is not None:
            book = self._runtime.get_book(request.project_id)
            config = self._runtime.get_effective_config_payload(request.project_id)
            config["translation_target_language"] = storage_target_language_name(request.target_language) or request.target_language
            if book.profile_id is not None:
                config["_ui_source_profile_id"] = book.profile_id
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
        self._runtime.invalidate_setup(project_id)
        self._runtime.invalidate_workboard(project_id)
        self._runtime.invalidate_queue(project_id)
        self._runtime.invalidate_document(project_id)
        self._runtime.invalidate_terms(project_id)
