from __future__ import annotations

from pathlib import Path
from typing import Protocol

from context_aware_translation.application.contracts.common import AcceptedCommand, SurfaceStatus
from context_aware_translation.application.contracts.terms import (
    BuildTermsRequest,
    ExportTermsRequest,
    FilterNoiseRequest,
    ImportTermsRequest,
    ReviewTermsRequest,
    TermsScope,
    TermsScopeKind,
    TermsTableState,
    TermStatus,
    TermsToolbarState,
    TermTableRow,
    TranslatePendingTermsRequest,
    UpdateTermRequest,
)
from context_aware_translation.application.runtime import ApplicationRuntime, make_document_ref
from context_aware_translation.glossary_io import import_glossary
from context_aware_translation.storage.context_tree_db import ContextTreeDB


class TermsService(Protocol):
    def get_project_terms(self, project_id: str) -> TermsTableState: ...

    def get_document_terms(self, project_id: str, document_id: int) -> TermsTableState: ...

    def update_term(self, request: UpdateTermRequest) -> TermsTableState: ...

    def build_terms(self, request: BuildTermsRequest) -> AcceptedCommand: ...

    def translate_pending(self, request: TranslatePendingTermsRequest) -> AcceptedCommand: ...

    def review_terms(self, request: ReviewTermsRequest) -> AcceptedCommand: ...

    def filter_noise(self, request: FilterNoiseRequest) -> TermsTableState: ...

    def import_terms(self, request: ImportTermsRequest) -> TermsTableState: ...

    def export_terms(self, request: ExportTermsRequest) -> AcceptedCommand: ...


class DefaultTermsService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_project_terms(self, project_id: str) -> TermsTableState:
        return self._build_terms_table(project_id, document_id=None)

    def get_document_terms(self, project_id: str, document_id: int) -> TermsTableState:
        return self._build_terms_table(project_id, document_id=document_id)

    def update_term(self, request: UpdateTermRequest) -> TermsTableState:
        with self._runtime.open_book_db(request.scope.project.project_id) as dbx:
            records = dbx.term_repo.list_term_records()
            target_key = request.term_key or str(request.term_id)
            record = next((item for item in records if item.key == target_key), None)
            if record is not None:
                if request.translation is not None:
                    record.translated_name = request.translation
                if request.description is not None:
                    record.descriptions = {**record.descriptions, "manual": request.description}
                if request.ignored is not None:
                    record.ignored = request.ignored
                if request.reviewed is not None:
                    record.is_reviewed = request.reviewed
                dbx.term_repo.upsert_terms([record])
        if request.scope.kind is TermsScopeKind.DOCUMENT and request.scope.document is not None:
            return self.get_document_terms(request.scope.project.project_id, request.scope.document.document_id)
        return self.get_project_terms(request.scope.project.project_id)

    def build_terms(self, request: BuildTermsRequest) -> AcceptedCommand:
        params: dict[str, object] = {}
        if request.document_id is not None:
            params["document_ids"] = [request.document_id]
        if request.cutoff_document_id is not None:
            params["cutoff_doc_id"] = request.cutoff_document_id
        return self._runtime.submit_task("glossary_extraction", request.project_id, **params)

    def translate_pending(self, request: TranslatePendingTermsRequest) -> AcceptedCommand:
        params: dict[str, object] = {}
        if request.document_id is not None:
            params["document_ids"] = [request.document_id]
        return self._runtime.submit_task("glossary_translation", request.project_id, **params)

    def review_terms(self, request: ReviewTermsRequest) -> AcceptedCommand:
        params: dict[str, object] = {}
        if request.document_id is not None:
            params["document_ids"] = [request.document_id]
        return self._runtime.submit_task("glossary_review", request.project_id, **params)

    def filter_noise(self, request: FilterNoiseRequest) -> TermsTableState:
        # Preserve current backend behavior for now: filtering is still a local table operation.
        return self.get_document_terms(request.project_id, request.document_id) if request.document_id else self.get_project_terms(request.project_id)

    def import_terms(self, request: ImportTermsRequest) -> TermsTableState:
        with self._runtime.open_book_db(request.project_id) as dbx:
            context_tree_db = ContextTreeDB(self._runtime.book_manager.get_book_context_tree_path(request.project_id))
            try:
                import_glossary(dbx.db, context_tree_db, Path(request.input_path))
            finally:
                context_tree_db.close()
        return self.get_project_terms(request.project_id)

    def export_terms(self, request: ExportTermsRequest) -> AcceptedCommand:
        params: dict[str, object] = {"output_path": request.output_path}
        if request.document_id is not None:
            params["document_ids"] = [request.document_id]
        return self._runtime.submit_task("glossary_export", request.project_id, **params)

    def _build_terms_table(self, project_id: str, document_id: int | None) -> TermsTableState:
        project = self._runtime.get_project_ref(project_id)
        with self._runtime.open_book_db(project_id) as dbx:
            chunk_ids = {chunk.chunk_id for chunk in dbx.term_repo.list_chunks(document_id=document_id)} if document_id is not None else None
            rows = []
            for record in dbx.term_repo.list_term_records():
                if chunk_ids is not None:
                    occurrence_chunk_ids = {int(key) for key in record.occurrence if str(key).isdigit()}
                    if not occurrence_chunk_ids.intersection(chunk_ids):
                        continue
                rows.append(
                    TermTableRow(
                        term_id=int(record.key) if record.key.isdigit() else hash(record.key),
                        term_key=record.key,
                        term=record.key,
                        translation=record.translated_name,
                        description=next(iter(record.descriptions.values()), None),
                        occurrences=len(record.occurrence),
                        votes=record.votes,
                        ignored=record.ignored,
                        reviewed=record.is_reviewed,
                        status=(
                            TermStatus.IGNORED
                            if record.ignored
                            else TermStatus.NEEDS_TRANSLATION
                            if not record.translated_name
                            else TermStatus.NEEDS_REVIEW
                            if not record.is_reviewed
                            else TermStatus.READY
                        ),
                    )
                )
        scope = TermsScope(
            kind=TermsScopeKind.DOCUMENT if document_id is not None else TermsScopeKind.PROJECT,
            project=project,
            document=make_document_ref(document_id, f"Document {document_id}") if document_id is not None else None,
        )
        return TermsTableState(
            scope=scope,
            toolbar=TermsToolbarState(can_build=document_id is not None, can_translate_pending=True, can_review=True, can_filter_noise=True),
            rows=rows,
            status=SurfaceStatus.READY,
        )
