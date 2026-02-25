from __future__ import annotations

from context_aware_translation.workflow.tasks.claims import ClaimArbiter, ClaimMode, ResourceClaim


def test_same_namespace_book_key_conflicts():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="42")})
    active = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="42")})
    assert arbiter.conflicts(wanted, active) is True


def test_wildcard_wanted_conflicts_with_any_key():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="*")})
    active = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="42")})
    assert arbiter.conflicts(wanted, active) is True


def test_wildcard_active_conflicts_with_any_key():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="42")})
    active = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="*")})
    assert arbiter.conflicts(wanted, active) is True


def test_different_namespaces_no_conflict():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="42")})
    active = frozenset({ResourceClaim(namespace="glossary", book_id="b1", key="42")})
    assert arbiter.conflicts(wanted, active) is False


def test_different_book_ids_no_conflict():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="42")})
    active = frozenset({ResourceClaim(namespace="doc", book_id="b2", key="42")})
    assert arbiter.conflicts(wanted, active) is False


def test_empty_wanted_no_conflict():
    arbiter = ClaimArbiter()
    wanted: frozenset[ResourceClaim] = frozenset()
    active = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="42")})
    assert arbiter.conflicts(wanted, active) is False


def test_empty_active_no_conflict():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim(namespace="doc", book_id="b1", key="42")})
    active: frozenset[ResourceClaim] = frozenset()
    assert arbiter.conflicts(wanted, active) is False


def test_all_overlaps_all_same_book():
    from context_aware_translation.workflow.tasks.claims import AllDocuments, scopes_overlap
    a = AllDocuments(book_id="b1")
    b = AllDocuments(book_id="b1")
    assert scopes_overlap(a, b) is True


def test_all_overlaps_some_same_book():
    from context_aware_translation.workflow.tasks.claims import AllDocuments, SomeDocuments, scopes_overlap
    a = AllDocuments(book_id="b1")
    b = SomeDocuments(book_id="b1", doc_ids=frozenset({1, 2}))
    assert scopes_overlap(a, b) is True
    assert scopes_overlap(b, a) is True


def test_some_overlaps_some_intersecting():
    from context_aware_translation.workflow.tasks.claims import SomeDocuments, scopes_overlap
    a = SomeDocuments(book_id="b1", doc_ids=frozenset({1, 2, 3}))
    b = SomeDocuments(book_id="b1", doc_ids=frozenset({3, 4, 5}))
    assert scopes_overlap(a, b) is True


def test_some_no_overlap_disjoint():
    from context_aware_translation.workflow.tasks.claims import SomeDocuments, scopes_overlap
    a = SomeDocuments(book_id="b1", doc_ids=frozenset({1, 2}))
    b = SomeDocuments(book_id="b1", doc_ids=frozenset({3, 4}))
    assert scopes_overlap(a, b) is False


def test_no_documents_overlaps_nothing():
    from context_aware_translation.workflow.tasks.claims import AllDocuments, NoDocuments, SomeDocuments, scopes_overlap
    none = NoDocuments(book_id="b1")
    all_docs = AllDocuments(book_id="b1")
    some_docs = SomeDocuments(book_id="b1", doc_ids=frozenset({1}))
    other_none = NoDocuments(book_id="b1")

    assert scopes_overlap(none, all_docs) is False
    assert scopes_overlap(all_docs, none) is False
    assert scopes_overlap(none, some_docs) is False
    assert scopes_overlap(some_docs, none) is False
    assert scopes_overlap(none, other_none) is False


def test_different_books_never_overlap():
    from context_aware_translation.workflow.tasks.claims import AllDocuments, NoDocuments, SomeDocuments, scopes_overlap
    a = AllDocuments(book_id="b1")
    b = AllDocuments(book_id="b2")
    assert scopes_overlap(a, b) is False

    c = SomeDocuments(book_id="b1", doc_ids=frozenset({1}))
    d = SomeDocuments(book_id="b2", doc_ids=frozenset({1}))
    assert scopes_overlap(c, d) is False

    e = NoDocuments(book_id="b1")
    f = NoDocuments(book_id="b2")
    assert scopes_overlap(e, f) is False


# ---------------------------------------------------------------------------
# ClaimMode-aware conflict tests
# ---------------------------------------------------------------------------


def test_read_shared_vs_read_shared_no_conflict():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.READ_SHARED)})
    active = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.READ_SHARED)})
    assert arbiter.conflicts(wanted, active) is False


def test_write_cooperative_vs_write_cooperative_no_conflict():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim("context_tree", "b1", "*", ClaimMode.WRITE_COOPERATIVE)})
    active = frozenset({ResourceClaim("context_tree", "b1", "*", ClaimMode.WRITE_COOPERATIVE)})
    assert arbiter.conflicts(wanted, active) is False


def test_read_shared_vs_write_exclusive_conflicts():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.READ_SHARED)})
    active = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.WRITE_EXCLUSIVE)})
    assert arbiter.conflicts(wanted, active) is True


def test_write_exclusive_vs_read_shared_conflicts():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.WRITE_EXCLUSIVE)})
    active = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.READ_SHARED)})
    assert arbiter.conflicts(wanted, active) is True


def test_write_cooperative_vs_write_exclusive_conflicts():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim("context_tree", "b1", "*", ClaimMode.WRITE_COOPERATIVE)})
    active = frozenset({ResourceClaim("context_tree", "b1", "*", ClaimMode.WRITE_EXCLUSIVE)})
    assert arbiter.conflicts(wanted, active) is True


def test_write_exclusive_vs_write_exclusive_conflicts():
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.WRITE_EXCLUSIVE)})
    active = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.WRITE_EXCLUSIVE)})
    assert arbiter.conflicts(wanted, active) is True


def test_read_shared_vs_write_cooperative_conflicts():
    """READ_SHARED and WRITE_COOPERATIVE conflict — cooperative writers don't share with readers."""
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.READ_SHARED)})
    active = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.WRITE_COOPERATIVE)})
    assert arbiter.conflicts(wanted, active) is True


def test_claim_mode_no_conflict_different_namespace():
    """Even conflicting modes don't conflict across different namespaces."""
    arbiter = ClaimArbiter()
    wanted = frozenset({ResourceClaim("glossary_state", "b1", "*", ClaimMode.WRITE_EXCLUSIVE)})
    active = frozenset({ResourceClaim("context_tree", "b1", "*", ClaimMode.WRITE_EXCLUSIVE)})
    assert arbiter.conflicts(wanted, active) is False
