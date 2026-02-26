from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_aware_translation.storage.document_repository import DocumentRepository


@dataclass(frozen=True)
class GlossaryPreflightResult:
    target_doc_ids: list[int]
    cutoff_doc_id: int | None
    preflight_doc_ids: list[int]
    blocking_ocr_doc_ids: list[int]
    is_blocked: bool


def compute_glossary_preflight(
    pending_doc_ids: list[int],
    selected_cutoff_doc_id: int | None,
    document_repo: DocumentRepository,
) -> GlossaryPreflightResult:
    """Compute preflight information for a glossary extraction task.

    Args:
        pending_doc_ids: All document IDs that are pending glossary build.
        selected_cutoff_doc_id: Optional cutoff; if provided, only docs with
            doc_id <= selected_cutoff_doc_id are targeted.
        document_repo: Repository used to load document data.

    Returns:
        GlossaryPreflightResult with target docs, cutoff, preflight set,
        blocking OCR docs, and whether the run is blocked.
    """
    from context_aware_translation.documents.base import (
        can_build_glossary_without_prior_ocr_for_type,
        is_ocr_required_for_type,
    )

    # Step 1: filter pending_doc_ids to target set
    if selected_cutoff_doc_id is not None:
        target_doc_ids = [doc_id for doc_id in pending_doc_ids if doc_id <= selected_cutoff_doc_id]
    else:
        target_doc_ids = list(pending_doc_ids)

    # Step 2: resolve effective cutoff
    if selected_cutoff_doc_id is not None:
        cutoff_doc_id: int | None = selected_cutoff_doc_id
    elif target_doc_ids:
        cutoff_doc_id = max(target_doc_ids)
    else:
        cutoff_doc_id = None

    # Step 3: build preflight set — all docs up to cutoff in ascending order
    if cutoff_doc_id is not None:
        all_docs = document_repo.list_documents()
        all_ids = sorted(int(doc["document_id"]) for doc in all_docs)
        preflight_doc_ids = [doc_id for doc_id in all_ids if doc_id <= cutoff_doc_id]
    else:
        preflight_doc_ids = []

    # Fetch document status once for both Step 4 and Step 5
    docs_with_status = document_repo.get_documents_with_status()
    docs_by_id = {int(doc["document_id"]): doc for doc in docs_with_status}

    # Step 4: EPUB-skip check — if ALL target types can skip prior OCR blockers,
    # return unblocked immediately.
    if target_doc_ids:
        selected_types = []
        for doc_id in target_doc_ids:
            doc = docs_by_id.get(doc_id)
            if doc is not None:
                selected_types.append(str(doc.get("document_type", "")))

        if selected_types and all(
            can_build_glossary_without_prior_ocr_for_type(doc_type) for doc_type in selected_types
        ):
            return GlossaryPreflightResult(
                target_doc_ids=target_doc_ids,
                cutoff_doc_id=cutoff_doc_id,
                preflight_doc_ids=preflight_doc_ids,
                blocking_ocr_doc_ids=[],
                is_blocked=False,
            )

    # Step 5: find OCR blockers in preflight set
    if preflight_doc_ids:
        blocking_ocr_doc_ids: list[int] = []
        for doc_id in preflight_doc_ids:
            doc = docs_by_id.get(doc_id)
            if doc is None:
                continue
            if not is_ocr_required_for_type(doc.get("document_type", "")):
                continue
            if int(doc.get("ocr_pending", 0) or 0) > 0:
                blocking_ocr_doc_ids.append(doc_id)
    else:
        blocking_ocr_doc_ids = []

    is_blocked = len(blocking_ocr_doc_ids) > 0

    return GlossaryPreflightResult(
        target_doc_ids=target_doc_ids,
        cutoff_doc_id=cutoff_doc_id,
        preflight_doc_ids=preflight_doc_ids,
        blocking_ocr_doc_ids=blocking_ocr_doc_ids,
        is_blocked=is_blocked,
    )


def resolve_effective_pending_ids(
    requested_document_ids: list[int] | None,
    document_repo: DocumentRepository,
) -> tuple[list[int], list[int]]:
    """Resolve the effective set of pending document IDs for a task.

    Args:
        requested_document_ids: The doc IDs originally requested, or None for all.
        document_repo: Repository for fetching current document status.

    Returns:
        Tuple of (effective_ids, stale_ids).
        - effective_ids: IDs that are still pending glossary work.
        - stale_ids: IDs from the request that are no longer pending.
    """
    currently_pending_docs = document_repo.list_documents_pending_glossary()
    currently_pending_ids = {int(doc["document_id"]) for doc in currently_pending_docs}

    if requested_document_ids is None:
        return (sorted(currently_pending_ids), [])

    requested_set = set(requested_document_ids)
    still_pending = requested_set & currently_pending_ids
    stale = sorted(requested_set - currently_pending_ids)
    effective = sorted(still_pending)

    return (effective, stale)
