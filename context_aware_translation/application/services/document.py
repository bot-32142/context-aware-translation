from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Protocol

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    ActionState,
    BlockerCode,
    BlockerInfo,
    DocumentSection,
    ExportOption,
    NavigationTargetKind,
    ProgressInfo,
    SurfaceStatus,
)
from context_aware_translation.application.contracts.document import (
    DocumentExportResult,
    DocumentExportState,
    DocumentImagesState,
    DocumentOCRActions,
    DocumentOCRState,
    DocumentOverviewState,
    DocumentSectionCard,
    DocumentTranslationState,
    DocumentWorkspaceState,
    ImageAssetState,
    OCRPageState,
    OCRTextElement,
    RetranslateRequest,
    RunDocumentExportRequest,
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
    make_blocker,
    make_document_ref,
    progress_from_task,
    raise_application_error,
)
from context_aware_translation.documents.base import get_supported_formats_for_type
from context_aware_translation.documents.content.ocr_content import SinglePageOCRContent
from context_aware_translation.documents.manga_alignment import align_sources_to_chunks, extract_ocr_text
from context_aware_translation.storage.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import ClaimMode, ResourceClaim
from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES, TaskAction


class DocumentService(Protocol):
    def get_workspace(self, project_id: str, document_id: int) -> DocumentWorkspaceState: ...

    def get_overview(self, project_id: str, document_id: int) -> DocumentOverviewState: ...

    def get_ocr(self, project_id: str, document_id: int) -> DocumentOCRState: ...

    def get_ocr_page_image(self, project_id: str, document_id: int, source_id: int) -> bytes | None: ...

    def save_ocr(self, request: SaveOCRPageRequest) -> DocumentOCRState: ...

    def run_ocr(self, request: RunOCRRequest) -> AcceptedCommand: ...

    def get_terms(self, project_id: str, document_id: int) -> TermsTableState: ...

    def get_translation(self, project_id: str, document_id: int) -> DocumentTranslationState: ...

    def save_translation(self, request: SaveTranslationRequest) -> DocumentTranslationState: ...

    def retranslate(self, request: RetranslateRequest) -> AcceptedCommand: ...

    def get_images(self, project_id: str, document_id: int) -> DocumentImagesState: ...

    def run_image_reinsertion(self, request: RunImageReinsertionRequest) -> AcceptedCommand: ...

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
            active_tab=DocumentSection.OVERVIEW,
            available_tabs=[
                DocumentSection.OVERVIEW,
                DocumentSection.OCR,
                DocumentSection.TERMS,
                DocumentSection.TRANSLATION,
                DocumentSection.IMAGES,
                DocumentSection.EXPORT,
            ],
        )

    def get_overview(self, project_id: str, document_id: int) -> DocumentOverviewState:
        workspace = self.get_workspace(project_id, document_id)
        with self._runtime.open_book_db(project_id) as dbx:
            status_rows = {int(doc["document_id"]): doc for doc in dbx.document_repo.get_documents_with_status()}
            status = status_rows.get(document_id)
            if status is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {document_id}")
            sections = [
                DocumentSectionCard(section=DocumentSection.OCR, status=SurfaceStatus.READY if int(status.get("ocr_pending", 0) or 0) > 0 else SurfaceStatus.DONE, summary="OCR"),
                DocumentSectionCard(section=DocumentSection.TERMS, status=SurfaceStatus.READY if int(status.get("chunks_extracted", 0) or 0) < int(status.get("total_chunks", 0) or 0) else SurfaceStatus.DONE, summary="Terms"),
                DocumentSectionCard(section=DocumentSection.TRANSLATION, status=SurfaceStatus.READY if int(status.get("chunks_translated", 0) or 0) < int(status.get("total_chunks", 0) or 0) else SurfaceStatus.DONE, summary="Translation"),
                DocumentSectionCard(section=DocumentSection.IMAGES, status=SurfaceStatus.READY, summary="Images"),
                DocumentSectionCard(section=DocumentSection.EXPORT, status=SurfaceStatus.READY if int(status.get("chunks_translated", 0) or 0) >= int(status.get("total_chunks", 0) or 0) and int(status.get("total_chunks", 0) or 0) > 0 else SurfaceStatus.BLOCKED, summary="Export"),
            ]
        return DocumentOverviewState(workspace=workspace, sections=sections)

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
                        and (
                            active_source_ids is None
                            or int(source["source_id"]) in active_source_ids
                        )
                    ),
                )
                for source in image_sources
            ]
            total_pages = len(pages)
            pages = [
                page.model_copy(update={"total_pages": total_pages})
                for page in pages
            ]
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
            blocker = self._ocr_mutation_blocker(request.project_id, request.document_id, chunk_count=dbx.document_repo.get_chunk_count(request.document_id))
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
            if not any(int(source["source_id"]) == int(request.source_id) for source in sources if source.get("source_type") == "image"):
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
        self._runtime.invalidate_document(
            request.project_id,
            request.document_id,
            sections=[DocumentSection.OCR, DocumentSection.OVERVIEW, DocumentSection.TERMS],
        )
        self._runtime.invalidate_workboard(request.project_id)
        return self.get_ocr(request.project_id, request.document_id)

    def run_ocr(self, request: RunOCRRequest) -> AcceptedCommand:
        params: dict[str, object] = {"document_ids": [request.document_id]}
        if request.source_id is not None:
            params["source_ids"] = [request.source_id]
        return self._runtime.submit_task("ocr", request.project_id, **params)

    def get_terms(self, project_id: str, document_id: int) -> TermsTableState:
        from context_aware_translation.application.services.terms import DefaultTermsService

        return DefaultTermsService(self._runtime).get_document_terms(project_id, document_id)

    def get_translation(self, project_id: str, document_id: int) -> DocumentTranslationState:
        workspace = self.get_workspace(project_id, document_id).model_copy(update={"active_tab": DocumentSection.TRANSLATION})
        with self._runtime.open_book_db(project_id) as dbx:
            doc = dbx.document_repo.get_document_by_id(document_id)
            if doc is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {document_id}")
            units = self._build_translation_units(
                project_id,
                document_id,
                document_type=str(doc.get("document_type") or ""),
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
        return DocumentTranslationState(
            workspace=workspace,
            units=units,
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
            sections=[DocumentSection.TRANSLATION, DocumentSection.OVERVIEW, DocumentSection.IMAGES, DocumentSection.EXPORT],
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
            chunk_id=int(request.unit_id),
            document_id=request.document_id,
        )

    def get_images(self, project_id: str, document_id: int) -> DocumentImagesState:
        workspace = self.get_workspace(project_id, document_id).model_copy(update={"active_tab": DocumentSection.IMAGES})
        with self._runtime.open_book_db(project_id) as dbx:
            sources = dbx.document_repo.get_document_sources_metadata(document_id)
            existing = dbx.document_repo.load_reembedded_images(document_id)
            assets = [
                ImageAssetState(
                    asset_id=str(source["source_id"]),
                    label=f"Image {source['sequence_number']}",
                    status=SurfaceStatus.DONE if int(source["source_id"]) in existing else SurfaceStatus.READY,
                    source_id=int(source["source_id"]),
                )
                for source in sources
                if source.get("source_type") == "image"
            ]
        return DocumentImagesState(workspace=workspace, assets=assets)

    def run_image_reinsertion(self, request: RunImageReinsertionRequest) -> AcceptedCommand:
        params: dict[str, object] = {"document_ids": [request.document_id], "force": request.force_all}
        if request.source_id is not None:
            params["source_ids"] = [request.source_id]
        return self._runtime.submit_task("image_reembedding", request.project_id, **params)

    def get_export(self, project_id: str, document_id: int) -> DocumentExportState:
        workspace = self.get_workspace(project_id, document_id).model_copy(update={"active_tab": DocumentSection.EXPORT})
        with self._runtime.open_book_db(project_id) as dbx:
            doc = dbx.document_repo.get_document_by_id(document_id)
            if doc is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {document_id}")
            status = next((row for row in dbx.document_repo.get_documents_with_status() if int(row["document_id"]) == document_id), None)
            if status is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Document not found: {document_id}")
            total_chunks = int(status.get("total_chunks", 0) or 0)
            translated_chunks = int(status.get("chunks_translated", 0) or 0)
            can_export = total_chunks > 0 and translated_chunks >= total_chunks
            available_formats = [ExportOption(format_id=fmt, label=fmt, is_default=(idx == 0)) for idx, fmt in enumerate(get_supported_formats_for_type(str(doc["document_type"]))) ]
        return DocumentExportState(
            workspace=workspace,
            can_export=can_export,
            available_formats=available_formats,
            default_output_path=str(self._runtime.book_manager.get_book_path(project_id) / "export"),
        )

    def export_document(self, request: RunDocumentExportRequest) -> DocumentExportResult:
        raise_application_error(
            ApplicationErrorCode.UNSUPPORTED,
            "Document export execution is still owned by the existing export worker flow and has not been migrated into the application layer yet.",
            project_id=request.project_id,
            document_id=request.document_id,
        )

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
        blocker = self._ocr_mutation_blocker(project_id, document_id, chunk_count=chunk_count, active_task=active_task)
        if blocker is not None:
            disabled = ActionState(enabled=False, blocker=blocker)
            return DocumentOCRActions(save=disabled, run_current=disabled, run_pending=disabled)

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
            save=ActionState(enabled=True),
            run_current=ActionState(enabled=current_allowed, blocker=current_blocker),
            run_pending=ActionState(enabled=pending_allowed, blocker=pending_blocker),
        )

    def _decision_to_action_state(
        self,
        project_id: str,
        decision: Any,
        *,
        document_id: int,
    ) -> tuple[bool, BlockerInfo | None]:
        if decision.allowed:
            return True, None
        return False, make_blocker(
            blocker_code_for_decision_code(decision.code or ""),
            decision.reason or "Operation is blocked.",
            target_kind=NavigationTargetKind.DOCUMENT_OCR,
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
            replacement_lines = [element.text for element in request.elements] if request.elements else (request.extracted_text or "").split("\n")
            content.set_texts(replacement_lines)
            return json.dumps(content.to_json(), ensure_ascii=False)

        if isinstance(payload, dict):
            updated = dict(payload)
            if request.elements and isinstance(updated.get("boxes"), list):
                boxes = list(updated["boxes"])
                if len(boxes) == len(request.elements) and all(isinstance(box, dict) for box in boxes):
                    updated["boxes"] = [
                        {**box, "text": element.text}
                        for box, element in zip(boxes, request.elements, strict=True)
                    ]
                    if "text" in updated:
                        updated["text"] = request.extracted_text if request.extracted_text is not None else "\n".join(
                            element.text for element in request.elements
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
                    "text": request.extracted_text if request.extracted_text is not None else "\n".join(element.text for element in request.elements),
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
                elements = [
                    OCRTextElement(element_id=index, text=text)
                    for index, text in enumerate(content.get_texts())
                ]
                extracted_text = "\n".join(element.text for element in elements)
            elif isinstance(payload, dict):
                if isinstance(payload.get("text"), str):
                    extracted_text = payload.get("text")
                elif isinstance(payload.get("embedded_text"), str):
                    extracted_text = payload.get("embedded_text")
                boxes = payload.get("boxes")
                if isinstance(boxes, list):
                    elements = [
                        OCRTextElement(element_id=index, text=str(box.get("text") or ""))
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
        if decision.allowed:
            return True, None
        return False, make_blocker(
            blocker_code_for_decision_code(decision.code or ""),
            decision.reason or "Retranslate is currently unavailable.",
            target_kind=NavigationTargetKind.QUEUE,
            project_id=project_id,
            document_id=document_id,
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
        if decision.allowed:
            return True, None
        return False, make_blocker(
            blocker_code_for_decision_code(decision.code or ""),
            decision.reason or "Retranslate is currently unavailable.",
            target_kind=NavigationTargetKind.QUEUE,
            project_id=project_id,
            document_id=document_id,
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
        if record.task_type not in {"translation_text", "translation_manga", "chunk_retranslation", "batch_translation"}:
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
