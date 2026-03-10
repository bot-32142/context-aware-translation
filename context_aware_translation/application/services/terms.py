from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
    NavigationTargetKind,
    SurfaceStatus,
)
from context_aware_translation.application.contracts.terms import (
    BuildTermsRequest,
    BulkUpdateTermsRequest,
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
from context_aware_translation.application.errors import (
    ApplicationErrorCode,
    ApplicationErrorPayload,
    BlockedOperationError,
)
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    blocker_code_for_decision_code,
    make_blocker,
    make_document_ref,
)
from context_aware_translation.glossary_io import import_glossary
from context_aware_translation.storage.book_db import TermRecord
from context_aware_translation.storage.context_tree_db import ContextTreeDB
from context_aware_translation.workflow.tasks.claims import ClaimMode, ResourceClaim
from context_aware_translation.workflow.tasks.models import TaskAction

if TYPE_CHECKING:
    from context_aware_translation.workflow.tasks.models import Decision


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

    def bulk_update_terms(self, request: BulkUpdateTermsRequest) -> TermsTableState: ...


class DefaultTermsService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_project_terms(self, project_id: str) -> TermsTableState:
        return self._build_terms_table(project_id, document_id=None)

    def get_document_terms(self, project_id: str, document_id: int) -> TermsTableState:
        return self._build_terms_table(project_id, document_id=document_id)

    def update_term(self, request: UpdateTermRequest) -> TermsTableState:
        blocker = self._glossary_mutation_blocker(request.scope.project.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.scope.project.project_id)
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
        self._runtime.invalidate_terms(
            request.scope.project.project_id,
            request.scope.document.document_id if request.scope.document is not None else None,
        )
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
        blocker = self._glossary_mutation_blocker(request.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.project_id)

        with self._runtime.open_book_db(request.project_id) as dbx:
            chunk_ids = (
                {chunk.chunk_id for chunk in dbx.term_repo.list_chunks(document_id=request.document_id)}
                if request.document_id is not None
                else None
            )
            rare_keys = self._get_rare_term_keys(dbx.term_repo.list_term_records(), chunk_ids=chunk_ids)
            if not rare_keys:
                return (
                    self.get_document_terms(request.project_id, request.document_id)
                    if request.document_id
                    else self.get_project_terms(request.project_id)
                )
            dbx.term_repo.update_terms_bulk(rare_keys, ignored=True, is_reviewed=True)
        self._runtime.invalidate_terms(request.project_id, request.document_id)
        return (
            self.get_document_terms(request.project_id, request.document_id)
            if request.document_id
            else self.get_project_terms(request.project_id)
        )

    def import_terms(self, request: ImportTermsRequest) -> TermsTableState:
        blocker = self._glossary_mutation_blocker(request.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.project_id)
        with self._runtime.open_book_db(request.project_id) as dbx:
            context_tree_db = ContextTreeDB(self._runtime.book_manager.get_book_context_tree_path(request.project_id))
            try:
                import_glossary(dbx.db, context_tree_db, Path(request.input_path))
            finally:
                context_tree_db.close()
        self._runtime.invalidate_terms(request.project_id)
        return self.get_project_terms(request.project_id)

    def export_terms(self, request: ExportTermsRequest) -> AcceptedCommand:
        params: dict[str, object] = {"output_path": request.output_path}
        if request.document_id is not None:
            params["document_ids"] = [request.document_id]
        return self._runtime.submit_task("glossary_export", request.project_id, **params)

    def bulk_update_terms(self, request: BulkUpdateTermsRequest) -> TermsTableState:
        blocker = self._glossary_mutation_blocker(request.scope.project.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.scope.project.project_id)
        if not request.term_keys:
            return (
                self.get_document_terms(request.scope.project.project_id, request.scope.document.document_id)
                if request.scope.kind is TermsScopeKind.DOCUMENT and request.scope.document is not None
                else self.get_project_terms(request.scope.project.project_id)
            )
        with self._runtime.open_book_db(request.scope.project.project_id) as dbx:
            if request.delete:
                dbx.term_repo.delete_terms(request.term_keys)
            else:
                dbx.term_repo.update_terms_bulk(
                    request.term_keys,
                    ignored=request.ignored,
                    is_reviewed=request.reviewed,
                )
        self._runtime.invalidate_terms(
            request.scope.project.project_id,
            request.scope.document.document_id if request.scope.document is not None else None,
        )
        if request.scope.kind is TermsScopeKind.DOCUMENT and request.scope.document is not None:
            return self.get_document_terms(request.scope.project.project_id, request.scope.document.document_id)
        return self.get_project_terms(request.scope.project.project_id)

    def _build_terms_table(self, project_id: str, document_id: int | None) -> TermsTableState:
        project = self._runtime.get_project_ref(project_id)
        with self._runtime.open_book_db(project_id) as dbx:
            chunk_ids = (
                {chunk.chunk_id for chunk in dbx.term_repo.list_chunks(document_id=document_id)}
                if document_id is not None
                else None
            )
            rows = []
            filtered_records = []
            for record in dbx.term_repo.list_term_records():
                if chunk_ids is not None:
                    occurrence_chunk_ids = {int(key) for key in record.occurrence if str(key).isdigit()}
                    if not occurrence_chunk_ids.intersection(chunk_ids):
                        continue
                filtered_records.append(record)
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
        toolbar = self._build_toolbar_state(
            project_id,
            document_id=document_id,
            has_rows=bool(rows),
            term_records=filtered_records,
            chunk_ids=chunk_ids,
        )
        return TermsTableState(
            scope=scope,
            toolbar=toolbar,
            rows=rows,
            status=SurfaceStatus.READY,
        )

    def _build_toolbar_state(
        self,
        project_id: str,
        *,
        document_id: int | None,
        has_rows: bool,
        term_records: list[TermRecord],
        chunk_ids: set[int] | None,
    ) -> TermsToolbarState:
        build_allowed = False
        build_blocker = None
        if document_id is not None:
            build_allowed, build_blocker = self._decision_to_action_state(
                project_id,
                self._runtime.task_engine.preflight(
                    "glossary_extraction",
                    project_id,
                    {"document_ids": [document_id]},
                    TaskAction.RUN,
                ),
                target_kind=NavigationTargetKind.DOCUMENT_TERMS,
                document_id=document_id,
            )

        translate_allowed, translate_blocker = self._decision_to_action_state(
            project_id,
            self._runtime.task_engine.preflight(
                "glossary_translation",
                project_id,
                {"document_ids": [document_id]} if document_id is not None else {},
                TaskAction.RUN,
            ),
        )
        review_allowed, review_blocker = self._decision_to_action_state(
            project_id,
            self._runtime.task_engine.preflight(
                "glossary_review",
                project_id,
                {"document_ids": [document_id]} if document_id is not None else {},
                TaskAction.RUN,
            ),
        )
        export_allowed, export_blocker = self._decision_to_action_state(
            project_id,
            self._runtime.task_engine.preflight(
                "glossary_export",
                project_id,
                {
                    "output_path": "__terms_export__.json",
                    **({"document_ids": [document_id]} if document_id is not None else {}),
                },
                TaskAction.RUN,
            ),
        )

        mutation_blocker = self._glossary_mutation_blocker(project_id)
        has_rare_terms = bool(self._get_rare_term_keys(term_records, chunk_ids=chunk_ids))
        filter_noise_allowed = mutation_blocker is None and has_rare_terms
        filter_noise_blocker = None
        if mutation_blocker is not None:
            filter_noise_blocker = mutation_blocker
        elif not has_rare_terms:
            filter_noise_blocker = make_blocker(
                BlockerCode.NOTHING_TO_DO,
                "No terms matched the rare-term criteria.",
                target_kind=NavigationTargetKind.TERMS if document_id is None else NavigationTargetKind.DOCUMENT_TERMS,
                project_id=project_id,
                document_id=document_id,
            )

        import_allowed = mutation_blocker is None
        import_blocker = mutation_blocker

        return TermsToolbarState(
            can_build=build_allowed,
            can_translate_pending=translate_allowed,
            can_review=review_allowed,
            can_filter_noise=filter_noise_allowed,
            can_import=import_allowed,
            can_export=export_allowed and has_rows,
            build_blocker=build_blocker,
            translate_pending_blocker=translate_blocker,
            review_blocker=review_blocker,
            filter_noise_blocker=filter_noise_blocker,
            import_blocker=import_blocker,
            export_blocker=(
                export_blocker
                if export_blocker is not None
                else (
                    make_blocker(
                        BlockerCode.NOTHING_TO_DO,
                        "No terms found in glossary. Cannot export empty glossary.",
                        target_kind=NavigationTargetKind.TERMS
                        if document_id is None
                        else NavigationTargetKind.DOCUMENT_TERMS,
                        project_id=project_id,
                        document_id=document_id,
                    )
                    if not has_rows
                    else None
                )
            ),
        )

    def _decision_to_action_state(
        self,
        project_id: str,
        decision: Decision,
        *,
        target_kind: NavigationTargetKind = NavigationTargetKind.TERMS,
        document_id: int | None = None,
    ) -> tuple[bool, BlockerInfo | None]:
        if decision.allowed:
            return True, None
        return False, make_blocker(
            blocker_code_for_decision_code(decision.code or ""),
            decision.reason or "Operation is blocked.",
            target_kind=target_kind,
            project_id=project_id,
            document_id=document_id,
        )

    def _glossary_mutation_blocker(self, project_id: str) -> BlockerInfo | None:
        wanted = frozenset({ResourceClaim("glossary_state", project_id, "*", ClaimMode.WRITE_EXCLUSIVE)})
        if self._runtime.task_engine.has_active_claims(project_id, wanted):
            return make_blocker(
                BlockerCode.ALREADY_RUNNING_ELSEWHERE,
                "Another terms task is already running for this project.",
                target_kind=NavigationTargetKind.QUEUE,
                project_id=project_id,
            )
        return None

    def _raise_blocked_blocker(self, blocker: BlockerInfo, **details: str | int | float | bool | None) -> None:
        raise BlockedOperationError(
            ApplicationErrorPayload(
                code=ApplicationErrorCode.BLOCKED,
                message=blocker.message,
                details={"decision_code": blocker.code.value, **details},
            )
        )

    def _get_rare_term_keys(self, term_records: list[TermRecord], *, chunk_ids: set[int] | None) -> list[str]:
        rare_keys: list[str] = []
        for record in term_records:
            if record.ignored or record.is_reviewed:
                continue
            if chunk_ids is not None:
                occurrence_chunk_ids = {int(key) for key in (record.occurrence or {}) if str(key).isdigit()}
                if not occurrence_chunk_ids.intersection(chunk_ids):
                    continue
            total_occurrences = sum((record.occurrence or {}).values())
            if total_occurrences <= 1:
                rare_keys.append(record.key)
                continue
            chunk_desc_count = sum(1 for key in (record.descriptions or {}) if str(key).lstrip("-").isdigit())
            if chunk_desc_count <= 1:
                rare_keys.append(record.key)
        return rare_keys
