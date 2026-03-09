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
)
from context_aware_translation.application.contracts.work import (
    ContextFrontierState,
    DocumentRowAction,
    ExportDialogState,
    ImportDocumentsRequest,
    PrepareExportRequest,
    RunExportRequest,
    WorkboardState,
    WorkDocumentRow,
)
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    build_default_routes_from_config,
    make_blocker,
    map_document_type_code,
    raise_application_error,
)
from context_aware_translation.application.services._export_support import (
    prepare_export,
    run_export,
    to_export_dialog_state,
)
from context_aware_translation.documents.base import is_ocr_required_for_type

_IMAGE_DOCUMENT_TYPES = {"manga", "pdf", "epub", "scanned_book"}


class WorkService(Protocol):
    def get_workboard(self, project_id: str) -> WorkboardState: ...

    def import_documents(self, request: ImportDocumentsRequest) -> AcceptedCommand: ...

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
            document_sources = {
                int(doc["document_id"]): dbx.document_repo.get_document_sources_metadata(int(doc["document_id"]))
                for doc in docs
            }
            pending_glossary_ids = {
                int(doc["document_id"]) for doc in dbx.document_repo.list_documents_pending_glossary()
            }
            pending_translation_ids = {
                int(doc["document_id"]) for doc in dbx.document_repo.list_documents_pending_translation()
            }
        setup_blocker = self._resolve_setup_blocker(project_id, config, docs)

        rows: list[WorkDocumentRow] = []
        frontier_last_ready = None
        blocking_doc_id: int | None = None
        blocking_message: str | None = None
        for order_index, doc in enumerate(docs, start=1):
            document_id = int(doc["document_id"])
            document_type = str(doc.get("document_type") or "")
            total_chunks = int(doc.get("total_chunks", 0) or 0)
            translated_chunks = int(doc.get("chunks_translated", 0) or 0)
            ocr_pending = int(doc.get("ocr_pending", 0) or 0)
            ref = self._build_document_ref(
                document_id=document_id,
                document_type=document_type,
                order_index=order_index,
                sources=document_sources.get(document_id, []),
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
            elif document_id in pending_glossary_ids:
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
            elif document_id in pending_translation_ids or (total_chunks > 0 and translated_chunks < total_chunks):
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
                        kind=NavigationTargetKind.DOCUMENT_OVERVIEW,
                        project_id=project_id,
                        document_id=document_id,
                    ),
                )

            rows.append(
                WorkDocumentRow(
                    document=ref,
                    status=status,
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
        sources: list[dict],
    ) -> DocumentRef:
        label = f"Document {order_index}"
        if sources:
            first_source = sources[0]
            relative_path = str(first_source.get("relative_path") or "").strip()
            if relative_path:
                label = Path(relative_path).name
            else:
                sequence_number = int(first_source.get("sequence_number", 1) or 1)
                label = f"{document_type.replace('_', ' ').title()} {sequence_number}"

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

    def import_documents(self, request: ImportDocumentsRequest) -> AcceptedCommand:
        raise_application_error(
            ApplicationErrorCode.UNSUPPORTED,
            "Document import is still owned by the existing import flow and has not been migrated into the application layer yet.",
            project_id=request.project_id,
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
