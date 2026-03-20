from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, Protocol, cast

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    ActionState,
    BlockerCode,
    BlockerInfo,
    CapabilityCode,
    DocumentSection,
    NavigationTargetKind,
    ProgressInfo,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import (
    CancelOCRRequest,
    DocumentExportResult,
    DocumentExportState,
    DocumentImagesState,
    DocumentImagesToolbarState,
    DocumentOCRActions,
    DocumentOCRState,
    DocumentTranslationState,
    DocumentWorkspaceState,
    ImageAssetState,
    OCRBoundingBox,
    OCRPageState,
    OCRTextElement,
    RetranslateRequest,
    RunDocumentExportRequest,
    RunDocumentTranslationRequest,
    RunImageReinsertionRequest,
    RunOCRRequest,
    SaveOCRPageRequest,
    SaveTranslationRequest,
    TranslationUnitActionState,
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.contracts.terms import TermsTableState
from context_aware_translation.application.errors import (
    ApplicationErrorCode,
    ApplicationErrorPayload,
    BlockedOperationError,
)
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    blocker_code_for_decision_code,
    build_default_routes_from_config,
    make_blocker,
    make_document_ref,
    progress_from_task,
    raise_application_error,
)
from context_aware_translation.application.services._export_support import prepare_export, run_export
from context_aware_translation.application.services.terms import DefaultTermsService
from context_aware_translation.documents.base import Document
from context_aware_translation.documents.content.ocr_content import SinglePageOCRContent
from context_aware_translation.documents.content.ocr_items import ImageItem
from context_aware_translation.documents.epub import EPUBDocument
from context_aware_translation.documents.manga import MangaDocument
from context_aware_translation.documents.manga_alignment import (
    align_sources_to_chunks,
    extract_ocr_text,
    get_sources_with_nonempty_ocr_text,
)
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import ClaimMode, ResourceClaim
from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES, TaskAction

_IMAGE_REEMBEDDABLE_DOCUMENT_TYPES = frozenset({"pdf", "scanned_book", "manga", "epub"})


class DocumentService(Protocol):
    def get_workspace(self, project_id: str, document_id: int) -> DocumentWorkspaceState: ...

    def get_ocr(self, project_id: str, document_id: int) -> DocumentOCRState: ...

    def get_ocr_page_image(self, project_id: str, document_id: int, source_id: int) -> bytes | None: ...

    def save_ocr(self, request: SaveOCRPageRequest) -> DocumentOCRState: ...

    def run_ocr(self, request: RunOCRRequest) -> AcceptedCommand: ...

    def cancel_ocr(self, request: CancelOCRRequest) -> AcceptedCommand: ...

    def get_terms(self, project_id: str, document_id: int) -> TermsTableState: ...

    def get_translation(
        self, project_id: str, document_id: int, *, enable_polish: bool = True
    ) -> DocumentTranslationState: ...

    def save_translation(self, request: SaveTranslationRequest) -> DocumentTranslationState: ...

    def retranslate(self, request: RetranslateRequest) -> AcceptedCommand: ...

    def run_translation(self, request: RunDocumentTranslationRequest) -> AcceptedCommand: ...

    def get_images(self, project_id: str, document_id: int) -> DocumentImagesState: ...

    def run_image_reinsertion(self, request: RunImageReinsertionRequest) -> AcceptedCommand: ...

    def cancel_image_reinsertion(self, project_id: str, task_id: str) -> AcceptedCommand: ...

    def get_export(self, project_id: str, document_id: int) -> DocumentExportState: ...

    def export_document(self, request: RunDocumentExportRequest) -> DocumentExportResult: ...


class DefaultDocumentService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_workspace(self, project_id: str, document_id: int) -> DocumentWorkspaceState:
        project = self._runtime.get_project_ref(project_id)
        with self._runtime.open_book_db(project_id) as dbx:
            doc = dbx.document_repo.get_document_by_id(document_id)
            if doc is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {document_id}")
        return DocumentWorkspaceState(
            project=project,
            document=make_document_ref(document_id, f"Document {document_id}", str(doc.get("document_type") or "")),
            active_tab=DocumentSection.OCR,
        )

    def get_ocr(self, project_id: str, document_id: int) -> DocumentOCRState:
        workspace = self.get_workspace(project_id, document_id).model_copy(update={"active_tab": DocumentSection.OCR})
        with self._runtime.open_book_db(project_id) as dbx:
            sources = dbx.document_repo.get_document_sources_metadata(document_id)
            image_sources = [source for source in sources if source.get("source_type") == "image"]
            active_task = self._get_active_ocr_task(project_id, document_id)
            active_source_ids = self._task_source_ids(active_task)
            pages = [
                self._build_ocr_page(
                    project_id,
                    source,
                    document_repo=dbx.document_repo,
                    running=(
                        active_task is not None
                        and (active_source_ids is None or int(source["source_id"]) in active_source_ids)
                    ),
                )
                for source in image_sources
            ]
            total_pages = len(pages)
            pages = [page.model_copy(update={"total_pages": total_pages}) for page in pages]
            chunk_count = dbx.document_repo.get_chunk_count(document_id)
        return DocumentOCRState(
            workspace=workspace,
            pages=pages,
            current_page_index=0 if pages else None,
            actions=self._build_ocr_actions(
                project_id,
                document_id,
                current_source_id=pages[0].source_id if pages else None,
                has_pages=bool(pages),
                chunk_count=chunk_count,
                active_task=active_task,
            ),
            progress=progress_from_task(active_task) if active_task is not None else None,
            active_task_id=active_task.task_id if active_task is not None else None,
        )

    def get_ocr_page_image(self, project_id: str, document_id: int, source_id: int) -> bytes | None:
        with self._runtime.open_book_db(project_id) as dbx:
            sources = dbx.document_repo.get_document_sources_metadata(document_id)
            source_row = next(
                (
                    source
                    for source in sources
                    if source.get("source_type") == "image" and int(source["source_id"]) == int(source_id)
                ),
                None,
            )
            if source_row is None:
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND,
                    f"OCR page not found: source_id={source_id}",
                    project_id=project_id,
                    document_id=document_id,
                    source_id=source_id,
                )
            image_bytes = dbx.document_repo.get_source_binary_content(source_id)
            if image_bytes is None:
                relative_path = source_row.get("relative_path")
                if isinstance(relative_path, str) and relative_path:
                    disk_path = self._runtime.book_manager.get_book_path(project_id) / relative_path
                    if disk_path.exists():
                        image_bytes = disk_path.read_bytes()
        return image_bytes

    def save_ocr(self, request: SaveOCRPageRequest) -> DocumentOCRState:
        with self._runtime.open_book_db(request.project_id) as dbx:
            blocker = self._ocr_mutation_blocker(
                request.project_id,
                request.document_id,
                chunk_count=dbx.document_repo.get_chunk_count(request.document_id),
            )
            if blocker is not None:
                raise_application_error(
                    ApplicationErrorCode.BLOCKED,
                    blocker.message,
                    project_id=request.project_id,
                    document_id=request.document_id,
                    source_id=request.source_id,
                    decision_code=blocker.code.value,
                )
            sources = dbx.document_repo.get_document_sources_metadata(request.document_id)
            if not any(
                int(source["source_id"]) == int(request.source_id)
                for source in sources
                if source.get("source_type") == "image"
            ):
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND,
                    f"OCR page not found: source_id={request.source_id}",
                    project_id=request.project_id,
                    document_id=request.document_id,
                    source_id=request.source_id,
                )
            existing_ocr_json = dbx.document_repo.get_source_ocr_json(request.source_id)
            serialized = self._serialize_ocr_save(existing_ocr_json, request)
            dbx.document_repo.update_source_ocr(request.source_id, serialized)
            dbx.document_repo.update_source_ocr_completed(request.source_id)
            reset_result = dbx.document_repo.reset_document_stack(request.document_id)
        invalidated_sections = [
            DocumentSection.OCR,
            DocumentSection.TERMS,
            DocumentSection.TRANSLATION,
            DocumentSection.EXPORT,
        ]
        affected_document_ids = [int(document_id) for document_id in reset_result.get("affected_document_ids", [])]
        invalidate_all_documents = any(document_id != request.document_id for document_id in affected_document_ids)
        self._runtime.invalidate_document(
            request.project_id,
            None if invalidate_all_documents else request.document_id,
            sections=invalidated_sections,
        )
        if affected_document_ids:
            self._runtime.invalidate_terms(request.project_id)
        self._runtime.invalidate_workboard(request.project_id)
        return self.get_ocr(request.project_id, request.document_id)

    def run_ocr(self, request: RunOCRRequest) -> AcceptedCommand:
        with self._runtime.open_book_db(request.project_id) as dbx:
            blocker = self._ocr_mutation_blocker(
                request.project_id,
                request.document_id,
                chunk_count=dbx.document_repo.get_chunk_count(request.document_id),
            )
            if blocker is not None:
                raise_application_error(
                    ApplicationErrorCode.BLOCKED,
                    blocker.message,
                    project_id=request.project_id,
                    document_id=request.document_id,
                    source_id=request.source_id,
                    decision_code=blocker.code.value,
                )
        params: dict[str, object] = {"document_ids": [request.document_id]}
        if request.source_id is not None:
            params["source_ids"] = [request.source_id]
        return self._runtime.submit_task("ocr", request.project_id, **params)

    def cancel_ocr(self, request: CancelOCRRequest) -> AcceptedCommand:
        record = self._runtime.task_store.get(request.task_id)
        if record is None or record.book_id != request.project_id or record.task_type != "ocr":
            raise_application_error(
                ApplicationErrorCode.NOT_FOUND,
                f"OCR task not found: {request.task_id}",
                project_id=request.project_id,
                task_id=request.task_id,
            )
        decision = self._runtime.task_engine.preflight_task(request.task_id, TaskAction.CANCEL)
        if not decision.allowed:
            document_ids = self._task_document_ids(record)
            raise_application_error(
                ApplicationErrorCode.BLOCKED,
                decision.reason or "OCR cannot be cancelled.",
                project_id=request.project_id,
                task_id=request.task_id,
                document_id=document_ids[0] if document_ids is not None and len(document_ids) == 1 else None,
            )
        self._runtime.task_engine.cancel(request.task_id)
        self._runtime.invalidate_task_activity(request.project_id)
        return AcceptedCommand(
            command_name="cancel_ocr",
            command_id=request.task_id,
            queue_item_id=request.task_id,
            message=UserMessage(
                severity=UserMessageSeverity.INFO,
                text="OCR cancellation requested.",
            ),
        )

    def get_terms(self, project_id: str, document_id: int) -> TermsTableState:
        return DefaultTermsService(self._runtime).get_document_terms(project_id, document_id)

    def get_translation(
        self, project_id: str, document_id: int, *, enable_polish: bool = True
    ) -> DocumentTranslationState:
        workspace = self.get_workspace(project_id, document_id).model_copy(
            update={"active_tab": DocumentSection.TRANSLATION}
        )
        with self._runtime.open_book_db(project_id) as dbx:
            doc = dbx.document_repo.get_document_by_id(document_id)
            if doc is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {document_id}")
            document_type = str(doc.get("document_type") or "")
            units = self._build_translation_units(
                project_id,
                document_id,
                document_type=document_type,
                dbx=dbx,
            )
        active_task = self._active_translation_task(project_id, document_id)
        translatable_units = [unit for unit in units if unit.blocker is None]
        completed_units = sum(1 for unit in translatable_units if unit.status is SurfaceStatus.DONE)
        progress = progress_from_task(active_task) if active_task is not None else None
        if progress is None and translatable_units:
            progress = ProgressInfo(
                current=completed_units,
                total=len(translatable_units),
                label="Translated units",
            )
        current_unit = next((unit for unit in units if unit.blocker is None), units[0] if units else None)
        run_allowed, run_blocker = self._translation_run_action_state(
            project_id,
            document_id=document_id,
            document_type=document_type,
            enable_polish=enable_polish,
            batch=False,
            has_work=bool(translatable_units),
            active_task=active_task,
        )
        supports_batch = document_type != "manga"
        batch_allowed, batch_blocker = self._translation_run_action_state(
            project_id,
            document_id=document_id,
            document_type=document_type,
            enable_polish=enable_polish,
            batch=True,
            has_work=bool(translatable_units),
            active_task=active_task,
        )
        return DocumentTranslationState(
            workspace=workspace,
            units=units,
            run_action=ActionState(enabled=run_allowed, blocker=run_blocker),
            batch_action=ActionState(enabled=batch_allowed, blocker=batch_blocker),
            supports_batch=supports_batch,
            current_unit_id=current_unit.unit_id if current_unit is not None else None,
            progress=progress,
            active_task_id=active_task.task_id if active_task is not None else None,
            terms=self.get_terms(project_id, document_id),
        )

    def save_translation(self, request: SaveTranslationRequest) -> DocumentTranslationState:
        with self._runtime.open_book_db(request.project_id) as dbx:
            doc = dbx.document_repo.get_document_by_id(request.document_id)
            if doc is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {request.document_id}")
            blocker = self._translation_save_blocker(request.project_id, request.document_id)
            if blocker is not None:
                self._raise_blocked_blocker(blocker, document_id=request.document_id, unit_id=request.unit_id)

            document_type = str(doc.get("document_type") or "")
            if document_type == "manga":
                chunk = self._resolve_manga_chunk_for_source(
                    dbx=dbx,
                    document_id=request.document_id,
                    source_id=int(request.unit_id),
                )
                if chunk is None:
                    raise_blocked_or_not_found_for_manga_unit(
                        project_id=request.project_id,
                        document_id=request.document_id,
                        source_id=int(request.unit_id),
                    )
                updated_chunk = replace(
                    chunk,
                    is_translated=bool(request.translated_text.strip()),
                    translation=request.translated_text if request.translated_text.strip() else None,
                )
            else:
                chunk = dbx.db.get_chunk_by_id(int(request.unit_id))
                if chunk is None or chunk.document_id is None or chunk.document_id != request.document_id:
                    raise_application_error(
                        ApplicationErrorCode.NOT_FOUND,
                        f"Translation unit not found: {request.unit_id}",
                    )
                source_line_count = self._line_count(chunk.text)
                translated_line_count = self._line_count(request.translated_text)
                if source_line_count > 0 and translated_line_count != source_line_count:
                    raise_application_error(
                        ApplicationErrorCode.VALIDATION,
                        (
                            f"Cannot save translation with {translated_line_count} lines; "
                            f"expected {source_line_count} lines."
                        ),
                        document_id=request.document_id,
                        unit_id=request.unit_id,
                    )
                updated_chunk = replace(
                    chunk,
                    is_translated=bool(request.translated_text.strip()),
                    translation=request.translated_text if request.translated_text.strip() else None,
                )
            dbx.db.upsert_chunks([updated_chunk])
        self._runtime.invalidate_document(
            request.project_id,
            request.document_id,
            sections=[
                DocumentSection.TRANSLATION,
                DocumentSection.IMAGES,
                DocumentSection.EXPORT,
            ],
        )
        self._runtime.invalidate_workboard(request.project_id)
        return self.get_translation(request.project_id, request.document_id)

    def retranslate(self, request: RetranslateRequest) -> AcceptedCommand:
        with self._runtime.open_book_db(request.project_id) as dbx:
            doc = dbx.document_repo.get_document_by_id(request.document_id)
            if doc is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {request.document_id}")
            document_type = str(doc.get("document_type") or "")
            if document_type == "manga":
                source_id = int(request.unit_id)
                unit = self._build_manga_translation_units(request.project_id, request.document_id, dbx)
                matched = next((candidate for candidate in unit if candidate.unit_id == request.unit_id), None)
                if matched is None:
                    raise_application_error(
                        ApplicationErrorCode.NOT_FOUND,
                        f"Translation unit not found: {request.unit_id}",
                    )
                blocker = matched.actions.retranslate_blocker or matched.blocker
                if blocker is not None:
                    self._raise_blocked_blocker(blocker, document_id=request.document_id, unit_id=request.unit_id)
                return self._runtime.submit_task(
                    "translation_manga",
                    request.project_id,
                    document_ids=[request.document_id],
                    source_ids=[source_id],
                    force=True,
                )

            unit = self._build_text_translation_units(request.project_id, request.document_id, dbx)
            matched = next((candidate for candidate in unit if candidate.unit_id == request.unit_id), None)
            if matched is None:
                raise_application_error(
                    ApplicationErrorCode.NOT_FOUND,
                    f"Translation unit not found: {request.unit_id}",
                )
            blocker = matched.actions.retranslate_blocker or matched.blocker
            if blocker is not None:
                self._raise_blocked_blocker(blocker, document_id=request.document_id, unit_id=request.unit_id)
        return self._runtime.submit_task(
            "chunk_retranslation",
            request.project_id,
            document_ids=[request.document_id],
            chunk_id=int(request.unit_id),
            document_id=request.document_id,
        )

    def run_translation(self, request: RunDocumentTranslationRequest) -> AcceptedCommand:
        with self._runtime.open_book_db(request.project_id) as dbx:
            doc = dbx.document_repo.get_document_by_id(request.document_id)
            if doc is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {request.document_id}")
            document_type = str(doc.get("document_type") or "")
        if request.batch:
            if document_type == "manga":
                raise_application_error(
                    ApplicationErrorCode.BLOCKED,
                    "Async batch translation is only available for non-manga documents.",
                    project_id=request.project_id,
                    document_id=request.document_id,
                )
            return self._runtime.submit_task(
                "batch_translation",
                request.project_id,
                document_ids=[request.document_id],
                enable_polish=request.enable_polish,
            )
        if document_type == "manga":
            return self._runtime.submit_task(
                "translation_manga",
                request.project_id,
                document_ids=[request.document_id],
                enable_polish=request.enable_polish,
            )
        return self._runtime.submit_task(
            "translation_text",
            request.project_id,
            document_ids=[request.document_id],
            enable_polish=request.enable_polish,
        )

    def get_images(self, project_id: str, document_id: int) -> DocumentImagesState:
        workspace = self.get_workspace(project_id, document_id).model_copy(
            update={"active_tab": DocumentSection.IMAGES}
        )
        active_task = self._find_active_image_reembedding_task(project_id, document_id)
        with self._runtime.open_book_db(project_id) as dbx:
            doc_row = dbx.document_repo.get_document_by_id(document_id)
            if doc_row is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {document_id}")
            document_type = str(doc_row.get("document_type") or "")
            assets = self._build_image_assets(
                project_id,
                dbx.document_repo,
                document_id=document_id,
                document_type=document_type,
                active_task=active_task,
            )
            assets = self._apply_source_asset_actions(
                project_id,
                document_id=document_id,
                document_type=document_type,
                assets=assets,
                active_task=active_task,
            )

        toolbar = self._build_images_toolbar_state(
            project_id,
            document_id=document_id,
            document_type=document_type,
            assets=assets,
            active_task=active_task,
        )
        return DocumentImagesState(
            workspace=workspace,
            assets=assets,
            toolbar=toolbar,
            progress=progress_from_task(active_task) if active_task is not None else None,
            active_task_id=active_task.task_id if active_task is not None else None,
        )

    def run_image_reinsertion(self, request: RunImageReinsertionRequest) -> AcceptedCommand:
        params: dict[str, object] = {"document_ids": [request.document_id], "force": request.force_all}
        if request.source_id is not None:
            params["source_ids"] = [request.source_id]
        return self._runtime.submit_task("image_reembedding", request.project_id, **params)

    def cancel_image_reinsertion(self, project_id: str, task_id: str) -> AcceptedCommand:
        record = self._runtime.task_store.get(task_id)
        if record is None or record.book_id != project_id or record.task_type != "image_reembedding":
            raise_application_error(
                ApplicationErrorCode.NOT_FOUND,
                f"Image reinsertion task not found: {task_id}",
                project_id=project_id,
                task_id=task_id,
            )
        decision = self._runtime.task_engine.preflight_task(task_id, TaskAction.CANCEL)
        if not decision.allowed:
            document_ids = self._task_document_ids(record)
            raise_application_error(
                ApplicationErrorCode.BLOCKED,
                decision.reason or "Image reinsertion cannot be cancelled.",
                project_id=project_id,
                task_id=task_id,
                document_id=document_ids[0] if document_ids is not None and len(document_ids) == 1 else None,
            )
        self._runtime.task_engine.cancel(task_id)
        self._runtime.invalidate_task_activity(project_id)
        return AcceptedCommand(
            command_name="cancel_image_reinsertion",
            command_id=task_id,
            queue_item_id=task_id,
            message=UserMessage(
                severity=UserMessageSeverity.INFO,
                text="Image reinsertion cancellation requested.",
            ),
        )

    def get_export(self, project_id: str, document_id: int) -> DocumentExportState:
        workspace = self.get_workspace(project_id, document_id).model_copy(
            update={"active_tab": DocumentSection.EXPORT}
        )
        prepared = prepare_export(self._runtime, project_id=project_id, document_ids=[document_id])
        return DocumentExportState(
            workspace=workspace,
            can_export=True,
            available_formats=prepared.available_formats,
            default_output_path=prepared.default_output_path,
            supports_preserve_structure=prepared.supports_preserve_structure,
            incomplete_translation_message=prepared.incomplete_translation_message,
        )

    def export_document(self, request: RunDocumentExportRequest) -> DocumentExportResult:
        result = run_export(
            self._runtime,
            project_id=request.project_id,
            document_ids=[request.document_id],
            format_id=request.format_id,
            output_path=request.output_path,
            options=request.options,
        )
        self._runtime.invalidate_document(
            request.project_id,
            request.document_id,
            sections=[DocumentSection.EXPORT],
        )
        self._runtime.invalidate_workboard(request.project_id)
        return result.model_copy(update={"document_id": request.document_id})

    def _get_active_ocr_task(self, project_id: str, document_id: int) -> Any | None:
        for record in self._runtime.task_engine.get_tasks(project_id, task_type="ocr", full=True):
            if record.status in TERMINAL_TASK_STATUSES:
                continue
            document_ids = self._task_document_ids(record)
            if document_ids == [document_id]:
                return record
        return None

    def _task_document_ids(self, record: Any) -> list[int] | None:
        if not getattr(record, "document_ids_json", None):
            return None
        try:
            payload = json.loads(record.document_ids_json)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, list):
            return None
        values: list[int] = []
        for item in payload:
            try:
                values.append(int(item))
            except (TypeError, ValueError):
                return None
        return values

    def _task_source_ids(self, record: Any) -> set[int] | None:
        if record is None or not getattr(record, "payload_json", None):
            return None
        try:
            payload = json.loads(record.payload_json)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        raw_ids = payload.get("source_ids")
        if raw_ids is None:
            return None
        if not isinstance(raw_ids, list):
            return None
        values: set[int] = set()
        for item in raw_ids:
            try:
                values.add(int(item))
            except (TypeError, ValueError):
                return None
        return values

    def _find_active_image_reembedding_task(self, project_id: str, document_id: int) -> TaskRecord | None:
        records = self._runtime.task_store.list_tasks(book_id=project_id, task_type="image_reembedding")
        for record in records:
            if record.status in TERMINAL_TASK_STATUSES:
                continue
            document_ids = self._task_document_ids(record)
            if document_ids is not None and document_id in document_ids:
                return record
        return None

    def _build_ocr_actions(
        self,
        project_id: str,
        document_id: int,
        *,
        current_source_id: int | None,
        has_pages: bool,
        chunk_count: int,
        active_task: Any,
    ) -> DocumentOCRActions:
        if not has_pages or current_source_id is None:
            no_pages = ActionState(
                enabled=False,
                blocker=make_blocker(
                    BlockerCode.NOTHING_TO_DO,
                    "No image pages are available for OCR in this document.",
                    target_kind=NavigationTargetKind.DOCUMENT_OCR,
                    project_id=project_id,
                    document_id=document_id,
                ),
            )
            return DocumentOCRActions(save=no_pages, run_current=no_pages, run_pending=no_pages)

        save_blocker = self._ocr_mutation_blocker(
            project_id,
            document_id,
            chunk_count=chunk_count,
            active_task=active_task,
        )
        rerun_blocker = self._ocr_mutation_blocker(
            project_id,
            document_id,
            chunk_count=chunk_count,
            active_task=active_task,
        )
        save_action = ActionState(enabled=save_blocker is None, blocker=save_blocker)
        if rerun_blocker is not None:
            disabled = ActionState(enabled=False, blocker=rerun_blocker)
            return DocumentOCRActions(save=save_action, run_current=disabled, run_pending=disabled)

        current_allowed, current_blocker = self._decision_to_action_state(
            project_id,
            self._runtime.task_engine.preflight(
                "ocr",
                project_id,
                {"document_ids": [document_id], "source_ids": [current_source_id]},
                TaskAction.RUN,
            ),
            document_id=document_id,
        )
        pending_allowed, pending_blocker = self._decision_to_action_state(
            project_id,
            self._runtime.task_engine.preflight(
                "ocr",
                project_id,
                {"document_ids": [document_id]},
                TaskAction.RUN,
            ),
            document_id=document_id,
        )
        return DocumentOCRActions(
            save=save_action,
            run_current=ActionState(enabled=current_allowed, blocker=current_blocker),
            run_pending=ActionState(enabled=pending_allowed, blocker=pending_blocker),
        )

    def _decision_to_action_state(
        self,
        project_id: str,
        decision: Any,
        *,
        document_id: int,
        target_kind: NavigationTargetKind = NavigationTargetKind.DOCUMENT_OCR,
        default_reason: str = "Operation is blocked.",
    ) -> tuple[bool, BlockerInfo | None]:
        if decision.allowed:
            return True, None
        return False, make_blocker(
            blocker_code_for_decision_code(decision.code or ""),
            decision.reason or default_reason,
            target_kind=target_kind,
            project_id=project_id,
            document_id=document_id,
        )

    def _ocr_mutation_blocker(
        self,
        project_id: str,
        document_id: int,
        *,
        chunk_count: int,
        active_task: Any | None = None,
    ) -> BlockerInfo | None:
        if active_task is not None:
            return make_blocker(
                BlockerCode.ALREADY_RUNNING_ELSEWHERE,
                "OCR is already running for this document.",
                target_kind=NavigationTargetKind.QUEUE,
                project_id=project_id,
                document_id=document_id,
            )
        wanted = frozenset(
            {
                ResourceClaim("ocr", project_id, str(document_id), ClaimMode.WRITE_EXCLUSIVE),
                ResourceClaim("doc", project_id, str(document_id), ClaimMode.WRITE_EXCLUSIVE),
            }
        )
        if self._runtime.task_engine.has_active_claims(project_id, wanted):
            return make_blocker(
                BlockerCode.ALREADY_RUNNING_ELSEWHERE,
                "Another OCR task is already running for this document.",
                target_kind=NavigationTargetKind.QUEUE,
                project_id=project_id,
                document_id=document_id,
            )
        if chunk_count > 0:
            return make_blocker(
                BlockerCode.NOTHING_TO_DO,
                "OCR is locked after terms or translation have started for this document.",
                target_kind=NavigationTargetKind.DOCUMENT_OCR,
                project_id=project_id,
                document_id=document_id,
            )
        return None

    def _serialize_ocr_save(self, existing_ocr_json: str | None, request: SaveOCRPageRequest) -> str:
        payload: Any = None
        if existing_ocr_json:
            try:
                payload = json.loads(existing_ocr_json)
            except json.JSONDecodeError:
                payload = None

        if isinstance(payload, list):
            content = SinglePageOCRContent.from_ocr_json(payload)
            replacement_lines = (
                [element.text for element in request.elements]
                if request.elements
                else (request.extracted_text or "").split("\n")
            )
            content.set_texts(replacement_lines)
            return json.dumps(content.to_json(), ensure_ascii=False)

        if isinstance(payload, dict):
            updated = dict(payload)
            if request.elements and isinstance(updated.get("boxes"), list):
                boxes = list(updated["boxes"])
                if len(boxes) == len(request.elements) and all(isinstance(box, dict) for box in boxes):
                    updated["boxes"] = [
                        {**box, "text": element.text} for box, element in zip(boxes, request.elements, strict=True)
                    ]
                    if "text" in updated:
                        updated["text"] = (
                            request.extracted_text
                            if request.extracted_text is not None
                            else "\n".join(element.text for element in request.elements)
                        )
                    return json.dumps(updated, ensure_ascii=False)
            if "embedded_text" in updated:
                updated["embedded_text"] = request.extracted_text or ""
            else:
                updated["text"] = request.extracted_text or ""
            return json.dumps(updated, ensure_ascii=False)

        if request.elements:
            return json.dumps(
                {
                    "text": request.extracted_text
                    if request.extracted_text is not None
                    else "\n".join(element.text for element in request.elements),
                    "boxes": [{"text": element.text} for element in request.elements],
                },
                ensure_ascii=False,
            )
        return json.dumps({"text": request.extracted_text or ""}, ensure_ascii=False)

    def _build_ocr_page(
        self,
        project_id: str,
        source: dict[str, Any],
        *,
        document_repo: Any,
        running: bool,
    ) -> OCRPageState:
        ocr_json = document_repo.get_source_ocr_json(int(source["source_id"]))
        extracted_text = None
        elements: list[OCRTextElement] = []
        if ocr_json:
            try:
                payload = json.loads(ocr_json)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, list):
                content = SinglePageOCRContent.from_ocr_json(payload)
                elements = self._elements_from_single_page_content(content)
                extracted_text = "\n".join(element.text for element in elements)
            elif isinstance(payload, dict):
                if isinstance(payload.get("text"), str):
                    extracted_text = payload.get("text")
                elif isinstance(payload.get("embedded_text"), str):
                    extracted_text = payload.get("embedded_text")
                boxes = payload.get("boxes")
                if isinstance(boxes, list):
                    elements = [
                        OCRTextElement(
                            element_id=index,
                            text=str(box.get("text") or ""),
                            bbox_id=index,
                            bbox=self._bbox_from_payload(box),
                            kind=str(box.get("type") or "text"),
                        )
                        for index, box in enumerate(boxes)
                        if isinstance(box, dict)
                    ]
                    if extracted_text is None and elements:
                        extracted_text = "\n".join(element.text for element in elements if element.text)
        image_path = None
        relative_path = source.get("relative_path")
        if isinstance(relative_path, str) and relative_path:
            image_path = str(self._runtime.book_manager.get_book_path(project_id) / relative_path)
        return OCRPageState(
            source_id=int(source["source_id"]),
            page_number=int(source.get("sequence_number", 0)) + 1,
            status=(
                SurfaceStatus.RUNNING
                if running
                else (SurfaceStatus.DONE if bool(source.get("is_ocr_completed")) else SurfaceStatus.READY)
            ),
            image_path=image_path,
            extracted_text=extracted_text,
            elements=elements,
        )

    @staticmethod
    def _bbox_from_payload(payload: dict[str, Any]) -> OCRBoundingBox | None:
        bbox_payload = payload.get("bbox") if isinstance(payload.get("bbox"), dict) else payload
        if not isinstance(bbox_payload, dict):
            return None
        try:
            x = float(bbox_payload["x"])
            y = float(bbox_payload["y"])
            width = float(bbox_payload["width"])
            height = float(bbox_payload["height"])
        except (KeyError, TypeError, ValueError):
            return None
        return OCRBoundingBox(x=x, y=y, width=width, height=height)

    @classmethod
    def _elements_from_single_page_content(cls, content: SinglePageOCRContent) -> list[OCRTextElement]:
        elements: list[OCRTextElement] = []
        for item in content.items:
            kind = type(item).__name__.removesuffix("Item").lower() or "text"
            bbox = cls._bbox_from_payload({"bbox": getattr(item, "bbox", None)})
            bbox_id = len(elements) if bbox is not None else None
            for text in item.get_texts():
                elements.append(
                    OCRTextElement(
                        element_id=len(elements),
                        text=text,
                        bbox_id=bbox_id,
                        bbox=bbox,
                        kind=kind,
                    )
                )
        return elements

    def _build_translation_units(
        self,
        project_id: str,
        document_id: int,
        *,
        document_type: str,
        dbx: Any,
    ) -> list[TranslationUnitState]:
        if document_type == "manga":
            return self._build_manga_translation_units(project_id, document_id, dbx)
        return self._build_text_translation_units(project_id, document_id, dbx)

    def _build_text_translation_units(
        self,
        project_id: str,
        document_id: int,
        dbx: Any,
    ) -> list[TranslationUnitState]:
        chunks = sorted(dbx.term_repo.list_chunks(document_id=document_id), key=lambda chunk: int(chunk.chunk_id))
        save_blocker = self._translation_save_blocker(project_id, document_id)
        units: list[TranslationUnitState] = []
        for chunk in chunks:
            retranslate_allowed, retranslate_blocker = self._retranslate_action_state_for_chunk(
                project_id,
                document_id,
                int(chunk.chunk_id),
            )
            actions = TranslationUnitActionState(
                can_save=save_blocker is None,
                can_retranslate=retranslate_allowed,
                save_blocker=save_blocker,
                retranslate_blocker=retranslate_blocker,
            )
            units.append(
                TranslationUnitState(
                    unit_id=str(chunk.chunk_id),
                    unit_kind=TranslationUnitKind.CHUNK,
                    label=f"Chunk {chunk.chunk_id}",
                    status=SurfaceStatus.DONE if chunk.is_translated else SurfaceStatus.READY,
                    source_text=chunk.text,
                    translated_text=chunk.translation,
                    line_count=self._line_count(chunk.text),
                    actions=actions,
                )
            )
        return units

    def _build_image_assets(
        self,
        project_id: str,
        document_repo: DocumentRepository,
        *,
        document_id: int,
        document_type: str,
        active_task: TaskRecord | None,
    ) -> list[ImageAssetState]:
        config = self._runtime.get_effective_config(project_id)
        document = Document.load_by_id(document_repo, document_id, config.ocr_config)
        if document is None:
            return []
        translated_lines = self._get_translated_lines_with_fallback(project_id, document_id, document_type)
        if not translated_lines:
            return []
        try:
            asyncio.run(document.set_text(translated_lines))
        except Exception:
            return []

        if document_type == "manga":
            return self._collect_manga_assets(project_id, document_repo, document, active_task=active_task)
        if document_type == "epub":
            return self._collect_epub_assets(project_id, document_repo, document, active_task=active_task)
        return self._collect_structured_assets(project_id, document, active_task=active_task)

    def _get_translated_lines_with_fallback(self, project_id: str, document_id: int, document_type: str) -> list[str]:
        with self._runtime.open_book_db(project_id) as dbx:
            chunks = dbx.db.list_chunks(document_id=document_id)
        if not chunks:
            return []
        sorted_chunks = sorted(chunks, key=lambda chunk: chunk.chunk_id)
        if document_type == "manga":
            return [
                chunk.translation if chunk.is_translated and chunk.translation is not None else ""
                for chunk in sorted_chunks
            ]
        if not any(chunk.is_translated and chunk.translation is not None for chunk in sorted_chunks):
            return []
        translated_text = "".join(
            chunk.translation if chunk.is_translated and chunk.translation is not None else chunk.text
            for chunk in sorted_chunks
        )
        return translated_text.split("\n")

    def _collect_manga_assets(
        self,
        project_id: str,
        document_repo: DocumentRepository,
        document: object,
        *,
        active_task: TaskRecord | None,
    ) -> list[ImageAssetState]:
        if not isinstance(document, MangaDocument):
            return []
        persisted = document_repo.load_reembedded_images(document.document_id)
        active_source_ids = self._task_source_ids(active_task) if active_task is not None else None
        items: list[ImageAssetState] = []
        for source_idx, source, _ocr_text in get_sources_with_nonempty_ocr_text(
            document_repo.get_document_sources(document.document_id)
        ):
            source_id = int(source["source_id"])
            translated = document._page_translations.get(source_id, "")
            if not translated.strip():
                continue
            is_running = active_task is not None and (active_source_ids is None or source_id in active_source_ids)
            is_done = source_idx in persisted
            items.append(
                ImageAssetState(
                    asset_id=str(source_idx),
                    label=self._image_label(source),
                    status=SurfaceStatus.RUNNING
                    if is_running
                    else SurfaceStatus.DONE
                    if is_done
                    else SurfaceStatus.READY,
                    source_id=source_id,
                    translated_text=translated,
                    original_image_bytes=source.get("binary_content"),
                    reembedded_image_bytes=persisted.get(source_idx, (None, ""))[0] if is_done else None,
                    can_run=active_task is None,
                    run_blocker=None
                    if active_task is None
                    else self._active_task_blocker(project_id=project_id, document_id=document.document_id),
                )
            )
        return items

    def _collect_epub_assets(
        self,
        project_id: str,
        document_repo: DocumentRepository,
        document: object,
        *,
        active_task: TaskRecord | None,
    ) -> list[ImageAssetState]:
        if not isinstance(document, EPUBDocument):
            return []
        persisted = document_repo.load_reembedded_images(document.document_id)
        active_source_ids = self._task_source_ids(active_task) if active_task is not None else None
        items: list[ImageAssetState] = []
        sources = sorted(
            document_repo.get_document_sources(document.document_id),
            key=lambda source: int(source.get("sequence_number", 0) or 0),
        )
        for source in sources:
            if source.get("source_type") != "image" or not source.get("binary_content"):
                continue
            source_id = int(source["source_id"])
            translated = document._translated_image_texts.get(source_id, "")
            if not translated.strip():
                continue
            is_running = active_task is not None and (active_source_ids is None or source_id in active_source_ids)
            is_done = source_id in persisted
            items.append(
                ImageAssetState(
                    asset_id=str(source_id),
                    label=self._image_label(source),
                    status=SurfaceStatus.RUNNING
                    if is_running
                    else SurfaceStatus.DONE
                    if is_done
                    else SurfaceStatus.READY,
                    source_id=source_id,
                    translated_text=translated,
                    original_image_bytes=source.get("binary_content"),
                    reembedded_image_bytes=persisted.get(source_id, (None, ""))[0] if is_done else None,
                    can_run=active_task is None,
                    run_blocker=None
                    if active_task is None
                    else self._active_task_blocker(project_id=project_id, document_id=document.document_id),
                )
            )
        return items

    def _collect_structured_assets(
        self,
        project_id: str,
        document: object,
        *,
        active_task: TaskRecord | None,
    ) -> list[ImageAssetState]:
        merged = getattr(document, "_merged_content", None)
        if merged is None:
            return []
        typed_document = cast(Any, document)
        document_id = int(typed_document.document_id)
        items: list[ImageAssetState] = []
        for index, element in enumerate(merged.elements):
            if not isinstance(element, ImageItem) or not element.needs_reembedding():
                continue
            translated = element.get_embedded_translation() or ""
            if not translated.strip():
                continue
            is_done = element.reembedded_image_bytes is not None
            items.append(
                ImageAssetState(
                    asset_id=str(index),
                    label=f"Image {len(items) + 1}",
                    status=SurfaceStatus.RUNNING
                    if active_task is not None and not is_done
                    else SurfaceStatus.DONE
                    if is_done
                    else SurfaceStatus.READY,
                    translated_text=translated,
                    original_image_bytes=element.image_bytes,
                    reembedded_image_bytes=element.reembedded_image_bytes,
                    can_run=False,
                    run_blocker=make_blocker(
                        BlockerCode.NOTHING_TO_DO,
                        "Reinsert Selected is available only for manga and EPUB documents.",
                        target_kind=NavigationTargetKind.DOCUMENT_IMAGES,
                        project_id=project_id,
                        document_id=document_id,
                    ),
                )
            )
        return items

    def _build_images_toolbar_state(
        self,
        project_id: str,
        *,
        document_id: int,
        document_type: str,
        assets: list[ImageAssetState],
        active_task: TaskRecord | None,
    ) -> DocumentImagesToolbarState:
        if active_task is not None:
            cancel_decision = self._runtime.task_engine.preflight_task(active_task.task_id, TaskAction.CANCEL)
            return DocumentImagesToolbarState(
                can_cancel=cancel_decision.allowed,
                cancel_blocker=None
                if cancel_decision.allowed
                else self._image_decision_to_blocker(
                    project_id,
                    document_id=document_id,
                    decision_code=cancel_decision.code or "",
                    reason=cancel_decision.reason or "",
                    default_target=NavigationTargetKind.DOCUMENT_IMAGES,
                ),
                run_pending_blocker=self._active_task_blocker(project_id=project_id, document_id=document_id),
                force_all_blocker=self._active_task_blocker(project_id=project_id, document_id=document_id),
            )

        if not assets:
            if document_type not in _IMAGE_REEMBEDDABLE_DOCUMENT_TYPES:
                return DocumentImagesToolbarState()
            decision = self._runtime.task_engine.preflight(
                "image_reembedding",
                project_id,
                {"document_ids": [document_id], "force": False},
                TaskAction.RUN,
            )
            blocker = (
                self._image_decision_to_blocker(
                    project_id,
                    document_id=document_id,
                    decision_code=decision.code or "",
                    reason=decision.reason or "",
                    default_target=NavigationTargetKind.DOCUMENT_IMAGES,
                )
                if not decision.allowed
                else make_blocker(
                    BlockerCode.NOTHING_TO_DO,
                    "No translated images are ready for reinsertion.",
                    target_kind=NavigationTargetKind.DOCUMENT_IMAGES,
                    project_id=project_id,
                    document_id=document_id,
                )
            )
            return DocumentImagesToolbarState(run_pending_blocker=blocker, force_all_blocker=blocker)

        pending_assets = [asset for asset in assets if asset.status is not SurfaceStatus.DONE]
        pending_allowed, pending_blocker = self._run_image_action_state(
            project_id,
            document_id=document_id,
            source_id=None,
            force_all=False,
            empty_blocker=make_blocker(
                BlockerCode.NOTHING_TO_DO,
                "No pending images need reinsertion.",
                target_kind=NavigationTargetKind.DOCUMENT_IMAGES,
                project_id=project_id,
                document_id=document_id,
            ),
            has_work=bool(pending_assets),
        )
        force_allowed, force_blocker = self._run_image_action_state(
            project_id,
            document_id=document_id,
            source_id=None,
            force_all=True,
            empty_blocker=None,
            has_work=bool(assets),
        )
        return DocumentImagesToolbarState(
            can_run_pending=pending_allowed,
            can_force_all=force_allowed,
            run_pending_blocker=pending_blocker,
            force_all_blocker=force_blocker,
        )

    def _apply_source_asset_actions(
        self,
        project_id: str,
        *,
        document_id: int,
        document_type: str,
        assets: list[ImageAssetState],
        active_task: TaskRecord | None,
    ) -> list[ImageAssetState]:
        if document_type not in {"manga", "epub"}:
            return assets
        updated: list[ImageAssetState] = []
        for asset in assets:
            if asset.source_id is None:
                updated.append(asset)
                continue
            if active_task is not None:
                updated.append(
                    asset.model_copy(
                        update={
                            "can_run": False,
                            "run_blocker": self._active_task_blocker(project_id=project_id, document_id=document_id),
                        }
                    )
                )
                continue
            allowed, blocker = self._run_image_action_state(
                project_id,
                document_id=document_id,
                source_id=asset.source_id,
                force_all=True,
                empty_blocker=None,
                has_work=True,
            )
            updated.append(asset.model_copy(update={"can_run": allowed, "run_blocker": blocker}))
        return updated

    def _run_image_action_state(
        self,
        project_id: str,
        *,
        document_id: int,
        source_id: int | None,
        force_all: bool,
        empty_blocker: BlockerInfo | None,
        has_work: bool,
    ) -> tuple[bool, BlockerInfo | None]:
        if not has_work:
            return False, empty_blocker
        params: dict[str, object] = {"document_ids": [document_id], "force": force_all}
        if source_id is not None:
            params["source_ids"] = [source_id]
        decision = self._runtime.task_engine.preflight("image_reembedding", project_id, params, TaskAction.RUN)
        if decision.allowed:
            return True, None
        return False, self._image_decision_to_blocker(
            project_id,
            document_id=document_id,
            decision_code=decision.code or "",
            reason=decision.reason or "",
            default_target=NavigationTargetKind.DOCUMENT_IMAGES,
            source_id=source_id,
        )

    def _image_decision_to_blocker(
        self,
        project_id: str,
        *,
        document_id: int,
        decision_code: str,
        reason: str,
        default_target: NavigationTargetKind,
        source_id: int | None = None,
    ) -> BlockerInfo:
        setup_blocker = self._resolve_image_setup_blocker(project_id)
        if setup_blocker is not None:
            return setup_blocker
        lowered = reason.lower()
        if decision_code == "blocked_claim_conflict":
            return self._active_task_blocker(project_id=project_id, document_id=document_id)
        if "translate documents before running image reembedding" in lowered or "no translated chunks found" in lowered:
            return make_blocker(
                BlockerCode.NEEDS_REVIEW,
                "Translate this document before putting text back into images.",
                target_kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
                project_id=project_id,
                document_id=document_id,
            )
        if "source_ids not found" in lowered or source_id is not None:
            return make_blocker(
                BlockerCode.NOTHING_TO_DO,
                reason or "The selected image is no longer available.",
                target_kind=default_target,
                project_id=project_id,
                document_id=document_id,
            )
        if decision_code == "no_manga_ocr_config":
            return make_blocker(
                blocker_code_for_decision_code(decision_code),
                reason or "Image reinsertion is blocked.",
                target_kind=NavigationTargetKind.PROJECT_SETUP,
                project_id=project_id,
                document_id=document_id,
            )
        return make_blocker(
            blocker_code_for_decision_code(decision_code),
            reason or "Image reinsertion is blocked.",
            target_kind=default_target,
            project_id=project_id,
            document_id=document_id,
        )

    def _resolve_image_setup_blocker(self, project_id: str) -> BlockerInfo | None:
        config = self._runtime.get_effective_config_payload(project_id)
        target_language = config.get("translation_target_language")
        if not isinstance(target_language, str) or not target_language.strip():
            return make_blocker(
                BlockerCode.NEEDS_SETUP,
                "Target language is not configured for this project.",
                target_kind=NavigationTargetKind.PROJECT_SETUP,
                project_id=project_id,
            )
        configured_connection_ids = {connection_id for connection_id, _label in self._runtime.list_connection_options()}
        route_map = {route.capability: route.connection_id for route in build_default_routes_from_config(config)}
        image_edit_route = route_map.get(CapabilityCode.IMAGE_EDITING)
        if image_edit_route is None or image_edit_route not in configured_connection_ids:
            return make_blocker(
                BlockerCode.NEEDS_SETUP,
                "Image editing needs a shared connection in App Setup.",
                target_kind=NavigationTargetKind.APP_SETUP,
                project_id=project_id,
            )
        return None

    def _active_task_blocker(self, *, project_id: str | None, document_id: int) -> BlockerInfo:
        return make_blocker(
            BlockerCode.ALREADY_RUNNING_ELSEWHERE,
            "Image reinsertion is already running for this document.",
            target_kind=NavigationTargetKind.DOCUMENT_IMAGES,
            project_id=project_id,
            document_id=document_id,
        )

    @staticmethod
    def _image_label(source: dict[str, Any]) -> str:
        sequence = int(source.get("sequence_number", 0) or 0) + 1
        return f"Image {sequence}"

    def _build_manga_translation_units(
        self,
        project_id: str,
        document_id: int,
        dbx: Any,
    ) -> list[TranslationUnitState]:
        save_blocker = self._translation_save_blocker(project_id, document_id)
        sources = [
            {
                **source,
                "ocr_json": dbx.document_repo.get_source_ocr_json(int(source["source_id"])),
            }
            for source in dbx.document_repo.get_document_sources_metadata(document_id)
            if source.get("source_type") == "image"
        ]
        chunks = sorted(dbx.term_repo.list_chunks(document_id=document_id), key=lambda chunk: int(chunk.chunk_id))
        source_to_chunk = align_sources_to_chunks(sources, len(chunks), strict=False)
        units: list[TranslationUnitState] = []
        for source_index, source in enumerate(sources):
            source_id = int(source["source_id"])
            page_number = int(source.get("sequence_number", 0)) + 1
            source_text = extract_ocr_text(source.get("ocr_json"))
            chunk_index = source_to_chunk.get(source_index)
            chunk = chunks[chunk_index] if chunk_index is not None and chunk_index < len(chunks) else None

            if not source_text.strip():
                blocker = make_blocker(
                    BlockerCode.NOTHING_TO_DO,
                    "No OCR text detected on this page.",
                    target_kind=NavigationTargetKind.DOCUMENT_OCR,
                    project_id=project_id,
                    document_id=document_id,
                )
                units.append(
                    TranslationUnitState(
                        unit_id=str(source_id),
                        unit_kind=TranslationUnitKind.PAGE,
                        label=f"Page {page_number}",
                        status=SurfaceStatus.BLOCKED,
                        source_text="",
                        translated_text=None,
                        source_id=source_id,
                        actions=TranslationUnitActionState(
                            can_save=False,
                            can_retranslate=False,
                            save_blocker=blocker,
                            retranslate_blocker=blocker,
                        ),
                        blocker=blocker,
                    )
                )
                continue

            if chunk is None:
                blocker = make_blocker(
                    BlockerCode.NEEDS_REVIEW,
                    "This page could not be aligned to a translation unit. Rebuild terms after OCR changes.",
                    target_kind=NavigationTargetKind.DOCUMENT_TERMS,
                    project_id=project_id,
                    document_id=document_id,
                )
                units.append(
                    TranslationUnitState(
                        unit_id=str(source_id),
                        unit_kind=TranslationUnitKind.PAGE,
                        label=f"Page {page_number}",
                        status=SurfaceStatus.BLOCKED,
                        source_text=source_text,
                        translated_text=None,
                        line_count=self._line_count(source_text),
                        source_id=source_id,
                        actions=TranslationUnitActionState(
                            can_save=False,
                            can_retranslate=False,
                            save_blocker=blocker,
                            retranslate_blocker=blocker,
                        ),
                        blocker=blocker,
                    )
                )
                continue

            retranslate_allowed, retranslate_blocker = self._retranslate_action_state_for_manga_page(
                project_id,
                document_id,
                source_id,
            )
            units.append(
                TranslationUnitState(
                    unit_id=str(source_id),
                    unit_kind=TranslationUnitKind.PAGE,
                    label=f"Page {page_number}",
                    status=SurfaceStatus.DONE if chunk.is_translated else SurfaceStatus.READY,
                    source_text=source_text,
                    translated_text=chunk.translation,
                    line_count=self._line_count(source_text),
                    source_id=source_id,
                    actions=TranslationUnitActionState(
                        can_save=save_blocker is None,
                        can_retranslate=retranslate_allowed,
                        save_blocker=save_blocker,
                        retranslate_blocker=retranslate_blocker,
                    ),
                )
            )
        return units

    def _translation_save_blocker(self, project_id: str, document_id: int) -> Any:
        wanted = frozenset({ResourceClaim("doc", project_id, str(document_id), ClaimMode.WRITE_EXCLUSIVE)})
        if self._runtime.task_engine.has_active_claims(project_id, wanted):
            return make_blocker(
                BlockerCode.ALREADY_RUNNING_ELSEWHERE,
                "Cannot save while another task is actively modifying this document.",
                target_kind=NavigationTargetKind.QUEUE,
                project_id=project_id,
                document_id=document_id,
            )
        return None

    def _translation_run_action_state(
        self,
        project_id: str,
        *,
        document_id: int,
        document_type: str,
        enable_polish: bool,
        batch: bool,
        has_work: bool,
        active_task: TaskRecord | None,
    ) -> tuple[bool, BlockerInfo | None]:
        if active_task is not None:
            return False, self._translation_active_task_blocker(project_id=project_id, document_id=document_id)
        if not has_work:
            return (
                False,
                make_blocker(
                    BlockerCode.NOTHING_TO_DO,
                    "No translatable units are ready in this document.",
                    target_kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
                    project_id=project_id,
                    document_id=document_id,
                ),
            )
        if batch and document_type == "manga":
            return False, None
        task_type = (
            "batch_translation" if batch else ("translation_manga" if document_type == "manga" else "translation_text")
        )
        decision = self._runtime.task_engine.preflight(
            task_type,
            project_id,
            {"document_ids": [document_id], "enable_polish": enable_polish},
            TaskAction.RUN,
        )
        return self._translation_decision_to_action_state(
            project_id,
            decision,
            document_id=document_id,
            batch=batch,
        )

    def _translation_decision_to_action_state(
        self,
        project_id: str,
        decision: Any,
        *,
        document_id: int,
        batch: bool,
    ) -> tuple[bool, BlockerInfo | None]:
        if decision.allowed:
            return True, None
        reason = decision.reason or (
            "Async batch translation is unavailable." if batch else "Translation is unavailable."
        )
        lowered = reason.lower()
        target_kind = NavigationTargetKind.DOCUMENT_TRANSLATION
        if decision.code == "blocked_claim_conflict":
            return False, self._translation_active_task_blocker(project_id=project_id, document_id=document_id)
        if "setup" in lowered or "config snapshot" in lowered:
            target_kind = NavigationTargetKind.APP_SETUP
        return False, make_blocker(
            blocker_code_for_decision_code(decision.code or ""),
            reason,
            target_kind=target_kind,
            project_id=project_id,
            document_id=document_id,
        )

    def _translation_active_task_blocker(self, *, project_id: str, document_id: int) -> BlockerInfo:
        return make_blocker(
            BlockerCode.ALREADY_RUNNING_ELSEWHERE,
            "Translation is already running for this document.",
            target_kind=NavigationTargetKind.QUEUE,
            project_id=project_id,
            document_id=document_id,
        )

    def _retranslate_action_state_for_chunk(
        self,
        project_id: str,
        document_id: int,
        chunk_id: int,
    ) -> tuple[bool, Any]:
        decision = self._runtime.task_engine.preflight(
            "chunk_retranslation",
            project_id,
            {"chunk_id": chunk_id, "document_id": document_id},
            TaskAction.RUN,
        )
        return self._decision_to_action_state(
            project_id,
            decision,
            document_id=document_id,
            target_kind=NavigationTargetKind.QUEUE,
            default_reason="Retranslate is currently unavailable.",
        )

    def _retranslate_action_state_for_manga_page(
        self,
        project_id: str,
        document_id: int,
        source_id: int,
    ) -> tuple[bool, Any]:
        decision = self._runtime.task_engine.preflight(
            "translation_manga",
            project_id,
            {"document_ids": [document_id], "source_ids": [source_id], "force": True},
            TaskAction.RUN,
        )
        return self._decision_to_action_state(
            project_id,
            decision,
            document_id=document_id,
            target_kind=NavigationTargetKind.QUEUE,
            default_reason="Retranslate is currently unavailable.",
        )

    def _active_translation_task(self, project_id: str, document_id: int) -> TaskRecord | None:
        records = self._runtime.task_store.list_tasks(
            book_id=project_id,
            exclude_statuses=TERMINAL_TASK_STATUSES,
        )
        relevant = [record for record in records if self._record_targets_translation_document(record, document_id)]
        if not relevant:
            return None
        return sorted(relevant, key=self._translation_task_sort_key, reverse=True)[0]

    def _record_targets_translation_document(self, record: TaskRecord, document_id: int) -> bool:
        if record.task_type not in {
            "translation_text",
            "translation_manga",
            "chunk_retranslation",
            "batch_translation",
        }:
            return False
        if record.document_ids_json is None:
            return record.task_type != "chunk_retranslation"
        try:
            document_ids = json.loads(record.document_ids_json)
        except json.JSONDecodeError:
            return False
        if not isinstance(document_ids, list):
            return False
        try:
            normalized = {int(value) for value in document_ids}
        except (TypeError, ValueError):
            return False
        return document_id in normalized

    @staticmethod
    def _translation_task_sort_key(record: TaskRecord) -> tuple[int, float]:
        status_priority = 1 if record.status == "running" else 0
        return (status_priority, float(record.updated_at))

    def _resolve_manga_chunk_for_source(self, *, dbx: Any, document_id: int, source_id: int) -> Any:
        sources = [
            {
                **source,
                "ocr_json": dbx.document_repo.get_source_ocr_json(int(source["source_id"])),
            }
            for source in dbx.document_repo.get_document_sources_metadata(document_id)
            if source.get("source_type") == "image"
        ]
        chunks = sorted(dbx.term_repo.list_chunks(document_id=document_id), key=lambda chunk: int(chunk.chunk_id))
        source_ids = [int(source["source_id"]) for source in sources]
        try:
            source_index = source_ids.index(int(source_id))
        except ValueError:
            return None
        mapping = align_sources_to_chunks(sources, len(chunks), strict=False)
        chunk_index = mapping.get(source_index)
        if chunk_index is None or chunk_index >= len(chunks):
            return None
        return chunks[chunk_index]

    @staticmethod
    def _line_count(text: str | None) -> int:
        if text is None:
            return 0
        stripped = text.strip()
        if not stripped:
            return 0
        return len(text.splitlines())

    @staticmethod
    def _raise_blocked_blocker(blocker: Any, **details: str | int | float | bool | None) -> None:
        raise BlockedOperationError(
            ApplicationErrorPayload(
                code=ApplicationErrorCode.BLOCKED,
                message=blocker.message,
                details={"decision_code": blocker.code.value, **details},
            )
        )


def raise_blocked_or_not_found_for_manga_unit(*, project_id: str, document_id: int, source_id: int) -> None:
    blocker = make_blocker(
        BlockerCode.NEEDS_REVIEW,
        "This manga page cannot be edited because it is not aligned to a translation unit.",
        target_kind=NavigationTargetKind.DOCUMENT_TERMS,
        project_id=project_id,
        document_id=document_id,
    )
    raise BlockedOperationError(
        ApplicationErrorPayload(
            code=ApplicationErrorCode.BLOCKED,
            message=blocker.message,
            details={"decision_code": blocker.code.value, "source_id": source_id},
        )
    )
