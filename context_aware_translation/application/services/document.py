from __future__ import annotations

import json
from typing import Any, Protocol

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    DocumentSection,
    ExportOption,
    SurfaceStatus,
)
from context_aware_translation.application.contracts.document import (
    DocumentExportResult,
    DocumentExportState,
    DocumentImagesState,
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
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.contracts.terms import TermsTableState
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import ApplicationRuntime, make_document_ref, raise_application_error
from context_aware_translation.documents.base import get_supported_formats_for_type


class DocumentService(Protocol):
    def get_workspace(self, project_id: str, document_id: int) -> DocumentWorkspaceState: ...

    def get_overview(self, project_id: str, document_id: int) -> DocumentOverviewState: ...

    def get_ocr(self, project_id: str, document_id: int) -> DocumentOCRState: ...

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
            pages = [self._build_ocr_page(project_id, source) for source in sources if source.get("source_type") == "image"]
        return DocumentOCRState(workspace=workspace, pages=pages, current_page_index=0 if pages else None)

    def save_ocr(self, request: SaveOCRPageRequest) -> DocumentOCRState:
        payload: dict[str, Any] = {"text": request.extracted_text or ""}
        if request.elements:
            payload["boxes"] = [{"text": element.text} for element in request.elements]
        with self._runtime.open_book_db(request.project_id) as dbx:
            dbx.document_repo.update_source_ocr(request.source_id, json.dumps(payload, ensure_ascii=False))
            dbx.document_repo.update_source_ocr_completed(request.source_id)
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
            chunks = dbx.term_repo.list_chunks(document_id=document_id)
            units = [
                TranslationUnitState(
                    unit_id=str(chunk.chunk_id),
                    unit_kind=TranslationUnitKind.CHUNK,
                    label=f"Chunk {chunk.chunk_id}",
                    status=SurfaceStatus.DONE if chunk.is_translated else SurfaceStatus.READY,
                    source_text=chunk.text,
                    translated_text=chunk.translation,
                    line_count=len(chunk.text.splitlines()) if chunk.text else 0,
                )
                for chunk in chunks
            ]
        return DocumentTranslationState(
            workspace=workspace,
            units=units,
            current_unit_id=units[0].unit_id if units else None,
            terms=self.get_terms(project_id, document_id),
        )

    def save_translation(self, request: SaveTranslationRequest) -> DocumentTranslationState:
        with self._runtime.open_book_db(request.project_id) as dbx:
            chunk = dbx.db.get_chunk_by_id(int(request.unit_id))
            if chunk is None:
                raise_application_error(ApplicationErrorCode.NOT_FOUND, f"Translation unit not found: {request.unit_id}")
            chunk.translation = request.translated_text
            chunk.is_translated = True
            dbx.db.upsert_chunks([chunk])
        return self.get_translation(request.project_id, request.document_id)

    def retranslate(self, request: RetranslateRequest) -> AcceptedCommand:
        return self._runtime.submit_task(
            "chunk_retranslation",
            request.project_id,
            document_ids=[request.document_id],
            chunk_id=int(request.unit_id),
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

    def _build_ocr_page(self, project_id: str, source: dict[str, Any]) -> OCRPageState:
        ocr_json = None
        with self._runtime.open_book_db(project_id) as dbx:
            ocr_json = dbx.document_repo.get_source_ocr_json(int(source["source_id"]))
        extracted_text = None
        elements: list[OCRTextElement] = []
        if ocr_json:
            try:
                payload = json.loads(ocr_json)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
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
            status=SurfaceStatus.DONE if bool(source.get("is_ocr_completed")) else SurfaceStatus.READY,
            image_path=image_path,
            extracted_text=extracted_text,
            elements=elements,
        )
