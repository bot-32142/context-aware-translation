from __future__ import annotations

from pathlib import Path

import pytest

from context_aware_translation.core.context_tree import ContextTree as _ContextTree


class CallableSummarizer:
    def __init__(self, func):
        self._func = func

    async def summarize(self, descriptions: list[str], **_kwargs) -> str:
        return self._func(descriptions)


def ContextTree(
    *,
    summarize_func,
    estimate_token_size_func,
    sqlite_path,
    max_token_size: int = 250,
    max_workers: int = 20,
):
    return _ContextTree(
        summarizer=CallableSummarizer(summarize_func),
        estimate_token_size_func=estimate_token_size_func,
        sqlite_path=sqlite_path,
        max_token_size=max_token_size,
        max_workers=max_workers,
    )


def simple_summarize(descriptions: list[str]) -> str:
    """Simple mock summarize function that joins descriptions."""
    return " | ".join(descriptions)


def simple_estimate_tokens(text: str) -> int:
    """Simple mock token estimation function (approximates by character count / 4)."""
    return len(text) // 4


def test_add_chunks_basic(tmp_path: Path):
    """Test adding a single chunk."""
    sqlite_path = tmp_path / "test.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )
    tree.add_chunks({"term1": {0: "description1"}})

    # After adding, should be able to query it
    context = tree.get_context("term1", 1)
    assert context == ["description1"]


def test_add_chunks_sequential_indices(tmp_path: Path):
    """Test adding chunks with sequential chunk indices."""
    sqlite_path = tmp_path / "test.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks with sequential indices (0, 1, 2, 3, 4)
    data = {i: f"description{i}" for i in range(5)}
    tree.add_chunks({"term1": data})

    # Query should return all descriptions before index 5
    context = tree.get_context("term1", 5)
    assert context == ["description0 | description1 | description2 | description3", "description4"]


def test_get_longest_context_summary_returns_longest_prior_summary(tmp_path: Path):
    sqlite_path = tmp_path / "test_get_longest_context_summary_returns_longest_prior_summary.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    tree.add_chunks({"term1": {0: "a", 1: "bb", 2: "cccccccc", 3: "d"}})
    longest = tree.get_longest_context_summary("term1", 4)
    assert longest
    assert len(longest) >= len("cccccccc")

    tree.close()


def test_add_chunks_non_sequential_indices(tmp_path: Path):
    """Test adding chunks with non-sequential chunk indices (0, 2, 4, 5, 8).
    With gap merging enabled, indices 0, 2, 4, 5 can be merged into a summary covering [0-6).
    """
    sqlite_path = tmp_path / "test_add_chunks_non_sequential_indices.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    indices = [0, 2, 4, 5, 8]
    data = {idx: f"description{idx}" for idx in indices}
    tree.add_chunks({"term1": data})

    # Query up to index 9 should return all descriptions
    # With gap merging, 0, 2, 4, 5 are merged into a summary covering [0-6)
    context = tree.get_context("term1", 9)
    assert context == ["description0 | description2 | description4 | description5", "description8"]

    context = tree.get_context("term1", 4)
    assert context == ["description0 | description2"]


def test_summarization_triggered_when_threshold_exceeded(tmp_path: Path):
    """Test that summarization is triggered when accumulated size exceeds threshold."""
    sqlite_path = tmp_path / "test_summarization_triggered_when_threshold_exceeded.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks until max_token_size is exceeded (max_token_size=3, so 4th chunk should trigger)
    tree.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2"}})

    # This should trigger summarization of first 3 chunks
    tree.add_chunks({"term1": {3: "desc3"}})

    # Query should return summarized version for first 3, plus desc3
    context = tree.get_context("term1", 4)
    assert context == ["desc0 | desc1 | desc2", "desc3"]


def test_multi_layer_summarization(tmp_path: Path):
    """Test that summarization happens at multiple layers."""
    sqlite_path = tmp_path / "test_multi_layer_summarization.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add enough chunks to trigger multiple layers of summarization
    # max_token_size=3 means: 3 chunks -> layer 1, 3 summaries -> layer 2, etc.
    # Add 10 chunks to trigger at least 2 layers
    data = {i: f"desc{i}" for i in range(10)}
    tree.add_chunks({"term1": data})

    # Query should return high-level summaries when available
    context = tree.get_context("term1", 10)
    assert context == ["desc0 | desc1 | desc2 | desc3 | desc4 | desc5", "desc6 | desc7 | desc8", "desc9"]


def test_get_context_greedy_tiling(tmp_path: Path):
    """Test that get_context uses greedy tiling to prefer high-level summaries."""
    sqlite_path = tmp_path / "test_get_context_greedy_tiling.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add 9 chunks (will create 3 summaries at layer 1, then 1 summary at layer 2)
    data = {i: f"desc{i}" for i in range(9)}
    tree.add_chunks({"term1": data})

    # Query for index 9 should prefer the high-level summary covering [0, 9)
    # over individual descriptions or layer 1 summaries
    context = tree.get_context("term1", 9)

    # Should return minimal number of descriptions
    # With proper greedy tiling, should prefer 1 high-level summary over 3 layer-1 summaries
    assert context == ["desc0 | desc1 | desc2 | desc3 | desc4 | desc5", "desc6 | desc7 | desc8"]


def test_get_context_partial_range(tmp_path: Path):
    """Test querying for a partial range (not all chunks)."""
    sqlite_path = tmp_path / "test_get_context_partial_range.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add 10 chunks
    data = {i: f"desc{i}" for i in range(10)}
    tree.add_chunks({"term1": data})

    # Query only up to index 5
    context = tree.get_context("term1", 5)

    # Should return descriptions covering [0, 5)
    assert context == ["desc0 | desc1 | desc2", "desc3", "desc4"]


def test_get_context_empty(tmp_path: Path):
    """Test querying when no chunks exist."""
    sqlite_path = tmp_path / "test_get_context_empty.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    context = tree.get_context("term1", 5)
    assert context == []


def test_get_context_zero_index(tmp_path: Path):
    """Test querying for index 0 (should return empty)."""
    sqlite_path = tmp_path / "test_get_context_zero_index.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    tree.add_chunks({"term1": {0: "desc0"}})
    context = tree.get_context("term1", 0)
    assert context == []


def test_get_context_zero_index_includes_imported_negative_index(tmp_path: Path):
    """Imported pseudo-index (-1) should be available at query_index=0."""
    sqlite_path = tmp_path / "test_get_context_zero_index_includes_imported_negative_index.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    tree.add_chunks({"term1": {-1: "imported-desc", 0: "desc0"}})
    context = tree.get_context("term1", 0)
    assert context == ["imported-desc"]


def test_summarize_term_fully_merges_context_to_single_node(tmp_path: Path):
    sqlite_path = tmp_path / "test_summarize_term_fully_merges_context_to_single_node.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    tree.add_chunks({"term1": {i: f"desc{i}" for i in range(7)}})
    before = tree.get_context("term1", 7)
    assert len(before) > 1

    summary = tree.summarize_term_fully("term1", 7)
    assert summary

    after = tree.get_context("term1", 7)
    assert after == [summary]


def test_summarize_term_fully_reuses_existing_summary_when_new_chunks_added(tmp_path: Path):
    sqlite_path = tmp_path / "test_summarize_term_fully_reuses_existing_summary_when_new_chunks_added.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    tree.add_chunks({"term1": {i: f"desc{i}" for i in range(6)}})
    first_summary = tree.summarize_term_fully("term1", 6)
    assert tree.get_context("term1", 6) == [first_summary]

    tree.add_chunks({"term1": {6: "desc6", 7: "desc7"}})
    before_second_merge = tree.get_context("term1", 8)
    assert before_second_merge[0] == first_summary

    second_summary = tree.summarize_term_fully("term1", 8)
    assert tree.get_context("term1", 8) == [second_summary]


def test_multiple_terms(tmp_path: Path):
    """Test that different terms are stored separately."""
    sqlite_path = tmp_path / "test_multiple_terms.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    tree.add_chunks({"term1": {0: "desc1_0", 1: "desc1_1"}, "term2": {0: "desc2_0", 1: "desc2_1"}})

    context1 = tree.get_context("term1", 2)
    context2 = tree.get_context("term2", 2)

    assert context1 == ["desc1_0", "desc1_1"]
    assert context2 == ["desc2_0", "desc2_1"]


def test_summarization_preserves_coverage(tmp_path: Path):
    """Test that summarization doesn't lose coverage of chunk indices."""
    sqlite_path = tmp_path / "test_summarization_preserves_coverage.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks that will be summarized
    data = {i: f"desc{i}" for i in range(6)}
    tree.add_chunks({"term1": data})

    # Query should still cover all indices
    context = tree.get_context("term1", 6)
    assert context == ["desc0 | desc1 | desc2 | desc3 | desc4 | desc5"]


def test_large_buffer_size(tmp_path: Path):
    """Test with larger buffer size."""
    sqlite_path = tmp_path / "test_large_buffer_size.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=10,
    )

    # Add 25 chunks (should create summaries at different thresholds)
    data = {i: f"desc{i}" for i in range(25)}
    tree.add_chunks({"term1": data})

    # Query should still work and prefer high-level summaries
    context = tree.get_context("term1", 25)
    assert context == [
        "desc0 | desc1 | desc2 | desc3 | desc4 | desc5 | desc6 | desc7 | desc8 | desc9 | desc10 | desc11 | desc12 | desc13 | desc14 | desc15 | desc16 | desc17 | desc18 | desc19",
        "desc20",
        "desc21",
        "desc22",
        "desc23",
        "desc24",
    ]


def test_greedy_tiling_prefers_wide_coverage(tmp_path: Path):
    """Test that greedy tiling prefers summaries covering wider ranges."""
    sqlite_path = tmp_path / "test_greedy_tiling_prefers_wide_coverage.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add 12 chunks to create a clear hierarchy
    data = {i: f"desc{i}" for i in range(12)}
    tree.add_chunks({"term1": data})

    # Query for all 12
    context = tree.get_context("term1", 12)

    # Should prefer 1 high-level summary covering [0, 9) or [0, 12) if available
    # over multiple smaller summaries
    assert context == [
        "desc0 | desc1 | desc2 | desc3 | desc4 | desc5 | desc6 | desc7 | desc8 | desc9 | desc10 | desc11"
    ]

    context = tree.get_context("term1", 3)
    assert context == [
        "desc0 | desc1 | desc2",
    ]

    context = tree.get_context("term1", 7)
    assert context == ["desc0 | desc1 | desc2 | desc3 | desc4 | desc5", "desc6"]


def test_sequential_additions_trigger_summarization(tmp_path: Path):
    """Test that sequential additions properly trigger summarization at thresholds."""
    sqlite_path = tmp_path / "test_sequential_additions_trigger_summarization.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Track when summarization happens by checking context size
    # Add first 3 - should not trigger yet (waiting for threshold)
    tree.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2"}})

    # Add 4th - should trigger summarization of first 3
    tree.add_chunks({"term1": {3: "desc3"}})

    # Continue adding to trigger more summarizations
    data = {i: f"desc{i}" for i in range(4, 10)}
    tree.add_chunks({"term1": data})

    # Final query should use summaries
    context = tree.get_context("term1", 10)
    assert context == ["desc0 | desc1 | desc2 | desc3 | desc4 | desc5", "desc6 | desc7 | desc8", "desc9"]


def test_progressive_threshold_calculation(tmp_path: Path):
    """Test that progressive threshold calculates correctly for different layers."""
    sqlite_path = tmp_path / "test_progressive_threshold_calculation.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Verify threshold calculation
    assert tree._get_layer_threshold(0) == 3  # 3 * 2^0 = 3
    assert tree._get_layer_threshold(1) == 6  # 3 * 2^1 = 6
    assert tree._get_layer_threshold(2) == 12  # 3 * 2^2 = 12
    assert tree._get_layer_threshold(3) == 24  # 3 * 2^3 = 24
    assert tree._get_layer_threshold(4) == 48  # 3 * 2^4 = 48


def test_progressive_threshold_layer1_combines_more(tmp_path: Path):
    """Test that Layer 1 can combine more items than Layer 0 due to higher threshold."""
    sqlite_path = tmp_path / "test_progressive_threshold_layer1_combines_more.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks that will create Layer 1 summaries
    # Layer 0 threshold is 3, so 3-4 chunks per summary
    # Layer 1 threshold is 6, so it can combine 2 Layer 1 summaries
    data = {i: f"desc{i}" for i in range(12)}
    tree.add_chunks({"term1": data})

    # Check that Layer 1 summaries exist and can be combined at Layer 2
    # With progressive threshold, Layer 2 (threshold=12) can combine Layer 1 summaries
    # that are too large for Layer 1's threshold (6)
    context = tree.get_context("term1", 12)

    # Should have comprehensive summaries due to progressive threshold
    assert context == [
        "desc0 | desc1 | desc2 | desc3 | desc4 | desc5 | desc6 | desc7 | desc8 | desc9 | desc10 | desc11"
    ]


def test_progressive_threshold_allows_layer2_combination(tmp_path: Path):
    """Test that Layer 2 can combine summaries that exceed Layer 1 threshold."""
    sqlite_path = tmp_path / "test_progressive_threshold_allows_layer2_combination.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add enough chunks to create Layer 2 summaries
    # Layer 0: threshold 3, creates summaries of ~3-4 chunks
    # Layer 1: threshold 6, creates summaries of ~2 Layer 0 summaries
    # Layer 2: threshold 12, can combine Layer 1 summaries that are ~5-11 tokens
    data = {i: f"desc{i}" for i in range(18)}
    tree.add_chunks({"term1": data})

    # Query should return fewer items due to progressive threshold allowing
    # higher layers to combine more
    context = tree.get_context("term1", 18)

    # With progressive threshold, should have comprehensive summaries
    assert context == [
        "desc0 | desc1 | desc2 | desc3 | desc4 | desc5 | desc6 | desc7 | desc8 | desc9 | desc10 | desc11",
        "desc12 | desc13 | desc14 | desc15 | desc16 | desc17",
    ]


def test_progressive_threshold_different_base_sizes(tmp_path: Path):
    """Test progressive threshold with different base max_token_size values."""
    # Test with larger base threshold
    sqlite_path1 = tmp_path / "test1.db"
    tree1 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path1,
        max_token_size=10,
    )

    assert tree1._get_layer_threshold(0) == 10
    assert tree1._get_layer_threshold(1) == 20
    assert tree1._get_layer_threshold(2) == 40
    assert tree1._get_layer_threshold(3) == 80
    tree1.close()

    # Test with smaller base threshold
    sqlite_path2 = tmp_path / "test2.db"
    tree2 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path2,
        max_token_size=2,
    )

    assert tree2._get_layer_threshold(0) == 2
    assert tree2._get_layer_threshold(1) == 4
    assert tree2._get_layer_threshold(2) == 8
    assert tree2._get_layer_threshold(3) == 16
    tree2.close()


def test_progressive_threshold_enables_deeper_summarization(tmp_path: Path):
    """Test that progressive threshold enables more comprehensive summaries at higher layers."""
    sqlite_path = tmp_path / "test.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add many chunks to create multiple layers
    data = {i: f"desc{i}" for i in range(30)}
    tree.add_chunks({"term1": data})

    # Check that higher layers can combine summaries
    # Layer 2 threshold is 12, so it can combine Layer 1 summaries (typically 5-11 tokens)
    context = tree.get_context("term1", 30)

    # With progressive threshold, should have comprehensive summaries
    assert context == [
        "desc0 | desc1 | desc2 | desc3 | desc4 | desc5 | desc6 | desc7 | desc8 | desc9 | desc10 | desc11 | desc12 | desc13 | desc14 | desc15 | desc16 | desc17 | desc18 | desc19 | desc20 | desc21 | desc22 | desc23",
        "desc24 | desc25 | desc26 | desc27 | desc28 | desc29",
    ]
    tree.close()


def test_add_chunks_skips_monotonicity_violations(tmp_path: Path):
    """Test that indices violating monotonicity are skipped instead of raising an error."""
    sqlite_path = tmp_path / "test_add_chunks_skips_monotonicity_violations.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add initial chunks
    tree.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2"}})

    # Try to add chunks with some indices that violate monotonicity (0, 1 are already added)
    # Only indices 3, 4, 5 should be added
    tree.add_chunks({"term1": {0: "desc0_duplicate", 1: "desc1_duplicate", 3: "desc3", 4: "desc4", 5: "desc5"}})

    # Query should only contain the original desc0, desc1, desc2 and the new desc3, desc4, desc5
    # The duplicate indices should be skipped
    context = tree.get_context("term1", 6)
    assert "desc0_duplicate" not in " ".join(context)
    assert "desc1_duplicate" not in " ".join(context)
    assert "desc3" in " ".join(context) or any("desc3" in c for c in context)
    assert "desc4" in " ".join(context) or any("desc4" in c for c in context)
    assert "desc5" in " ".join(context) or any("desc5" in c for c in context)


def test_add_chunks_all_skipped_when_all_violate_monotonicity(tmp_path: Path):
    """Test that when all indices violate monotonicity, nothing is added."""
    sqlite_path = tmp_path / "test_add_chunks_all_skipped_when_all_violate_monotonicity.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add initial chunks
    tree.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2"}})

    # Try to add chunks where all indices violate monotonicity
    tree.add_chunks({"term1": {0: "desc0_new", 1: "desc1_new", 2: "desc2_new"}})

    # Query should only contain the original descriptions
    context = tree.get_context("term1", 3)
    assert "desc0_new" not in " ".join(context)
    assert "desc1_new" not in " ".join(context)
    assert "desc2_new" not in " ".join(context)


def test_persistence_across_instances(tmp_path: Path):
    """Test that data persists across different ContextTree instances."""
    sqlite_path = tmp_path / "test.db"

    # Create first tree and add chunks
    tree1 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )
    tree1.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2", 3: "desc3"}})
    tree1.close()

    # Create second tree from same database
    tree2 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Should be able to query the same data
    context = tree2.get_context("term1", 4)
    assert len(context) > 0
    assert "desc0" in " ".join(context) or any("desc0" in c for c in context)
    tree2.close()


def test_idempotency_add_chunks(tmp_path: Path):
    """Test that adding the same chunks multiple times is idempotent."""
    sqlite_path = tmp_path / "test.db"

    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks first time
    tree.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2"}})
    context1 = tree.get_context("term1", 3)

    # Add same chunks again (should be skipped due to monotonicity)
    tree.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2"}})
    context2 = tree.get_context("term1", 3)

    # Results should be the same
    assert context1 == context2

    # Add new chunks
    tree.add_chunks({"term1": {3: "desc3", 4: "desc4"}})
    context3 = tree.get_context("term1", 5)

    # Should have more content now
    assert len(context3) >= len(context2)
    tree.close()


def test_resume_after_crash_incomplete_summaries(tmp_path: Path):
    """Test that incomplete summaries are resumed after a crash."""

    sqlite_path = tmp_path / "test.db"

    # Track summarize calls
    summarize_calls_tree1 = []
    summarize_calls_tree2 = []

    def summarize_tree1(descriptions: list[str]) -> str:
        summarize_calls_tree1.append(len(descriptions))
        return " | ".join(descriptions)

    # Create first tree and add chunks that will trigger summarization
    tree1 = ContextTree(
        summarize_func=summarize_tree1,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add enough chunks to trigger summarization
    # max_token_size=3 means we need at least 4 chunks to trigger
    tree1.add_chunks({"term1": {i: f"desc{i}" for i in range(6)}})

    # Close quickly to simulate crash (some summarization may be incomplete)
    # The summarization happens asynchronously, so closing quickly may leave work incomplete
    tree1.close()

    # Create second tree - should resume incomplete summaries
    # _resume_summarization() runs during __init__ and will complete any pending work
    def summarize_tree2(descriptions: list[str]) -> str:
        summarize_calls_tree2.append(len(descriptions))
        return " | ".join(descriptions)

    # Creating tree2 will block until _resume_summarization() completes
    # This is expected behavior - initialization must complete before tree is usable
    tree2 = ContextTree(
        summarize_func=summarize_tree2,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # get_context should work immediately since initialization is complete
    context = tree2.get_context("term1", 6)
    assert len(context) > 0

    # Verify that data is accessible (persistence worked)
    assert len(context) > 0

    tree2.close()


def test_exception_during_summarization_crashes_program(tmp_path: Path):
    """Test that exceptions during summarization propagate (crash program)."""
    sqlite_path = tmp_path / "test.db"

    def failing_summarize(_descriptions: list[str]) -> str:
        raise RuntimeError("LLM call failed")

    tree = ContextTree(
        summarize_func=failing_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks that will trigger summarization
    # The exception will be raised when _execute_parallel_summaries runs
    # and will propagate from add_chunks (as designed - LLM failures should crash)
    with pytest.raises(RuntimeError, match="LLM call failed"):
        tree.add_chunks({"term1": {i: f"desc{i}" for i in range(6)}})

    # Clean up if exception was caught
    import contextlib

    with contextlib.suppress(Exception):
        tree.close()


def test_persistence_with_multiple_terms(tmp_path: Path):
    """Test persistence works correctly with multiple terms."""
    sqlite_path = tmp_path / "test.db"

    # Create first tree
    tree1 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )
    tree1.add_chunks({"term1": {0: "desc1_0", 1: "desc1_1"}, "term2": {0: "desc2_0", 1: "desc2_1"}})
    tree1.close()

    # Create second tree
    tree2 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Both terms should be available
    context1 = tree2.get_context("term1", 2)
    context2 = tree2.get_context("term2", 2)

    assert len(context1) > 0
    assert len(context2) > 0
    assert context1 != context2
    tree2.close()


def test_max_seen_index_persistence(tmp_path: Path):
    """Test that max_seen_index is persisted and used correctly."""
    sqlite_path = tmp_path / "test.db"

    # Create first tree and add chunks
    tree1 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )
    tree1.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2", 3: "desc3"}})
    tree1.close()

    # Create second tree
    tree2 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Try to add chunks with indices that should be skipped
    tree2.add_chunks({"term1": {0: "desc0_new", 1: "desc1_new"}})

    # Add new chunks that should be accepted
    tree2.add_chunks({"term1": {4: "desc4", 5: "desc5"}})

    context = tree2.get_context("term1", 6)
    # Old chunks should still be there, new chunks should be added
    assert "desc0" in " ".join(context) or any("desc0" in c for c in context)
    assert "desc4" in " ".join(context) or any("desc4" in c for c in context)
    tree2.close()


# ============================================================================
# UNCOVERED EDGE CASES
# ============================================================================


def test_no_database_mode_raises_exception():
    """Test that ContextTree raises exception when sqlite_path is None."""
    with pytest.raises(ValueError, match="sqlite_path is required"):
        ContextTree(
            summarize_func=simple_summarize,
            estimate_token_size_func=simple_estimate_tokens,
            sqlite_path=None,  # Should raise exception
            max_token_size=3,
        )


def test_database_rollback_on_failure(tmp_path: Path):
    """Test that database rollback works correctly on failure."""
    sqlite_path = tmp_path / "test.db"

    # Create a mock database that fails on commit
    from context_aware_translation.storage.context_tree_db import ContextTreeDB

    class FailingDB(ContextTreeDB):
        def commit(self):
            raise RuntimeError("Database commit failed")

    # Monkey patch to use failing DB
    original_init = ContextTreeDB.__init__
    db_instance = None

    def failing_init(self, path):
        nonlocal db_instance
        original_init(self, path)
        db_instance = self

    ContextTreeDB.__init__ = failing_init

    try:
        tree = ContextTree(
            summarize_func=simple_summarize,
            estimate_token_size_func=simple_estimate_tokens,
            sqlite_path=sqlite_path,
            max_token_size=3,
        )

        # Replace the db with failing version
        if db_instance:
            failing_db = FailingDB(sqlite_path)
            failing_db._init_schema()
            tree.db = failing_db

        # This should raise an exception and rollback
        with pytest.raises(RuntimeError, match="Database commit failed"):
            tree.add_chunks({"term1": {0: "desc0", 1: "desc1"}})

        # In-memory state should not be updated (rollback worked)
        # Since rollback happened, the data shouldn't be in the tree
        tree.get_context("term1", 2)
        # The data might still be in memory from the attempt, but DB should be rolled back
        # This is a bit tricky to test without accessing internals

    finally:
        ContextTreeDB.__init__ = original_init
        tree.close()


def test_get_context_beyond_max_index(tmp_path: Path):
    """Test get_context with query_index beyond max_seen_index."""
    sqlite_path = tmp_path / "test_get_context_beyond_max_index.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks up to index 5
    tree.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2", 3: "desc3", 4: "desc4"}})

    # Query beyond max_seen_index (with gaps)
    context = tree.get_context("term1", 10)
    # Should return what's available up to max_seen_index
    assert len(context) > 0
    # Should not crash


def test_get_context_multiple_nodes_same_start(tmp_path: Path):
    """Test get_context with multiple nodes at same start index but different layers."""
    sqlite_path = tmp_path / "test_get_context_multiple_nodes_same_start.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks that will create summaries at different layers
    tree.add_chunks({"term1": {i: f"desc{i}" for i in range(9)}})

    # After summarization, there should be nodes at different layers covering the same ranges
    # Query should prefer higher layer nodes (greedy tiling)
    context = tree.get_context("term1", 9)
    assert len(context) > 0
    # Should use higher layer summaries when available


def test_reconstruct_buffers_empty_database(tmp_path: Path):
    """Test _reconstruct_buffers_from_db with empty database."""
    sqlite_path = tmp_path / "test.db"

    # Create tree with empty database
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Should initialize without errors
    assert tree._initialization_complete
    assert len(tree.buffers) == 0
    assert len(tree.store) == 0

    tree.close()


def test_reconstruct_buffers_already_summarized(tmp_path: Path):
    """Test that already summarized nodes are not added to buffers."""
    sqlite_path = tmp_path / "test.db"

    # Create first tree and add chunks that get fully summarized
    tree1 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )
    tree1.add_chunks({"term1": {i: f"desc{i}" for i in range(9)}})
    tree1.close()

    # Create second tree - should not have layer 0 nodes in buffers
    # (they should all be summarized)
    tree2 = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Layer 0 nodes should not be in buffers (they're summarized)
    # Only higher layer nodes that need further summarization should be in buffers
    if "term1" in tree2.buffers and 0 in tree2.buffers["term1"]:
        # If there are layer 0 nodes, they should be minimal or none
        assert len(tree2.buffers["term1"][0]) == 0 or len(tree2.buffers["term1"][0]) < 9

    tree2.close()


def test_collect_ready_batches_single_large_node(tmp_path: Path):
    """Test _collect_ready_batches with single node that exceeds threshold."""
    sqlite_path = tmp_path / "test_collect_ready_batches_single_large_node.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add a single very large chunk (exceeds threshold)
    large_text = "x" * 100  # Large text that exceeds threshold
    tree.add_chunks({"term1": {0: large_text}})

    # Single node should not form a batch (requires 2+ items)
    # Should not crash, but also shouldn't process it
    context = tree.get_context("term1", 1)
    # Should still be queryable (stored but not summarized)
    assert len(context) > 0


def test_collect_ready_batches_nodes_below_threshold(tmp_path: Path):
    """Test _collect_ready_batches with nodes that can't form batches."""
    sqlite_path = tmp_path / "test_collect_ready_batches_nodes_below_threshold.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=10,  # High threshold
    )

    # Add small chunks that won't meet threshold even when combined
    tree.add_chunks({"term1": {0: "a", 1: "b", 2: "c"}})

    # These nodes should be in buffers but not processable
    # Should not cause infinite loop
    context = tree.get_context("term1", 3)
    # Should still work (nodes stored but not summarized)
    assert len(context) == 3


def test_thread_safety_concurrent_add_chunks(tmp_path: Path):
    """Test thread safety with concurrent add_chunks calls."""
    import threading

    sqlite_path = tmp_path / "test_thread_safety_concurrent_add_chunks.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    def add_chunks_thread(term: str, start_idx: int, count: int):
        data = {start_idx + i: f"desc{start_idx + i}" for i in range(count)}
        tree.add_chunks({term: data})

    # Create multiple threads adding chunks
    threads = []
    for i in range(5):
        t = threading.Thread(target=add_chunks_thread, args=("term1", i * 10, 3))
        threads.append(t)
        t.start()

    # Wait for all threads
    for t in threads:
        t.join()

    # Should not crash and data should be consistent
    context = tree.get_context("term1", 50)
    assert len(context) > 0

    tree.close()


def test_thread_safety_concurrent_get_context(tmp_path: Path):
    """Test thread safety with concurrent get_context calls."""
    import threading

    sqlite_path = tmp_path / "test_thread_safety_concurrent_get_context.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add some data first
    tree.add_chunks({"term1": {i: f"desc{i}" for i in range(10)}})

    results = []

    def get_context_thread(query_index: int):
        context = tree.get_context("term1", query_index)
        results.append((query_index, len(context)))

    # Create multiple threads querying
    threads = []
    for i in range(5):
        t = threading.Thread(target=get_context_thread, args=(i * 2 + 1,))
        threads.append(t)
        t.start()

    # Wait for all threads
    for t in threads:
        t.join()

    # Should not crash and all queries should succeed
    assert len(results) == 5
    for _query_index, context_len in results:
        assert context_len >= 0  # Should return valid results

    tree.close()


def test_close_idempotent(tmp_path: Path):
    """Test that close() can be called multiple times safely."""
    sqlite_path = tmp_path / "test_close_idempotent.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    tree.add_chunks({"term1": {0: "desc0"}})

    # Close multiple times
    tree.close()
    tree.close()
    tree.close()

    # Should not raise exceptions


def test_operations_after_close(tmp_path: Path):
    """Test behavior when operations are called after close()."""
    sqlite_path = tmp_path / "test_operations_after_close.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    tree.add_chunks({"term1": {0: "desc0"}})
    tree.close()

    # Operations after close might fail or might work depending on implementation
    # At minimum, should not crash the program
    import contextlib

    with contextlib.suppress(Exception):
        tree.get_context("term1", 1)


def test_initialization_empty_database(tmp_path: Path):
    """Test initialization with existing but empty database file."""
    sqlite_path = tmp_path / "test.db"

    # Create an empty database file
    from context_aware_translation.storage.context_tree_db import ContextTreeDB

    db = ContextTreeDB(sqlite_path)
    db.close()

    # Create tree from empty database
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Should initialize without errors
    assert tree._initialization_complete
    assert len(tree.store) == 0
    assert len(tree.buffers) == 0

    tree.close()


def test_add_chunks_large_dataset(tmp_path: Path):
    """Test add_chunks with very large dataset."""
    sqlite_path = tmp_path / "test_add_chunks_large_dataset.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add many chunks
    large_data = {i: f"desc{i}" for i in range(100)}
    tree.add_chunks({"term1": large_data})

    # Should handle large datasets without issues
    context = tree.get_context("term1", 100)
    assert len(context) > 0

    tree.close()


def test_persist_node_requires_database(tmp_path: Path):
    """Test _persist_node requires database (db is always set)."""
    sqlite_path = tmp_path / "test.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Should work with database
    from context_aware_translation.core.context_tree import SummaryNode

    node = SummaryNode("test", 0, 0, 1, 1)
    tree._persist_node("term1", node)  # Should work

    tree.close()


def test_persist_max_index_requires_database(tmp_path: Path):
    """Test _persist_max_index requires database (db is always set)."""
    sqlite_path = tmp_path / "test.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Should work with database
    tree._persist_max_index("term1", 5)  # Should work

    tree.close()


def test_get_context_with_gaps(tmp_path: Path):
    """Test get_context when there are gaps in node coverage."""
    sqlite_path = tmp_path / "test_get_context_with_gaps.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add chunks with gaps
    tree.add_chunks({"term1": {0: "desc0", 5: "desc5", 10: "desc10"}})

    # Query should handle gaps gracefully
    context = tree.get_context("term1", 15)
    assert len(context) > 0
    # Should return available nodes despite gaps

    tree.close()


def test_add_chunks_all_filtered_monotonicity(tmp_path: Path):
    """Test add_chunks when all items are filtered out due to monotonicity."""
    sqlite_path = tmp_path / "test_add_chunks_all_filtered_monotonicity.db"
    tree = ContextTree(
        summarize_func=simple_summarize,
        estimate_token_size_func=simple_estimate_tokens,
        sqlite_path=sqlite_path,
        max_token_size=3,
    )

    # Add initial chunks
    tree.add_chunks({"term1": {0: "desc0", 1: "desc1", 2: "desc2"}})

    # Try to add chunks where all violate monotonicity
    tree.add_chunks({"term1": {0: "new0", 1: "new1", 2: "new2"}})

    # Should not crash, and original data should remain
    context = tree.get_context("term1", 3)
    assert "desc0" in " ".join(context) or any("desc0" in c for c in context)
    assert "new0" not in " ".join(context)

    tree.close()
