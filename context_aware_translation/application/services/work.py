from __future__ import annotations

from pathlib import Path
from typing import Protocol

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
    CapabilityCode,
    DocumentRef,
    DocumentRowActionKind,
    DocumentSection,
    ExportResult,
    NavigationTarget,
    NavigationTargetKind,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.work import (
    ContextFrontierState,
    DeleteDocumentStackRequest,
    DocumentRowAction,
    ExportDialogState,
    ImportDocumentsRequest,
    ImportDocumentTypeOption,
    ImportInspectionState,
    InspectImportPathsRequest,
    PrepareExportRequest,
    ResetDocumentStackRequest,
    RunExportRequest,
    WorkboardState,
    WorkDocumentRow,
    WorkMutationResult,
)
from context_aware_translation.application.errors import (
    ApplicationErrorCode,
    ApplicationErrorPayload,
    BlockedOperationError,
)
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    build_default_routes_from_config,
    make_blocker,
    map_document_type_code,
)
from context_aware_translation.application.services._export_support import (
    prepare_export,
    run_export,
    to_export_dialog_state,
)
from context_aware_translation.documents.base import is_ocr_required_for_type
from context_aware_translation.workflow.ops.import_support import (
    get_compatible_document_classes_for_paths,
    import_via_repository,
)
from context_aware_translation.workflow.tasks.claims import ClaimMode, ResourceClaim

_IMAGE_DOCUMENT_TYPES = {"manga", "pdf", "epub", "scanned_book"}


class WorkService(Protocol):
    def get_workboard(self, project_id: str) -> WorkboardState: ...

    def inspect_import_paths(self, request: InspectImportPathsRequest) -> ImportInspectionState: ...

    def import_documents(self, request: ImportDocumentsRequest) -> AcceptedCommand: ...

    def reset_document_stack(self, request: ResetDocumentStackRequest) -> WorkMutationResult: ...

    def delete_document_stack(self, request: DeleteDocumentStackRequest) -> WorkMutationResult: ...

    def prepare_export(self, request: PrepareExportRequest) -> ExportDialogState: ...

    def run_export(self, request: RunExportRequest) -> ExportResult: ...


class DefaultWorkService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_workboard(self, project_id: str) -> WorkboardState:
        project = self._runtime.get_project_ref(project_id)
        config = self._runtime.get_effective_config_payload(project_id)
        with self._runtime.open_book_db(project_id) as dbx:
            docs = dbx.document_repo.get_documents_with_status()
        setup_blocker = self._resolve_setup_blocker(project_id, config, docs)

        rows: list[WorkDocumentRow] = []
        frontier_last_ready = None
        blocking_doc_id: int | None = None
        blocking_message: str | None = None
        for order_index, doc in enumerate(docs, start=1):
            document_id = int(doc["document_id"])
            document_type = str(doc.get("document_type") or "")
            total_chunks = int(doc.get("total_chunks", 0) or 0)
            extracted_chunks = int(doc.get("chunks_extracted", 0) or 0)
            mapped_chunks = int(doc.get("chunks_mapped", 0) or 0)
            translated_chunks = int(doc.get("chunks_translated", 0) or 0)
            ocr_pending = int(doc.get("ocr_pending", 0) or 0)
            text_pending_ready = int(doc.get("text_pending_ready", 0) or 0)
            ref = self._build_document_ref(
                document_id=document_id,
                document_type=document_type,
                order_index=order_index,
                first_source_relative_path=str(doc.get("first_source_relative_path") or ""),
                first_source_sequence_number=int(doc.get("first_source_sequence_number", 1) or 1),
            )

            if blocking_doc_id is not None and document_id > blocking_doc_id:
                row_blocker = make_blocker(
                    BlockerCode.NEEDS_EARLIER_DOCUMENT_FIRST,
                    f"Waiting for Document {blocking_doc_id} before continuing in order.",
                    target_kind=NavigationTargetKind.WORK,
                    project_id=project_id,
                    document_id=blocking_doc_id,
                )
                rows.append(
                    WorkDocumentRow(
                        document=ref,
                        status=SurfaceStatus.BLOCKED,
                        state_summary="Waiting in order",
                        blocker=row_blocker,
                        primary_action=DocumentRowAction(
                            kind=DocumentRowActionKind.BLOCKED,
                            label="Blocked",
                            blocker=row_blocker,
                        ),
                    )
                )
                continue

            blocker: BlockerInfo | None = None
            if setup_blocker is not None:
                blocker = setup_blocker
                status = SurfaceStatus.BLOCKED
                summary = "Needs setup"
                action = DocumentRowAction(
                    kind=DocumentRowActionKind.FIX_SETUP,
                    label="Open Setup",
                    target=NavigationTarget(kind=NavigationTargetKind.PROJECT_SETUP, project_id=project_id),
                    blocker=blocker,
                )
            elif is_ocr_required_for_type(document_type) and ocr_pending > 0:
                status = SurfaceStatus.READY
                summary = "Needs OCR review"
                action = DocumentRowAction(
                    kind=DocumentRowActionKind.OPEN_OCR,
                    label="Open OCR",
                    target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_OCR,
                        project_id=project_id,
                        document_id=document_id,
                    ),
                )
                blocking_doc_id = document_id
                blocking_message = summary
            elif text_pending_ready > 0 or (total_chunks > 0 and (extracted_chunks < total_chunks or mapped_chunks < total_chunks)):
                status = SurfaceStatus.READY
                summary = "Open Terms to build terms"
                action = DocumentRowAction(
                    kind=DocumentRowActionKind.OPEN_TERMS,
                    label="Open Terms",
                    target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_TERMS,
                        project_id=project_id,
                        document_id=document_id,
                    ),
                )
                blocking_doc_id = document_id
                blocking_message = summary
            elif total_chunks > 0 and translated_chunks < total_chunks:
                status = SurfaceStatus.READY
                summary = "Open Translation"
                action = DocumentRowAction(
                    kind=DocumentRowActionKind.OPEN_TRANSLATION,
                    label="Open Translation",
                    target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
                        project_id=project_id,
                        document_id=document_id,
                    ),
                )
                blocking_doc_id = document_id
                blocking_message = summary
            elif document_type in _IMAGE_DOCUMENT_TYPES and total_chunks > 0:
                status = SurfaceStatus.DONE
                summary = "Inspect images"
                action = DocumentRowAction(
                    kind=DocumentRowActionKind.OPEN_IMAGES,
                    label="Open Images",
                    target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_IMAGES,
                        project_id=project_id,
                        document_id=document_id,
                    ),
                )
                frontier_last_ready = ref
            elif total_chunks > 0 and translated_chunks == total_chunks:
                status = SurfaceStatus.DONE
                summary = "Ready to export"
                action = DocumentRowAction(kind=DocumentRowActionKind.EXPORT, label="Export")
                frontier_last_ready = ref
            else:
                status = SurfaceStatus.READY
                summary = "Open"
                action = DocumentRowAction(
                    kind=DocumentRowActionKind.OPEN,
                    label="Open",
                    target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_OCR,
                        project_id=project_id,
                        document_id=document_id,
                    ),
                )

            rows.append(
                WorkDocumentRow(
                    document=ref,
                    status=status,
                    source_count=int(doc.get("total_sources", 0) or 0),
                    ocr_status=self._ocr_summary(doc),
                    terms_status=self._terms_summary(doc),
                    translation_status=self._translation_summary(doc),
                    state_summary=summary,
                    blocker=blocker,
                    primary_action=action,
                )
            )
        context_frontier = ContextFrontierState(
            summary=(
                f"Context ready through Document {frontier_last_ready.document_id}."
                if frontier_last_ready is not None
                else "Context not ready yet."
            ),
            last_ready_document=frontier_last_ready,
            blocker=(
                make_blocker(
                    BlockerCode.NEEDS_REVIEW,
                    f"Blocked by {blocking_message or 'pending work'} on Document {blocking_doc_id}.",
                    target_kind=NavigationTargetKind.WORK,
                    project_id=project_id,
                    document_id=blocking_doc_id,
                )
                if blocking_doc_id is not None
                else None
            ),
        )
        return WorkboardState(
            project=project, context_frontier=context_frontier, rows=rows, setup_blocker=setup_blocker
        )

    def _resolve_setup_blocker(
        self,
        project_id: str,
        config: dict[str, object],
        docs: list[dict],
    ) -> BlockerInfo | None:
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
        if self._is_missing_route(route_map.get(CapabilityCode.TRANSLATION), configured_connection_ids):
            return make_blocker(
                BlockerCode.NEEDS_SETUP,
                "Translation needs a shared connection in App Setup.",
                target_kind=NavigationTargetKind.APP_SETUP,
                project_id=project_id,
            )

        needs_image_text_reading = any(is_ocr_required_for_type(str(doc.get("document_type") or "")) for doc in docs)
        if needs_image_text_reading and self._is_missing_route(
            route_map.get(CapabilityCode.IMAGE_TEXT_READING),
            configured_connection_ids,
        ):
            return make_blocker(
                BlockerCode.NEEDS_SETUP,
                "Image text reading needs a shared connection in App Setup.",
                target_kind=NavigationTargetKind.APP_SETUP,
                project_id=project_id,
            )
        return None

    def _build_document_ref(
        self,
        *,
        document_id: int,
        document_type: str,
        order_index: int,
        first_source_relative_path: str,
        first_source_sequence_number: int,
    ) -> DocumentRef:
        label = f"Document {order_index}"
        relative_path = first_source_relative_path.strip()
        if relative_path:
            label = Path(relative_path).name
        elif first_source_sequence_number > 0:
            label = f"{document_type.replace('_', ' ').title()} {first_source_sequence_number}"

        return DocumentRef(
            document_id=document_id,
            order_index=order_index,
            label=label,
            document_type=map_document_type_code(document_type),
        )

    @staticmethod
    def _is_missing_route(connection_id: str | None, configured_connection_ids: set[str]) -> bool:
        if connection_id is None:
            return True
        return connection_id not in configured_connection_ids

    def inspect_import_paths(self, request: InspectImportPathsRequest) -> ImportInspectionState:
        paths = [Path(path) for path in request.paths]
        try:
            matches = get_compatible_document_classes_for_paths(paths)
        except ValueError as exc:
            return ImportInspectionState(
                selected_paths=[str(path) for path in paths],
                summary=", ".join(path.name for path in paths),
                error_message=str(exc),
            )
        return ImportInspectionState(
            selected_paths=[str(path) for path in paths],
            summary=", ".join(path.name for path in paths),
            available_types=[
                ImportDocumentTypeOption(
                    document_type=str(getattr(cls, "document_type", "")),
                    label=str(getattr(cls, "document_type", "")).replace("_", " ").title(),
                )
                for cls in matches
            ],
        )

    def import_documents(self, request: ImportDocumentsRequest) -> AcceptedCommand:
        blocker = self._document_mutation_blocker(request.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.project_id)
        with self._runtime.open_book_db(request.project_id) as dbx:
            result = import_via_repository(
                dbx.document_repo,
                paths=[Path(path) for path in request.paths],
                document_type=request.document_type,
            )
        self._runtime.invalidate_workboard(request.project_id)
        self._runtime.invalidate_projects()
        return AcceptedCommand(
            command_name="import_documents",
            message=UserMessage(
                severity=UserMessageSeverity.SUCCESS,
                text=f"Imported {result['imported']} document(s); skipped {result['skipped']}.",
            ),
        )

    def reset_document_stack(self, request: ResetDocumentStackRequest) -> WorkMutationResult:
        blocker = self._document_mutation_blocker(request.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.project_id, document_id=request.document_id)
        context_tree_path = self._runtime.book_manager.get_book_context_tree_path(request.project_id)
        with self._runtime.open_book_db(request.project_id) as dbx:
            result = dbx.document_repo.reset_document_stack(request.document_id, context_tree_db_path=context_tree_path)
        self._runtime.invalidate_workboard(request.project_id)
        self._runtime.invalidate_terms(request.project_id)
        self._runtime.invalidate_document(request.project_id)
        return WorkMutationResult(
            message=UserMessage(
                severity=UserMessageSeverity.SUCCESS,
                text=(
                    f"Reset {len(result.get('affected_document_ids', []))} document(s); "
                    f"deleted {result.get('deleted_chunks', 0)} chunks and deleted {result.get('deleted_terms', 0)} terms."
                ),
            )
        )

    def delete_document_stack(self, request: DeleteDocumentStackRequest) -> WorkMutationResult:
        blocker = self._document_mutation_blocker(request.project_id)
        if blocker is not None:
            self._raise_blocked_blocker(blocker, project_id=request.project_id, document_id=request.document_id)
        context_tree_path = self._runtime.book_manager.get_book_context_tree_path(request.project_id)
        with self._runtime.open_book_db(request.project_id) as dbx:
            result = dbx.document_repo.delete_documents_stack(
                request.document_id, context_tree_db_path=context_tree_path
            )
        self._runtime.invalidate_workboard(request.project_id)
        self._runtime.invalidate_terms(request.project_id)
        self._runtime.invalidate_document(request.project_id)
        self._runtime.invalidate_projects()
        return WorkMutationResult(
            message=UserMessage(
                severity=UserMessageSeverity.SUCCESS,
                text=(
                    f"Deleted {result.get('deleted_documents', 0)} document(s), "
                    f"{result.get('deleted_sources', 0)} sources, and {result.get('deleted_chunks', 0)} chunks."
                ),
            )
        )

    def prepare_export(self, request: PrepareExportRequest) -> ExportDialogState:
        return to_export_dialog_state(
            prepare_export(self._runtime, project_id=request.project_id, document_ids=request.document_ids)
        )

    def run_export(self, request: RunExportRequest) -> ExportResult:
        result = run_export(
            self._runtime,
            project_id=request.project_id,
            document_ids=request.document_ids,
            format_id=request.format_id,
            output_path=request.output_path,
            options=request.options,
        )
        self._runtime.invalidate_workboard(request.project_id)
        for document_id in request.document_ids:
            self._runtime.invalidate_document(
                request.project_id,
                document_id,
                sections=[DocumentSection.EXPORT],
            )
        return result

    @staticmethod
    def _ocr_summary(doc: dict) -> str:
        pending = int(doc.get("ocr_pending", 0) or 0)
        completed = int(doc.get("ocr_completed", 0) or 0)
        if pending > 0:
            return f"Pending ({pending})"
        if completed > 0:
            return "Complete"
        return "N/A"

    @staticmethod
    def _terms_summary(doc: dict) -> str:
        total = int(doc.get("total_chunks", 0) or 0)
        if total == 0:
            return "Not started"
        extracted = int(doc.get("chunks_extracted", 0) or 0)
        mapped = int(doc.get("chunks_mapped", 0) or 0)
        if extracted == total and mapped == total:
            return "Complete"
        if extracted > 0 or mapped > 0:
            return f"In progress ({mapped}/{total})"
        return "Not started"

    @staticmethod
    def _translation_summary(doc: dict) -> str:
        total = int(doc.get("total_chunks", 0) or 0)
        translated = int(doc.get("chunks_translated", 0) or 0)
        if total == 0:
            return "Not started"
        if translated == total:
            return "Complete"
        if translated > 0:
            return f"In progress ({translated}/{total})"
        return "Not started"

    def _document_mutation_blocker(self, project_id: str) -> BlockerInfo | None:
        wanted = frozenset(
            {
                ResourceClaim("doc", project_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                ResourceClaim("glossary_state", project_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                ResourceClaim("context_tree", project_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                ResourceClaim("ocr", project_id, "*", ClaimMode.WRITE_EXCLUSIVE),
            }
        )
        if self._runtime.task_engine.has_active_claims(project_id, wanted):
            return make_blocker(
                BlockerCode.ALREADY_RUNNING_ELSEWHERE,
                "Cannot modify documents while other document tasks are active.",
                target_kind=NavigationTargetKind.QUEUE,
                project_id=project_id,
            )
        return None

    @staticmethod
    def _raise_blocked_blocker(blocker: BlockerInfo, **details: str | int | float | bool | None) -> None:
        raise BlockedOperationError(
            ApplicationErrorPayload(
                code=ApplicationErrorCode.BLOCKED,
                message=blocker.message,
                details={"decision_code": blocker.code.value, **details},
            )
        )
