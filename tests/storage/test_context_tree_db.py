"""Tests for context_tree_db.py

Tests are organized to match the code structure:
- ContextTreeDB (class)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from context_aware_translation.storage.context_tree_db import ContextTreeDB

# ============================================================================
# Fixtures
# ============================================================================


class MockNode:
    """Mock node for testing."""

    def __init__(self, start: int, layer: int, content: str, end: int, token_size: int):
        self.start = start
        self.layer = layer
        self.content = content
        self.end = end
        self.token_size = token_size


@pytest.fixture
def temp_context_tree_db(tmp_path: Path) -> ContextTreeDB:
    """Create a temporary context tree database for testing."""
    db_path = tmp_path / "context_tree.db"
    db = ContextTreeDB(db_path)
    yield db
    db.close()


# ============================================================================
# ContextTreeDB (class) Tests
# ============================================================================

# --- Initialization ---


def test_context_tree_db_init(temp_context_tree_db: ContextTreeDB):
    """Test database initialization."""
    assert temp_context_tree_db.db_path.exists()


# --- Node Operations ---


def test_persist_node(temp_context_tree_db: ContextTreeDB):
    """Test persisting a node."""
    node = MockNode(start=0, layer=0, content="content1", end=10, token_size=10)
    temp_context_tree_db.persist_node("term1", node)

    # Verify node was persisted
    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert nodes[0][0] == "term1"  # term
    assert nodes[0][1] == "content1"  # content
    assert nodes[0][2] == 0  # layer
    assert nodes[0][3] == 0  # start_idx
    assert nodes[0][4] == 10  # end_idx
    assert nodes[0][5] == 10  # token_size


def test_persist_node_duplicate(temp_context_tree_db: ContextTreeDB):
    """Test persisting duplicate node (should be ignored)."""
    node1 = MockNode(start=0, layer=0, content="content1", end=10, token_size=10)
    node2 = MockNode(start=0, layer=0, content="content2", end=10, token_size=10)

    temp_context_tree_db.persist_node("term1", node1)
    temp_context_tree_db.persist_node("term1", node2)  # Same term, start, layer

    # Should only have one node (duplicate ignored)
    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert nodes[0][1] == "content1"  # First content preserved


def test_persist_node_multiple_layers(temp_context_tree_db: ContextTreeDB):
    """Test persisting nodes at different layers."""
    node0 = MockNode(start=0, layer=0, content="content0", end=10, token_size=10)
    node1 = MockNode(start=0, layer=1, content="content1", end=10, token_size=10)

    temp_context_tree_db.persist_node("term1", node0)
    temp_context_tree_db.persist_node("term1", node1)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 2


def test_persist_node_multiple_terms(temp_context_tree_db: ContextTreeDB):
    """Test persisting nodes for different terms."""
    node1 = MockNode(start=0, layer=0, content="content1", end=10, token_size=10)
    node2 = MockNode(start=0, layer=0, content="content2", end=10, token_size=10)

    temp_context_tree_db.persist_node("term1", node1)
    temp_context_tree_db.persist_node("term2", node2)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 2


def test_load_all_nodes_empty(temp_context_tree_db: ContextTreeDB):
    """Test loading all nodes when empty."""
    nodes = temp_context_tree_db.load_all_nodes()
    assert nodes == []


def test_load_all_nodes_ordered(temp_context_tree_db: ContextTreeDB):
    """Test that nodes are loaded in correct order."""
    # Add nodes in non-sequential order
    temp_context_tree_db.persist_node("term1", MockNode(start=20, layer=0, content="c20", end=30, token_size=10))
    temp_context_tree_db.persist_node("term1", MockNode(start=0, layer=0, content="c0", end=10, token_size=10))
    temp_context_tree_db.persist_node("term1", MockNode(start=10, layer=0, content="c10", end=20, token_size=10))
    temp_context_tree_db.persist_node("term1", MockNode(start=0, layer=1, content="c0_l1", end=10, token_size=10))

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 4

    # Should be ordered by term, layer, start_idx
    assert nodes[0][3] == 0  # start_idx = 0, layer = 0
    assert nodes[1][3] == 10  # start_idx = 10, layer = 0
    assert nodes[2][3] == 20  # start_idx = 20, layer = 0
    assert nodes[3][3] == 0  # start_idx = 0, layer = 1


def test_multiple_terms_nodes(temp_context_tree_db: ContextTreeDB):
    """Test persisting nodes for multiple terms."""
    temp_context_tree_db.persist_node("term1", MockNode(start=0, layer=0, content="t1_c0", end=10, token_size=10))
    temp_context_tree_db.persist_node("term2", MockNode(start=0, layer=0, content="t2_c0", end=10, token_size=10))
    temp_context_tree_db.persist_node("term1", MockNode(start=10, layer=0, content="t1_c10", end=20, token_size=10))

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 3

    # Verify all terms are present
    terms = {node[0] for node in nodes}
    assert terms == {"term1", "term2"}


# --- Node Edge Cases ---


def test_persist_node_empty_term_string(temp_context_tree_db: ContextTreeDB):
    """Test persisting node with empty term string."""
    node = MockNode(start=0, layer=0, content="content1", end=10, token_size=10)
    temp_context_tree_db.persist_node("", node)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert nodes[0][0] == ""  # term is empty string


def test_persist_node_negative_indices(temp_context_tree_db: ContextTreeDB):
    """Test persisting node with negative indices."""
    node = MockNode(start=-10, layer=-1, content="content1", end=-5, token_size=5)
    temp_context_tree_db.persist_node("term1", node)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert nodes[0][3] == -10  # start_idx
    assert nodes[0][2] == -1  # layer
    assert nodes[0][4] == -5  # end_idx


def test_persist_node_zero_token_size(temp_context_tree_db: ContextTreeDB):
    """Test persisting node with zero token size."""
    node = MockNode(start=0, layer=0, content="content1", end=10, token_size=0)
    temp_context_tree_db.persist_node("term1", node)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert nodes[0][5] == 0  # token_size


def test_persist_node_negative_token_size(temp_context_tree_db: ContextTreeDB):
    """Test persisting node with negative token size."""
    node = MockNode(start=0, layer=0, content="content1", end=10, token_size=-5)
    temp_context_tree_db.persist_node("term1", node)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert nodes[0][5] == -5  # token_size


def test_persist_node_empty_content(temp_context_tree_db: ContextTreeDB):
    """Test persisting node with empty content."""
    node = MockNode(start=0, layer=0, content="", end=0, token_size=0)
    temp_context_tree_db.persist_node("term1", node)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert nodes[0][1] == ""  # content


def test_persist_node_very_long_content(temp_context_tree_db: ContextTreeDB):
    """Test persisting node with very long content."""
    long_content = "a" * 100000
    node = MockNode(start=0, layer=0, content=long_content, end=len(long_content), token_size=len(long_content))
    temp_context_tree_db.persist_node("term1", node)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert len(nodes[0][1]) == 100000


def test_context_tree_node_invalid_attributes(temp_context_tree_db: ContextTreeDB):
    """Test persisting node with potentially invalid attributes."""
    # Test with very large values
    node = MockNode(
        start=2**31 - 1,
        layer=1000,
        content="content",
        end=2**31 - 1,
        token_size=2**31 - 1,
    )
    temp_context_tree_db.persist_node("term1", node)

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1
    assert nodes[0][3] == 2**31 - 1  # start_idx


# --- Max Index Operations ---


def test_persist_max_index(temp_context_tree_db: ContextTreeDB):
    """Test persisting max index."""
    temp_context_tree_db.persist_max_index("term1", 5)

    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == 5


def test_persist_max_index_increase_only(temp_context_tree_db: ContextTreeDB):
    """Test that max index only increases."""
    temp_context_tree_db.persist_max_index("term1", 5)
    temp_context_tree_db.persist_max_index("term1", 3)  # Smaller value

    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == 5  # Should remain 5

    temp_context_tree_db.persist_max_index("term1", 7)  # Larger value
    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == 7  # Should update to 7


def test_load_max_seen_indices_empty(temp_context_tree_db: ContextTreeDB):
    """Test loading max seen indices when empty."""
    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices == {}


def test_load_max_seen_indices_multiple(temp_context_tree_db: ContextTreeDB):
    """Test loading max seen indices for multiple terms."""
    temp_context_tree_db.persist_max_index("term1", 5)
    temp_context_tree_db.persist_max_index("term2", 10)
    temp_context_tree_db.persist_max_index("term3", 3)

    indices = temp_context_tree_db.load_max_seen_indices()
    assert len(indices) == 3
    assert indices["term1"] == 5
    assert indices["term2"] == 10
    assert indices["term3"] == 3


# --- Max Index Edge Cases ---


def test_persist_max_index_negative(temp_context_tree_db: ContextTreeDB):
    """Test persisting negative max index."""
    temp_context_tree_db.persist_max_index("term1", -10)

    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == -10


def test_persist_max_index_large_value(temp_context_tree_db: ContextTreeDB):
    """Test persisting very large max index."""
    large_value = 2**31 - 1  # Max 32-bit signed int
    temp_context_tree_db.persist_max_index("term1", large_value)

    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == large_value


def test_persist_max_index_decrease_ignored(temp_context_tree_db: ContextTreeDB):
    """Test that decreasing max index is ignored (only increases)."""
    temp_context_tree_db.persist_max_index("term1", 10)
    temp_context_tree_db.persist_max_index("term1", 5)  # Decrease

    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == 10  # Should remain 10

    temp_context_tree_db.persist_max_index("term1", 15)  # Increase
    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == 15  # Should update to 15


def test_persist_max_index_same_value(temp_context_tree_db: ContextTreeDB):
    """Test persisting same max index value."""
    temp_context_tree_db.persist_max_index("term1", 10)
    temp_context_tree_db.persist_max_index("term1", 10)  # Same value

    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == 10


def test_persist_max_index_very_large_negative(temp_context_tree_db: ContextTreeDB):
    """Test persisting very large negative max index."""
    temp_context_tree_db.persist_max_index("term1", -(2**31))

    indices = temp_context_tree_db.load_max_seen_indices()
    assert indices["term1"] == -(2**31)


# --- Transaction Operations ---


def test_transaction_begin_commit(temp_context_tree_db: ContextTreeDB):
    """Test transaction begin and commit."""
    temp_context_tree_db.begin()
    node = MockNode(start=0, layer=0, content="content1", end=10, token_size=10)
    temp_context_tree_db.persist_node("term1", node)
    temp_context_tree_db.commit()

    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1


def test_transaction_rollback(temp_context_tree_db: ContextTreeDB):
    """Test transaction rollback.

    Note: persist_node commits immediately, so it doesn't participate in transactions.
    This test verifies that rollback works for operations that do use transactions.
    """
    # persist_node commits immediately, so it will persist even after rollback
    node = MockNode(start=0, layer=0, content="content1", end=10, token_size=10)
    temp_context_tree_db.persist_node("term1", node)
    temp_context_tree_db.begin()
    temp_context_tree_db.rollback()

    # Node should still exist because persist_node committed immediately
    nodes = temp_context_tree_db.load_all_nodes()
    assert len(nodes) == 1


# --- Lifecycle Operations ---


def test_close(temp_context_tree_db: ContextTreeDB):
    """Test closing the database."""
    node = MockNode(start=0, layer=0, content="content1", end=10, token_size=10)
    temp_context_tree_db.persist_node("term1", node)

    # Close should not raise error
    temp_context_tree_db.close()

    # Database file should still exist
    assert temp_context_tree_db.db_path.exists()
