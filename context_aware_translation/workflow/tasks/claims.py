from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# ResourceClaim (from resource_claim.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceClaim:
    namespace: str   # e.g. "doc", "glossary", "embedding_index"
    book_id: str
    key: str         # e.g. "*", "42", "default"

# ---------------------------------------------------------------------------
# ClaimArbiter (from claim_arbiter.py)
# ---------------------------------------------------------------------------


class ClaimArbiter:
    def conflicts(self, wanted: frozenset[ResourceClaim], active: frozenset[ResourceClaim]) -> bool:
        for w in wanted:
            for a in active:
                if w.namespace != a.namespace:
                    continue
                if w.book_id != a.book_id:
                    continue
                if w.key == a.key or w.key == "*" or a.key == "*":
                    return True
        return False

# ---------------------------------------------------------------------------
# DocumentScope (from document_scope.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllDocuments:
    book_id: str


@dataclass(frozen=True)
class SomeDocuments:
    book_id: str
    doc_ids: frozenset[int]


@dataclass(frozen=True)
class NoDocuments:
    book_id: str


DocumentScope = AllDocuments | SomeDocuments | NoDocuments


def scopes_overlap(a: DocumentScope, b: DocumentScope) -> bool:
    """Return True if two scopes in the same book overlap."""
    if a.book_id != b.book_id:
        return False
    if isinstance(a, NoDocuments) or isinstance(b, NoDocuments):
        return False
    if isinstance(a, AllDocuments) or isinstance(b, AllDocuments):
        return True
    # Both SomeDocuments
    return bool(a.doc_ids & b.doc_ids)
