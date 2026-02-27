from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from context_aware_translation.documents.base import is_ocr_required_for_type

if TYPE_CHECKING:
    from context_aware_translation.workflow.service import WorkflowService


BOOTSTRAP_REGISTRY_LOCK = threading.Lock()
BOOTSTRAP_LOCKS: dict[str, threading.Lock] = {}


def get_bootstrap_lock(
    book_id: str | None,
    *,
    registry_lock: threading.Lock | None = None,
    locks: dict[str, threading.Lock] | None = None,
) -> threading.Lock:
    """Return a per-book lock for serializing bootstrap operations."""
    lock_registry = BOOTSTRAP_REGISTRY_LOCK if registry_lock is None else registry_lock
    lock_map = BOOTSTRAP_LOCKS if locks is None else locks
    key = book_id or "__unknown__"
    with lock_registry:
        if key not in lock_map:
            lock_map[key] = threading.Lock()
        return lock_map[key]


def is_missing_source_language_error(exc: BaseException) -> bool:
    """Return True if error indicates missing source-language bootstrap state."""
    message = str(exc).lower()
    return ("source language not found" in message) or ("no text chunks found" in message)


async def ensure_source_language(
    workflow: WorkflowService,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Ensure source language is available for LLM-dependent glossary/translation steps."""
    workflow._check_cancel(cancel_check)
    await workflow.manager.detect_language(cancel_check=cancel_check)


async def process_document(
    workflow: WorkflowService,
    document_ids: list[int] | None = None,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Process documents, adding their text to the context manager with document_id."""
    documents = workflow._load_documents(document_ids)
    if not documents:
        raise ValueError("No documents found in database")

    for document in documents:
        workflow._check_cancel(cancel_check)
        if not document.is_ocr_completed() and document.ocr_required_for_translation:
            raise ValueError(
                f"Document {document.document_id} has not completed OCR. "
                "Please run OCR from the OCR Review tab before translation or glossary build."
            )

        if not document.is_text_added():
            text_content = document.get_text()
            translator_config = workflow.config.translator_config
            assert translator_config is not None

            workflow.manager.add_text(
                text=text_content,
                max_token_size_per_chunk=translator_config.chunk_size,
                document_id=document.document_id,
                document_type=document.document_type,
            )
            document.mark_text_added()


async def prepare_llm_prerequisites(
    workflow: WorkflowService,
    document_ids: list[int] | None,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Prepare document text/chunks and source language for LLM-driven steps."""
    lock = workflow._get_bootstrap_lock(workflow.book_id)
    with lock:
        workflow._check_cancel(cancel_check)
        await workflow._process_document(document_ids, cancel_check=cancel_check)
        workflow._check_cancel(cancel_check)
        await workflow._ensure_source_language(cancel_check=cancel_check)


async def ensure_glossary_source_language(
    workflow: WorkflowService,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Ensure source language for glossary-only operations without document preflight."""
    workflow._check_cancel(cancel_check)
    source_language = workflow.db.get_source_language()
    if source_language:
        return

    # Hidden best-effort prep: add text from docs that are already ready.
    # OCR-blocked document types are skipped rather than failing.
    documents = sorted(workflow._load_documents(None), key=lambda doc: int(doc.document_id))
    translator_config = workflow.config.translator_config
    assert translator_config is not None
    for document in documents:
        workflow._check_cancel(cancel_check)
        if document.is_text_added():
            continue
        if document.ocr_required_for_translation and not document.is_ocr_completed():
            continue
        text_content = document.get_text()
        workflow.manager.add_text(
            text=text_content,
            max_token_size_per_chunk=translator_config.chunk_size,
            document_id=document.document_id,
            document_type=document.document_type,
        )
        document.mark_text_added()

    # First try standard chunk-based detection (if any chunks now exist).
    try:
        await workflow._ensure_source_language(cancel_check=cancel_check)
        return
    except ValueError as exc:
        if not workflow._is_missing_source_language_error(exc):
            raise

    # Fallback to glossary table text (imported terms, etc.).
    terms = workflow.db.list_terms(limit=80)
    sample_parts: list[str] = []
    for term in terms:
        workflow._check_cancel(cancel_check)
        key = (term.key or "").strip()
        if key:
            sample_parts.append(key)
        descriptions = term.descriptions or {}
        for desc in descriptions.values():
            if isinstance(desc, str) and desc.strip():
                sample_parts.append(desc.strip())
                break
        if len(sample_parts) >= 120:
            break

    sample_text = "\n".join(sample_parts).strip()
    if not sample_text:
        raise ValueError("Source language not found. Build/import glossary terms with source text first.")

    detected = await workflow.manager.source_language_detector.detect(sample_text, cancel_check=cancel_check)
    workflow.db.set_source_language(detected)


def resolve_preflight_document_ids(
    workflow: WorkflowService,
    document_ids: list[int] | None,
) -> list[int] | None:
    """Resolve document IDs to preflight before translation."""
    all_documents = sorted(workflow.document_repo.list_documents(), key=lambda d: int(d["document_id"]))
    if not all_documents:
        return None
    if document_ids is None:
        return [int(doc["document_id"]) for doc in all_documents]

    if not document_ids:
        return []

    selected_ids = {int(doc_id) for doc_id in document_ids}
    selected_docs = [doc for doc in all_documents if int(doc["document_id"]) in selected_ids]
    if selected_docs and all(not is_ocr_required_for_type(str(doc.get("document_type", ""))) for doc in selected_docs):
        return [int(doc["document_id"]) for doc in selected_docs]

    cutoff = max(selected_ids)
    return [int(doc["document_id"]) for doc in all_documents if int(doc["document_id"]) <= cutoff]
