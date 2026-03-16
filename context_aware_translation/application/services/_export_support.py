from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from context_aware_translation.application.contracts.common import ExportOption, UserMessage, UserMessageSeverity
from context_aware_translation.application.contracts.document import DocumentExportResult
from context_aware_translation.application.contracts.work import ExportDialogState
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import ApplicationRuntime, raise_application_error
from context_aware_translation.documents.base import (
    get_supported_formats_for_type,
    supports_multi_export_for_type,
    supports_preserve_structure_for_type,
)
from context_aware_translation.workflow.ops import export_ops
from context_aware_translation.workflow.session import WorkflowSession


@dataclass(frozen=True)
class PreparedExport:
    project_id: str
    document_ids: list[int]
    document_type: str
    document_labels: list[str]
    available_formats: list[ExportOption]
    default_output_path: str
    supports_preserve_structure: bool = False
    incomplete_translation_message: str | None = None


def prepare_export(runtime: ApplicationRuntime, *, project_id: str, document_ids: list[int]) -> PreparedExport:
    if not document_ids:
        raise_application_error(ApplicationErrorCode.VALIDATION, "At least one document must be selected for export.")

    with runtime.open_book_db(project_id) as dbx:
        raw_docs = [dbx.document_repo.get_document_by_id(document_id) for document_id in document_ids]
        docs = [doc for doc in raw_docs if doc is not None]
        statuses = {int(doc["document_id"]): doc for doc in dbx.document_repo.get_documents_with_status()}
        sources_by_doc = {
            int(document_id): dbx.document_repo.get_document_sources_metadata(int(document_id))
            for document_id in document_ids
        }

    if len(docs) != len(document_ids):
        raise_application_error(ApplicationErrorCode.NOT_FOUND, "One or more documents could not be loaded for export.")

    document_types = {str(doc["document_type"] or "") for doc in docs}
    if len(document_types) != 1:
        raise_application_error(ApplicationErrorCode.VALIDATION, "Mixed document types cannot be exported together.")
    document_type = next(iter(document_types))

    if len(document_ids) > 1 and not supports_multi_export_for_type(document_type):
        raise_application_error(
            ApplicationErrorCode.VALIDATION,
            "Selected documents cannot be exported together for this document type.",
        )

    available_formats = [
        ExportOption(format_id=fmt, label=fmt.upper(), is_default=(idx == 0))
        for idx, fmt in enumerate(get_supported_formats_for_type(document_type))
    ]
    if not available_formats:
        raise_application_error(
            ApplicationErrorCode.UNSUPPORTED,
            f"No export formats are available for document type '{document_type}'.",
        )

    incomplete = False
    for document_id in document_ids:
        status = statuses.get(int(document_id))
        if status is None:
            raise_application_error(
                ApplicationErrorCode.NOT_FOUND,
                f"Export status missing for document {int(document_id)}.",
            )
        total_chunks = int(status.get("total_chunks", 0) or 0)
        translated_chunks = int(status.get("chunks_translated", 0) or 0)
        if total_chunks <= 0 or translated_chunks < total_chunks:
            incomplete = True
            break

    document_labels = [
        _document_label(int(doc["document_id"]), sources_by_doc.get(int(doc["document_id"]), [])) for doc in docs
    ]
    default_format = next(
        (option.format_id for option in available_formats if option.is_default),
        available_formats[0].format_id,
    )
    default_output_path = _default_output_path(
        runtime=runtime,
        project_id=project_id,
        document_labels=document_labels,
        default_format=default_format,
    )

    return PreparedExport(
        project_id=project_id,
        document_ids=list(document_ids),
        document_type=document_type,
        document_labels=document_labels,
        available_formats=available_formats,
        default_output_path=default_output_path,
        supports_preserve_structure=supports_preserve_structure_for_type(document_type),
        incomplete_translation_message=(
            "Selected documents are not fully translated. Enable fallback to use original content for untranslated chunks."
            if incomplete
            else None
        ),
    )


def to_export_dialog_state(prepared: PreparedExport) -> ExportDialogState:
    return ExportDialogState(
        project_id=prepared.project_id,
        document_ids=prepared.document_ids,
        document_labels=prepared.document_labels,
        available_formats=prepared.available_formats,
        default_output_path=prepared.default_output_path,
        supports_preserve_structure=prepared.supports_preserve_structure,
        incomplete_translation_message=prepared.incomplete_translation_message,
    )


def run_export(
    runtime: ApplicationRuntime,
    *,
    project_id: str,
    document_ids: list[int],
    format_id: str,
    output_path: str,
    options: dict[str, str | int | float | bool | None],
) -> DocumentExportResult:
    prepared = prepare_export(runtime, project_id=project_id, document_ids=document_ids)

    preserve_structure = bool(options.get("preserve_structure", False))
    allow_original_fallback = bool(options.get("allow_original_fallback", False))
    if prepared.incomplete_translation_message and not allow_original_fallback:
        raise_application_error(
            ApplicationErrorCode.BLOCKED,
            prepared.incomplete_translation_message,
            project_id=project_id,
        )
    if preserve_structure and not prepared.supports_preserve_structure:
        raise_application_error(
            ApplicationErrorCode.UNSUPPORTED,
            "This document type does not support preserve-structure export.",
            project_id=project_id,
        )
    if not output_path.strip():
        raise_application_error(ApplicationErrorCode.VALIDATION, "Output path is required.", project_id=project_id)
    if not preserve_structure and format_id not in {option.format_id for option in prepared.available_formats}:
        raise_application_error(
            ApplicationErrorCode.VALIDATION,
            f"Unsupported export format: {format_id}.",
            project_id=project_id,
        )

    export_path = Path(output_path)
    with WorkflowSession.from_book(runtime.book_manager, project_id) as workflow:
        try:
            if preserve_structure:
                asyncio.run(
                    export_ops.export_preserve_structure(
                        workflow,
                        output_folder=export_path,
                        document_ids=document_ids,
                        allow_original_fallback=allow_original_fallback,
                    )
                )
            else:
                asyncio.run(
                    export_ops.export(
                        workflow,
                        file_path=export_path,
                        export_format=format_id,
                        document_ids=document_ids,
                        allow_original_fallback=allow_original_fallback,
                    )
                )
        except NotImplementedError as exc:
            raise_application_error(ApplicationErrorCode.UNSUPPORTED, str(exc), project_id=project_id)
        except ValueError as exc:
            raise_application_error(ApplicationErrorCode.VALIDATION, str(exc), project_id=project_id)

    return DocumentExportResult(
        document_id=document_ids[0] if len(document_ids) == 1 else 0,
        output_path=str(export_path),
        exported_count=len(document_ids),
        message=UserMessage(
            severity=UserMessageSeverity.SUCCESS,
            text=f"Export complete: {export_path}",
        ),
    )


def _document_label(document_id: int, sources: list[dict]) -> str:
    if sources:
        relative_path = str(sources[0].get("relative_path") or "").strip()
        if relative_path:
            return Path(relative_path).name
        sequence_number = int(sources[0].get("sequence_number", 1) or 1)
        return f"Document {document_id} ({sequence_number})"
    return f"Document {document_id}"


def _default_output_path(
    *,
    runtime: ApplicationRuntime,
    project_id: str,
    document_labels: list[str],
    default_format: str,
) -> str:
    export_root = runtime.book_manager.get_book_path(project_id) / "export"
    base_name = "export"
    if len(document_labels) == 1:
        base_name = _slugify(Path(document_labels[0]).stem or document_labels[0]) or "export"
    return str(export_root / f"{base_name}.{default_format}")


def _slugify(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    compact = compact.strip("-._")
    return compact[:80] or ""
