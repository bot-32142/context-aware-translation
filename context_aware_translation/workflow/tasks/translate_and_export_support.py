from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import context_aware_translation.config as config_module
import context_aware_translation.storage.repositories.document_repository as document_repository
import context_aware_translation.storage.repositories.term_repository as term_repository
import context_aware_translation.storage.schema.book_db as book_db
from context_aware_translation.documents.base import (
    get_supported_formats_for_type,
    supports_original_image_export_for_type,
    supports_preserve_structure_for_type,
)
from context_aware_translation.documents.epub import CHAPTER_MIME_TYPES, METADATA_PATH
from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import decode_task_payload
from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES

from .models import Decision

_ONE_SHOT_REEMBEDDABLE_DOCUMENT_TYPES = frozenset({"pdf", "scanned_book", "manga", "epub"})
_RERUN_GUARD_REASON = "This one-shot task cannot be retried because the document or glossary changed after it stopped."
_REMOTE_BATCH_PHASES = frozenset(
    {
        "translation_submit",
        "translation_poll",
        "translation_validate",
        "translation_fallback",
        "polish_submit",
        "polish_poll",
        "polish_validate",
        "polish_fallback",
        "apply",
    }
)
_ACTIVE_REMOTE_BATCH_STATUSES = frozenset({"running", "cancel_requested", "cancelling"})


def _is_translate_and_export_relevant_source(document_type: str, source: dict[str, Any]) -> bool:
    source_type = str(source.get("source_type") or "").strip().lower()
    if source_type == "image":
        return True
    if source_type != "text":
        return False
    if document_type != "epub":
        return True

    relative_path = str(source.get("relative_path") or "").strip()
    if relative_path == METADATA_PATH:
        return False

    mime_type = str(source.get("mime_type") or "").strip().lower()
    lower_path = relative_path.lower()
    return mime_type in CHAPTER_MIME_TYPES or lower_path.endswith((".xhtml", ".html", ".htm", ".svg"))


def decode_translate_and_export_payload(record: TaskRecord) -> dict[str, Any]:
    return decode_task_payload(record)


def extract_document_id(raw_document_ids: object) -> int:
    if not isinstance(raw_document_ids, list) or len(raw_document_ids) != 1:
        raise ValueError("Translate and Export requires exactly one document_id.")
    return int(raw_document_ids[0])


def document_id_from_record(record: TaskRecord) -> int:
    if not record.document_ids_json:
        raise ValueError("Translate and Export requires exactly one document_id.")
    try:
        raw = json.loads(record.document_ids_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Translate and Export task document_ids_json is malformed.") from exc
    return extract_document_id(raw)


def validate_translate_and_export_submit(book_id: str, params: dict[str, object], deps: Any) -> Decision:
    return _validate_translate_and_export(
        book_id,
        params=params,
        deps=deps,
        require_untouched=True,
        task_record=None,
    )


def validate_translate_and_export_run(record: TaskRecord, payload: dict[str, Any], deps: Any) -> Decision:
    params: dict[str, object] = {
        "document_ids": [document_id_from_record(record)],
        "format_id": payload.get("format_id"),
        "output_path": payload.get("output_path"),
        "use_batch": payload.get("use_batch", False),
        "use_reembedding": payload.get("use_reembedding", False),
        "options": payload.get("options", {}),
    }
    decision = _validate_translate_and_export(
        record.book_id,
        params=params,
        deps=deps,
        require_untouched=False,
        task_record=record,
    )
    if not decision.allowed:
        return decision

    resume_guard = payload.get("resume_guard")
    should_enforce_resume_guard = bool(payload.get("resume_guard_required", False)) or record.status in {
        "cancelled",
        "failed",
        "completed_with_errors",
    }
    if should_enforce_resume_guard and isinstance(resume_guard, str) and resume_guard.strip():
        document_ids = params.get("document_ids")
        if not isinstance(document_ids, list) or len(document_ids) != 1:
            raise ValueError("Translate and Export requires exactly one document_id.")
        current_guard = compute_resume_guard(
            deps.book_manager.get_book_db_path(record.book_id),
            int(document_ids[0]),
        )
        if current_guard != resume_guard:
            return Decision(allowed=False, code="stale_resume_state", reason=_RERUN_GUARD_REASON)
    return Decision(allowed=True)


def compute_resume_guard(db_path: Path, document_id: int) -> str:
    db = book_db.SQLiteBookDB(db_path)
    try:
        doc_repo = document_repository.DocumentRepository(db)
        term_repo = term_repository.TermRepository(db)
        sources = [
            {
                "source_id": int(source["source_id"]),
                "source_type": str(source.get("source_type") or ""),
                "is_ocr_completed": bool(source.get("is_ocr_completed")),
                "is_text_added": bool(source.get("is_text_added")),
                "ocr_hash": _sha256_text(doc_repo.get_source_ocr_json(int(source["source_id"])) or ""),
            }
            for source in doc_repo.get_document_sources_metadata(document_id)
        ]
        chunks = [
            {
                "chunk_id": int(chunk.chunk_id),
                "is_extracted": bool(chunk.is_extracted),
                "is_summarized": bool(chunk.is_summarized),
                "is_occurrence_mapped": bool(chunk.is_occurrence_mapped),
                "is_translated": bool(chunk.is_translated),
                "text_hash": _sha256_text(chunk.text or ""),
                "translation_hash": _sha256_text(chunk.translation or ""),
            }
            for chunk in term_repo.list_chunks(document_id=document_id)
        ]
        terms = [
            {
                "key": record.key,
                "translated_name": record.translated_name or "",
                "ignored": bool(record.ignored),
                "is_reviewed": bool(record.is_reviewed),
                "updated_at": float(record.updated_at or 0.0),
            }
            for record in term_repo.list_term_records()
        ]
        reembedded = [
            {
                "element_idx": int(element_idx),
                "mime": mime_type,
                "image_hash": hashlib.sha256(image_bytes).hexdigest(),
            }
            for element_idx, (image_bytes, mime_type) in sorted(doc_repo.load_reembedded_images(document_id).items())
        ]
        payload = {
            "sources": sources,
            "chunks": chunks,
            "terms": terms,
            "reembedded": reembedded,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    finally:
        db.close()


def with_resume_guard(
    payload: dict[str, Any],
    db_path: Path,
    document_id: int,
    *,
    required: bool = False,
) -> dict[str, Any]:
    updated = dict(payload)
    updated["resume_guard"] = compute_resume_guard(db_path, document_id)
    updated["resume_guard_required"] = required
    return updated


def _is_remote_batch_cleanup(task_record: TaskRecord | None, *, use_batch: bool) -> bool:
    if task_record is None or not use_batch:
        return False
    return task_record.status in _ACTIVE_REMOTE_BATCH_STATUSES and (task_record.phase or "") in _REMOTE_BATCH_PHASES


def _validate_translate_and_export(
    book_id: str,
    *,
    params: dict[str, object],
    deps: Any,
    require_untouched: bool,
    task_record: TaskRecord | None,
) -> Decision:
    try:
        document_id = extract_document_id(params.get("document_ids"))
    except ValueError as exc:
        return Decision(allowed=False, reason=str(exc))

    use_batch = bool(params.get("use_batch", False))
    use_reembedding = bool(params.get("use_reembedding", False))
    options = params.get("options")
    normalized_options = options if isinstance(options, dict) else {}
    format_id = str(params.get("format_id") or "").strip()
    output_path = str(params.get("output_path") or "").strip()

    book = deps.book_manager.get_book(book_id)
    if book is None:
        return Decision(allowed=False, reason=f"Book not found: {book_id}")

    try:
        config = config_module.Config.from_book(book, deps.book_manager.library_root, deps.book_manager.registry)
    except Exception as exc:  # noqa: BLE001
        return Decision(allowed=False, reason=str(exc) or "Project setup is incomplete.")

    if not config.translation_target_language.strip():
        return Decision(allowed=False, reason="Target language is required")
    if config.review_config is None:
        return Decision(
            allowed=False,
            code="no_review_config",
            reason="Review config not set. Please configure review settings.",
        )

    db_path = deps.book_manager.get_book_db_path(book_id)
    try:
        db = book_db.SQLiteBookDB(db_path)
    except Exception:
        return Decision(allowed=False, reason="Cannot open book database.")

    try:
        doc_repo = document_repository.DocumentRepository(db)
        document = doc_repo.get_document_by_id(document_id)
        if document is None:
            return Decision(allowed=False, reason=f"Document {document_id} not found.")
        document_type = str(document.get("document_type") or "")
        if require_untouched:
            active_tasks = _active_document_tasks(deps, book_id, document_id, exclude_task_id=None)
            if active_tasks:
                return Decision(
                    allowed=False,
                    reason="Translate and Export is already running or another task is active for this document.",
                )
            if not _document_is_untouched(doc_repo, document_id, document_type=document_type):
                return Decision(
                    allowed=False,
                    code="document_touched",
                    reason=(
                        "Translate and Export is available only before OCR, glossary, translation, "
                        "or reembedding work has started for this document."
                    ),
                )
        if use_batch and not _is_remote_batch_cleanup(task_record, use_batch=use_batch) and document_type == "manga":
            return Decision(
                allowed=False,
                reason="Async batch translation is only available for non-manga documents.",
            )
        if use_batch and not _is_remote_batch_cleanup(task_record, use_batch=use_batch):
            batch_provider = config_module.resolve_pipeline_batch_provider(
                config.translator_config,
                config.polish_config,
                enable_polish=True,
            )
            if batch_provider is None:
                return Decision(
                    allowed=False,
                    reason="Async batch translation requires Translator and Polish to use the same batch-capable provider.",
                )
            if config.translator_batch_config is None:
                return Decision(
                    allowed=False,
                    reason="Async batch translation requires Translator batch settings in Project Setup.",
                )
            if config_module.effective_polish_step_config(
                config.translator_config, config.polish_config
            ) is not None and (config.polish_batch_config is None):
                return Decision(
                    allowed=False,
                    reason="Async batch translation requires Polish batch settings in Project Setup.",
                )
        if document_type == "manga" and config.manga_translator_config is None:
            return Decision(
                allowed=False,
                reason="manga_translator_config is required to translate manga documents. Please configure it in your book settings.",
            )
        if document_type in {"pdf", "scanned_book", "manga"} and config.ocr_config is None:
            return Decision(
                allowed=False,
                reason="ocr_config is required for OCR tasks. Please configure it in your book settings.",
            )
        if use_reembedding:
            if document_type not in _ONE_SHOT_REEMBEDDABLE_DOCUMENT_TYPES:
                return Decision(allowed=False, reason="This document type does not support image reembedding.")
            if config.image_reembedding_config is None:
                return Decision(
                    allowed=False,
                    reason="image_reembedding_config is required for image reembedding. Please configure it in your book settings.",
                )

        export_decision = _validate_export_options(
            document_type=document_type,
            format_id=format_id,
            output_path=output_path,
            options=normalized_options,
        )
        if not export_decision.allowed:
            return export_decision
    finally:
        db.close()

    if task_record is not None and task_record.status in TERMINAL_TASK_STATUSES:
        return Decision(allowed=True)
    return Decision(allowed=True)


def _validate_export_options(
    *,
    document_type: str,
    format_id: str,
    output_path: str,
    options: dict[str, Any],
) -> Decision:
    if not output_path:
        return Decision(allowed=False, reason="Output path is required.")
    if not format_id:
        return Decision(allowed=False, reason="Export format is required.")

    if format_id not in set(get_supported_formats_for_type(document_type)):
        return Decision(allowed=False, reason=f"Unsupported export format: {format_id}.")

    preserve_structure = bool(options.get("preserve_structure", False))
    use_original_images = bool(options.get("use_original_images", False))
    epub_force_horizontal_ltr = bool(options.get("epub_force_horizontal_ltr", False))

    if preserve_structure and not supports_preserve_structure_for_type(document_type):
        return Decision(allowed=False, reason="This document type does not support preserve-structure export.")
    if use_original_images and not supports_original_image_export_for_type(document_type):
        return Decision(allowed=False, reason="This document type does not support exporting original images.")
    if epub_force_horizontal_ltr and document_type != "epub":
        return Decision(
            allowed=False,
            reason="EPUB layout conversion is only available for imported EPUB documents.",
        )
    return Decision(allowed=True)


def _document_is_untouched(
    doc_repo: document_repository.DocumentRepository,
    document_id: int,
    *,
    document_type: str,
) -> bool:
    sources = [
        source
        for source in doc_repo.get_document_sources_metadata(document_id)
        if _is_translate_and_export_relevant_source(document_type, source)
    ]
    if any(bool(source.get("is_ocr_completed")) for source in sources if source.get("source_type") == "image"):
        return False
    if any(bool(source.get("is_text_added")) for source in sources):
        return False
    if doc_repo.get_chunk_count(document_id) > 0:
        return False
    return not doc_repo.load_reembedded_images(document_id)


def _active_document_tasks(
    deps: Any, book_id: str, document_id: int, *, exclude_task_id: str | None
) -> list[TaskRecord]:
    records = deps.task_store.list_tasks(book_id=book_id, exclude_statuses=TERMINAL_TASK_STATUSES)
    relevant: list[TaskRecord] = []
    for record in records:
        if exclude_task_id is not None and record.task_id == exclude_task_id:
            continue
        if not record.document_ids_json:
            continue
        try:
            raw_ids = json.loads(record.document_ids_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(raw_ids, list):
            continue
        try:
            document_ids = {int(value) for value in raw_ids}
        except (TypeError, ValueError):
            continue
        if document_id in document_ids:
            relevant.append(record)
    return relevant


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
