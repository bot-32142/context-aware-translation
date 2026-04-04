from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from context_aware_translation.adapters.files.glossary_io import import_glossary
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
    BulkUpdateTermsResult,
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
    UpdateTermRowsRequest,
    UpdateTermRowsResult,
    UpsertProjectTermRequest,
    UpsertProjectTermResult,
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
    raise_application_error,
)
from context_aware_translation.core.models import description_index, ordered_description_entries
from context_aware_translation.storage.schema.book_db import TermRecord, TermRowUpdate
from context_aware_translation.workflow.tasks.claims import ClaimMode, ResourceClaim
from context_aware_translation.workflow.tasks.models import TaskAction

if TYPE_CHECKING:
    from context_aware_translation.workflow.tasks.models import Decision


class TermsService(Protocol):
    def get_project_terms(self, project_id: str) -> TermsTableState: ...

    def get_document_terms(self, project_id: str, document_id: int) -> TermsTableState: ...

    def get_toolbar_state(
        self,
        project_id: str,
        *,
        document_id: int | None = None,
        rows: Sequence[TermTableRow] | None = None,
    ) -> TermsToolbarState: ...

    def update_term(self, request: UpdateTermRequest) -> TermsTableState: ...

    def update_term_rows(self, request: UpdateTermRowsRequest) -> UpdateTermRowsResult: ...

    def build_terms(self, request: BuildTermsRequest) -> AcceptedCommand: ...

    def translate_pending(self, request: TranslatePendingTermsRequest) -> AcceptedCommand: ...

    def review_terms(self, request: ReviewTermsRequest) -> AcceptedCommand: ...

    def filter_noise(self, request: FilterNoiseRequest) -> TermsTableState: ...

    def import_terms(self, request: ImportTermsRequest) -> TermsTableState: ...

    def upsert_project_term(self, request: UpsertProjectTermRequest) -> UpsertProjectTermResult: ...

    def export_terms(self, request: ExportTermsRequest) -> AcceptedCommand: ...

    def bulk_update_terms(self, request: BulkUpdateTermsRequest) -> BulkUpdateTermsResult: ...


class DefaultTermsService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_project_terms(self, project_id: str) -> TermsTableState:
        return self._build_terms_table(project_id, document_id=None)

    def get_document_terms(self, project_id: str, document_id: int) -> TermsTableState:
        return self._build_terms_table(project_id, document_id=document_id)

    def get_toolbar_state(
        self,
        project_id: str,
        *,
        document_id: int | None = None,
        rows: Sequence[TermTableRow] | None = None,
    ) -> TermsToolbarState:
        row_list = list(rows) if rows is not None else self._load_scope_rows(project_id, document_id=document_id)
        return self._build_toolbar_state(
            project_id,
            document_id=document_id,
            has_rows=bool(row_list),
            rows=row_list,
        )

    def update_term(self, request: UpdateTermRequest) -> TermsTableState:
        blocker = self._glossary_mutation_blocker(request.scope.project.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.scope.project.project_id)
        with self._runtime.open_book_db(request.scope.project.project_id) as dbx:
            records = dbx.term_repo.list_term_records()
            target_key = request.term_key or str(request.term_id)
            record = next((item for item in records if item.key == target_key), None)
            if record is None:
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND,
                    f"Term not found: {target_key}",
                    project_id=request.scope.project.project_id,
                    document_id=request.scope.document.document_id if request.scope.document is not None else None,
                    term_key=target_key,
                )
            if request.translation is not None:
                record.translated_name = request.translation
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

    def update_term_rows(self, request: UpdateTermRowsRequest) -> UpdateTermRowsResult:
        blocker = self._glossary_mutation_blocker(request.scope.project.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.scope.project.project_id)
        with self._runtime.open_book_db(request.scope.project.project_id) as dbx:
            updated_count = dbx.term_repo.update_term_rows(
                [
                    TermRowUpdate(
                        key=row.term_key,
                        translated_name=row.translation or "",
                        ignored=row.ignored,
                        is_reviewed=row.reviewed,
                    )
                    for row in request.rows
                ]
            )
        if updated_count:
            self._runtime.invalidate_terms(
                request.scope.project.project_id,
                request.scope.document.document_id if request.scope.document is not None else None,
            )
        return UpdateTermRowsResult(rows=request.rows)

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
            try:
                import_glossary(dbx.db, Path(request.input_path))
            except ValueError as exc:
                raise_application_error(
                    ApplicationErrorCode.VALIDATION,
                    str(exc),
                    project_id=request.project_id,
                    input_path=request.input_path,
                )
        self._runtime.invalidate_terms(request.project_id)
        return self.get_project_terms(request.project_id)

    def upsert_project_term(self, request: UpsertProjectTermRequest) -> UpsertProjectTermResult:
        blocker = self._glossary_mutation_blocker(request.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.project_id)

        term = request.term.strip()
        translation = request.translation.strip()
        if not term:
            raise_application_error(ApplicationErrorCode.VALIDATION, "Term is required.", project_id=request.project_id)
        if not translation:
            raise_application_error(
                ApplicationErrorCode.VALIDATION,
                "Translation is required.",
                project_id=request.project_id,
                term=term,
            )

        updated_existing = False
        with self._runtime.open_book_db(request.project_id) as dbx:
            existing = dbx.db.get_term(term)
            if existing is not None:
                updated_existing = True
                record = existing
                record.translated_name = translation
                record.ignored = False
                record.is_reviewed = True
                record.updated_at = time.time()
            else:
                record = TermRecord(
                    key=term,
                    descriptions={},
                    occurrence={},
                    votes=1,
                    total_api_calls=1,
                    term_type="other",
                    translated_name=translation,
                    ignored=False,
                    is_reviewed=True,
                )
            dbx.term_repo.upsert_terms([record])

        self._runtime.invalidate_terms(request.project_id)
        return UpsertProjectTermResult(
            state=self.get_project_terms(request.project_id),
            updated_existing=updated_existing,
        )

    def export_terms(self, request: ExportTermsRequest) -> AcceptedCommand:
        params: dict[str, object] = {"output_path": request.output_path}
        if request.document_id is not None:
            params["document_ids"] = [request.document_id]
        return self._runtime.submit_task("glossary_export", request.project_id, **params)

    def bulk_update_terms(self, request: BulkUpdateTermsRequest) -> BulkUpdateTermsResult:
        blocker = self._glossary_mutation_blocker(request.scope.project.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.scope.project.project_id)
        if not request.term_keys:
            return BulkUpdateTermsResult()
        with self._runtime.open_book_db(request.scope.project.project_id) as dbx:
            if request.delete:
                affected_count = dbx.term_repo.delete_terms(request.term_keys)
            else:
                affected_count = dbx.term_repo.update_terms_bulk(
                    request.term_keys,
                    ignored=request.ignored,
                    is_reviewed=request.reviewed,
                )
        if affected_count:
            self._runtime.invalidate_terms(
                request.scope.project.project_id,
                request.scope.document.document_id if request.scope.document is not None else None,
            )
        return BulkUpdateTermsResult(affected_count=affected_count)

    def _build_terms_table(self, project_id: str, document_id: int | None) -> TermsTableState:
        project = self._runtime.get_project_ref(project_id)
        chunk_ids, filtered_records = self._load_scope_term_records(project_id, document_id=document_id)
        rows = [self._term_record_to_row(record) for record in filtered_records]
        scope = TermsScope(
            kind=TermsScopeKind.DOCUMENT if document_id is not None else TermsScopeKind.PROJECT,
            project=project,
            document=make_document_ref(document_id, f"Document {document_id}") if document_id is not None else None,
        )
        toolbar = self._build_toolbar_state(
            project_id,
            document_id=document_id,
            has_rows=bool(rows),
            rows=rows,
        )
        return TermsTableState(
            scope=scope,
            toolbar=toolbar,
            rows=rows,
            status=SurfaceStatus.READY,
        )

    def _load_scope_rows(self, project_id: str, *, document_id: int | None) -> list[TermTableRow]:
        _chunk_ids, filtered_records = self._load_scope_term_records(project_id, document_id=document_id)
        return [self._term_record_to_row(record) for record in filtered_records]

    def _load_scope_term_records(
        self,
        project_id: str,
        *,
        document_id: int | None,
    ) -> tuple[set[int] | None, list[TermRecord]]:
        with self._runtime.open_book_db(project_id) as dbx:
            chunk_ids = (
                {chunk.chunk_id for chunk in dbx.term_repo.list_chunks(document_id=document_id)}
                if document_id is not None
                else None
            )
            filtered_records = []
            for record in dbx.term_repo.list_term_records():
                if chunk_ids is not None:
                    occurrence_chunk_ids = self._occurrence_chunk_ids(record)
                    if not occurrence_chunk_ids.intersection(chunk_ids):
                        continue
                filtered_records.append(record)
        return chunk_ids, filtered_records

    def _term_record_to_row(self, record: TermRecord) -> TermTableRow:
        return TermTableRow(
            term_id=int(record.key) if record.key.isdigit() else hash(record.key),
            term_key=record.key,
            term=record.key,
            term_type=record.term_type,
            translation=record.translated_name,
            description=self._primary_description(record),
            description_tooltip=self._description_tooltip(record),
            description_sort_key=self._max_chunk_id(record),
            occurrences=self._occurrence_chunk_count(record),
            votes=self._recognized_chunk_count(record),
            ignored=record.ignored,
            reviewed=record.is_reviewed,
            rare_candidate=self._is_structurally_rare(record),
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

    @staticmethod
    def _occurrence_chunk_ids(record: TermRecord) -> set[int]:
        return {int(key) for key in (record.occurrence or {}) if str(key).lstrip("-").isdigit()}

    @classmethod
    def _occurrence_chunk_count(cls, record: TermRecord) -> int:
        return len(cls._occurrence_chunk_ids(record))

    @staticmethod
    def _recognized_chunk_count(record: TermRecord) -> int:
        return sum(1 for key in (record.descriptions or {}) if (idx := description_index(key)) is not None and idx >= 0)

    @staticmethod
    def _max_chunk_id(record: TermRecord) -> int:
        chunk_ids = [
            idx for key in (record.descriptions or {}) if (idx := description_index(key)) is not None and idx >= 0
        ]
        return max(chunk_ids) if chunk_ids else -1

    @classmethod
    def _primary_description(cls, record: TermRecord) -> str | None:
        entries = cls._sorted_description_entries(record)
        return entries[0][1] if entries else None

    @classmethod
    def _description_tooltip(cls, record: TermRecord) -> str | None:
        entries = cls._sorted_description_entries(record)
        if not entries:
            return None
        return "\n".join(f"{key}: {value}" for key, value in entries)

    @staticmethod
    def _sorted_description_entries(record: TermRecord) -> list[tuple[str, str]]:
        return ordered_description_entries(record.descriptions or {})

    def _build_toolbar_state(
        self,
        project_id: str,
        *,
        document_id: int | None,
        has_rows: bool,
        rows: list[TermTableRow],
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
        add_terms_allowed = mutation_blocker is None and document_id is None
        add_terms_blocker = mutation_blocker if document_id is None else None
        if mutation_blocker is not None:
            translate_allowed = False
            translate_blocker = mutation_blocker
            review_allowed = False
            review_blocker = mutation_blocker
        has_rare_terms = any(row.rare_candidate and not row.ignored and not row.reviewed for row in rows)
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
            can_add_terms=add_terms_allowed,
            can_import=import_allowed,
            can_export=export_allowed and has_rows,
            build_blocker=build_blocker,
            translate_pending_blocker=translate_blocker,
            review_blocker=review_blocker,
            filter_noise_blocker=filter_noise_blocker,
            add_terms_blocker=add_terms_blocker,
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
                occurrence_chunk_ids = self._occurrence_chunk_ids(record)
                if not occurrence_chunk_ids.intersection(chunk_ids):
                    continue
            if self._is_structurally_rare(record):
                rare_keys.append(record.key)
        return rare_keys

    @classmethod
    def _is_structurally_rare(cls, record: TermRecord) -> bool:
        occurrence_chunk_count = cls._occurrence_chunk_count(record)
        if occurrence_chunk_count <= 1:
            return True
        chunk_desc_count = sum(1 for key in (record.descriptions or {}) if str(key).lstrip("-").isdigit())
        return chunk_desc_count <= 1
