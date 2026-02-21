import asyncio
import bisect
import concurrent.futures
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.translation_strategies import DescriptionSummarizer
from context_aware_translation.storage.context_tree_db import ContextTreeDB


class SummaryNode:
    def __init__(self, content: str, layer: int, start: int, end: int, token_size: int):
        self.content = content
        self.layer = layer
        self.start = start
        self.end = end
        self.token_size = token_size
        self.length = end - start

    def __repr__(self) -> str:
        return f"<Node L{self.layer} [{self.start}-{self.end}) Size={self.token_size}>"


class ContextTree:
    """
    LSM-like tree data structure for context management. Long context chunks are summarized into shorter chunks.
    This is designed to save overall token usage.
    Multi-threaded and thread-safe.
    Persists to SQLite database.
    """

    def __init__(
        self,
        summarizer: DescriptionSummarizer,
        estimate_token_size_func: Callable[[str], int],
        sqlite_path: Path,
        max_token_size: int = 250,
        max_workers: int = 20,
    ):
        if sqlite_path is None:
            raise ValueError("sqlite_path is required and cannot be None")

        self._summarize_async = summarizer.summarize

        self.estimate_tokens = estimate_token_size_func
        self.MAX_TOKENS = max_token_size
        self.max_workers = max_workers

        # Start background event loop thread for async execution
        self._event_loop_thread: threading.Thread | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._start_event_loop_thread()

        # Database connection for context tree persistence
        self.db = ContextTreeDB(sqlite_path)

        # SHARED STATE
        self.store: dict[str, dict[int, list[SummaryNode]]] = {}
        self.keys: dict[str, list[int]] = {}
        self.buffers: dict[str, dict[int, list[SummaryNode]]] = {}
        self.max_seen_index: dict[str, int] = {}

        # LOCK
        self.lock = threading.RLock()
        self._init_condition = threading.Condition(self.lock)
        self._initialization_complete = False
        # Load from database and resume summarization
        self._load_from_db()
        self._resume_summarization()

    def _start_event_loop_thread(self) -> None:
        """Start a background thread with an event loop for async functions."""

        def run_event_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._event_loop = loop
            self._loop_ready.set()
            loop.run_forever()

        self._event_loop_thread = threading.Thread(target=run_event_loop, daemon=True)
        self._event_loop_thread.start()
        self._loop_ready.wait()  # Wait for loop to be ready

    def _run_async(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run an async coroutine in the background event loop."""
        if self._event_loop is None:
            raise RuntimeError("Event loop not available")

        future: concurrent.futures.Future[Any] = asyncio.run_coroutine_threadsafe(coro, self._event_loop)
        return future.result()

    def _persist_node(self, term: str, node: SummaryNode) -> None:
        """Persist a node to the database immediately."""
        self.db.persist_node(term, node)

    def _persist_max_index(self, term: str, max_index: int) -> None:
        """Persist max_seen_index atomically, ensuring it only increases."""
        self.db.persist_max_index(term, max_index)

    def _load_from_db(self) -> None:
        """Load all nodes and metadata from database."""
        with self.lock:
            # Load max_seen_index for all terms
            self.max_seen_index = self.db.load_max_seen_indices()

            # Load all nodes
            node_data = self.db.load_all_nodes()

            for term, content, layer, start_idx, end_idx, token_size in node_data:
                node = SummaryNode(content=content, layer=layer, start=start_idx, end=end_idx, token_size=token_size)

                # Reconstruct store and keys
                if term not in self.store:
                    self.store[term] = {}
                    self.keys[term] = []

                if node.start not in self.store[term]:
                    self.store[term][node.start] = []
                    bisect.insort(self.keys[term], node.start)

                self.store[term][node.start].append(node)

            # Reconstruct buffers by finding nodes that need summarization
            self._reconstruct_buffers_from_db()

    def _reconstruct_buffers_from_db(self) -> None:
        """
        Reconstruct buffers by finding nodes that need summarization.
        A node at layer N needs summarization if there's no layer N+1 node
        that covers its range [start, end).
        This matches the behavior of add_chunks(), which adds all nodes to buffers.
        Single nodes won't be processed until more nodes are added (requires 2+ for batching).
        """
        for term in self.store:
            for start_idx in self.store[term]:
                for node in self.store[term][start_idx]:
                    # Check if this node has been summarized (has a layer+1 node covering it)
                    has_summary = any(
                        other_node.layer == node.layer + 1
                        and other_node.start <= node.start
                        and other_node.end >= node.end
                        for other_start in self.store[term]
                        for other_node in self.store[term][other_start]
                    )

                    # If not summarized, add to buffers (avoiding duplicates)
                    if not has_summary:
                        buffer = self.buffers.setdefault(term, {}).setdefault(node.layer, [])
                        if node not in buffer:
                            buffer.append(node)

    def _resume_summarization(self) -> None:
        """
        Resume summarization until all buffers are empty.
        This ensures any incomplete summaries from previous runs are completed.
        """
        try:
            while True:
                with self.lock:
                    # Check if there are processable batches (at least 2 nodes with combined token size >= threshold)
                    if not any(
                        len(layer_nodes) >= 2
                        and sum(node.token_size for node in layer_nodes) >= self._get_layer_threshold(layer)
                        for term_buffers in self.buffers.values()
                        for layer, layer_nodes in term_buffers.items()
                    ):
                        break

                # Execute summaries (this will process all ready batches)
                self._execute_parallel_summaries()
        finally:
            with self.lock:
                self._initialization_complete = True
                self._init_condition.notify_all()

    def _save_node(self, term: str, node: SummaryNode) -> None:
        if term not in self.store:
            self.store[term] = {}
            self.keys[term] = []

        if node.start not in self.store[term]:
            self.store[term][node.start] = []
            bisect.insort(self.keys[term], node.start)

        self.store[term][node.start].append(node)

    def _add_to_buffer_only(self, term: str, layer: int, node: SummaryNode) -> None:
        self.buffers.setdefault(term, {}).setdefault(layer, []).append(node)

    def _get_layer_threshold(self, layer: int) -> int:
        """
        Calculate the token threshold for a given layer.
        Uses progressive threshold: higher layers can handle more tokens.
        Layer 0: max_token_size
        Layer 1: max_token_size * 2
        Layer 2: max_token_size * 4
        Layer N: max_token_size * (2^N)
        """
        threshold: int = self.MAX_TOKENS * (2**layer)
        return threshold

    def _collect_ready_batches(self) -> list[dict[str, Any]]:
        """
        Scans buffers. Cuts slices based on Token Size.
        Sorts by start index and allows merging across gaps.
        Uses progressive threshold: higher layers have higher token limits.
        """
        jobs: list[dict[str, Any]] = []
        with self.lock:
            for term in list(self.buffers.keys()):
                for layer in list(self.buffers[term].keys()):
                    buffer = self.buffers[term][layer]

                    # Get layer-specific threshold
                    layer_threshold = self._get_layer_threshold(layer)

                    # Sort buffer by start index
                    # Because futures complete out-of-order, the buffer is often scrambled.
                    buffer.sort(key=lambda x: x.start)

                    while True:
                        current_size = 0
                        cut_index = 0

                        for i, node in enumerate(buffer):
                            current_size += node.token_size

                            # Minimum Size Guard: require at least 2 items
                            if (i + 1) < 2:
                                continue

                            # Token Limit Trigger (using layer-specific threshold)
                            if current_size >= layer_threshold:
                                cut_index = i + 1
                                current_batch = buffer[:cut_index]
                                buffer = buffer[cut_index:]
                                self.buffers[term][layer] = buffer

                                jobs.append(
                                    {
                                        "term": term,
                                        "layer": layer,
                                        "texts": [n.content for n in current_batch],
                                        "start": current_batch[0].start,
                                        "end": current_batch[-1].end,
                                    }
                                )
                                break
                        else:
                            # Break if we didn't hit token limit or ran out of items
                            break

        return jobs

    def _execute_parallel_summaries(self, cancel_check: Callable[[], bool] | None = None) -> None:
        """
        Runs the LLM loop.
        LLM exceptions are allowed to propagate (will crash program).
        """
        while True:
            raise_if_cancelled(cancel_check)
            # 1. GET WORK (Locked inside)
            jobs = self._collect_ready_batches()
            if not jobs:
                break

            # 2. SUBMIT WORK (Unlocked) - Use asyncio with semaphore for concurrency control
            # All tasks are created upfront and compete for the semaphore. This ensures:
            # - Up to max_workers tasks run concurrently
            # - As soon as one task completes, a waiting task immediately starts
            # - Maximum utilization of available workers
            async def run_all_summaries(jobs_batch: list[dict[str, Any]]) -> list[str | BaseException]:
                semaphore = asyncio.Semaphore(self.max_workers)

                async def summarize_with_limit(job: dict[str, Any]) -> str:
                    async with semaphore:
                        return await self._summarize_async(job["texts"], cancel_check=cancel_check)

                # Create all tasks upfront - they'll compete for semaphore slots
                # When a task completes and releases the semaphore, the next waiting task starts immediately
                # return_exceptions=True lets in-flight LLM calls finish so we can save their results
                tasks = [summarize_with_limit(job) for job in jobs_batch]
                return await asyncio.gather(*tasks, return_exceptions=True)

            # Run async summaries in the background event loop
            results = self._run_async(run_all_summaries(jobs))

            # 3. SAVE RESULTS (Locked) - Persist successful results, then re-raise first error
            first_error: BaseException | None = None
            with self.lock:
                for job, result in zip(jobs, results, strict=True):
                    if isinstance(result, BaseException):
                        if first_error is None:
                            first_error = result
                        continue
                    node = SummaryNode(
                        content=result,
                        layer=job["layer"] + 1,
                        start=job["start"],
                        end=job["end"],
                        token_size=self.estimate_tokens(result),
                    )
                    # Persist to DB immediately
                    self._persist_node(job["term"], node)
                    # Then update in-memory state
                    self._save_node(job["term"], node)
                    self._add_to_buffer_only(job["term"], node.layer, node)

            if first_error is not None:
                raise first_error

    # =========================================================================
    # PUBLIC API
    # =========================================================================
    def add_chunks(self, terms_data: dict[str, dict[int, str]], cancel_check: Callable[[], bool] | None = None) -> None:
        """
        Add chunks for multiple terms at once.

        Args:
            terms_data: Dictionary mapping term keys to their chunk data (chunk_id -> content)
        """
        if not terms_data:
            return

        all_nodes_to_persist: list[tuple[str, SummaryNode]] = []
        max_indices_to_update: dict[str, int] = {}

        with self.lock:
            for term, data in terms_data.items():
                if not data:
                    continue

                # New terms may contain an imported pseudo-index (-1) that should
                # be inserted once before regular chunk-indexed descriptions.
                current_max = self.max_seen_index.get(term, -2 if term not in self.max_seen_index else -1)
                filtered_items = [(idx, content) for idx, content in sorted(data.items()) if idx > current_max]

                if not filtered_items:
                    continue

                all_nodes_to_persist.extend(
                    [
                        (
                            term,
                            SummaryNode(
                                content=content,
                                layer=0,
                                start=idx,
                                end=idx + 1,
                                token_size=self.estimate_tokens(content),
                            ),
                        )
                        for idx, content in filtered_items
                    ]
                )
                max_indices_to_update[term] = filtered_items[-1][0]

            if not all_nodes_to_persist:
                return

            try:
                self.db.begin()
                for term_key, node in all_nodes_to_persist:
                    self._persist_node(term_key, node)
                for term_key, max_idx in max_indices_to_update.items():
                    self._persist_max_index(term_key, max_idx)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

            for term_key, max_idx in max_indices_to_update.items():
                self.max_seen_index[term_key] = max_idx
            for term_key, node in all_nodes_to_persist:
                self._save_node(term_key, node)
                self._add_to_buffer_only(term_key, 0, node)

        self._execute_parallel_summaries(cancel_check=cancel_check)

    def _tile_context_nodes_locked(self, term: str, query_index: int) -> list[SummaryNode]:
        if term not in self.store:
            return []

        result_nodes: list[SummaryNode] = []
        sorted_starts = self.keys[term]
        cursor = sorted_starts[0] if sorted_starts and sorted_starts[0] < 0 else 0

        while cursor < query_index:
            if cursor not in self.store[term]:
                idx = bisect.bisect_left(sorted_starts, cursor)
                if idx >= len(sorted_starts):
                    break
                next_valid_start = sorted_starts[idx]
                if next_valid_start >= query_index:
                    break
                cursor = next_valid_start

            candidates = self.store[term][cursor]
            valid_candidates = [n for n in candidates if n.end <= query_index]

            if not valid_candidates:
                idx = bisect.bisect_right(sorted_starts, cursor)
                if idx >= len(sorted_starts):
                    break
                cursor = sorted_starts[idx]
                continue

            best_node = max(valid_candidates, key=lambda n: (n.length, n.layer))
            result_nodes.append(best_node)
            cursor = best_node.end

        return result_nodes

    def _next_layer_for_start_locked(self, term: str, start: int, *, minimum_layer: int) -> int:
        existing_layers = [node.layer for node in self.store.get(term, {}).get(start, [])]
        if existing_layers:
            return max(max(existing_layers), minimum_layer) + 1
        return minimum_layer + 1

    def get_context(self, term: str, query_index: int) -> list[str]:
        with self.lock:
            # Wait for initialization to complete
            while not self._initialization_complete:
                self._init_condition.wait()
            nodes = self._tile_context_nodes_locked(term, query_index)
            return [node.content for node in nodes]

    def summarize_contents(
        self,
        contents: list[str],
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        """Summarize arbitrary content list using the configured summarizer."""
        texts = [text for text in contents if text and text.strip()]
        if not texts:
            return ""
        if len(texts) == 1:
            return texts[0]

        raise_if_cancelled(cancel_check)
        summary = self._run_async(self._summarize_async(texts, cancel_check=cancel_check))
        return summary if isinstance(summary, str) else ""

    def summarize_term_fully(
        self,
        term: str,
        query_index: int,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        """Ensure one fully summarized context string exists for term/query range.

        Creates and persists a regular summary node (not a special-case marker),
        so future additions can reuse this node during subsequent summarization.
        """
        while True:
            with self.lock:
                while not self._initialization_complete:
                    self._init_condition.wait()
                nodes = self._tile_context_nodes_locked(term, query_index)

            if not nodes:
                return ""
            if len(nodes) == 1:
                return nodes[0].content

            raise_if_cancelled(cancel_check)
            summary_content = self._run_async(
                self._summarize_async([node.content for node in nodes], cancel_check=cancel_check)
            )
            raise_if_cancelled(cancel_check)

            with self.lock:
                nodes_now = self._tile_context_nodes_locked(term, query_index)
                if not nodes_now:
                    return ""
                if len(nodes_now) == 1:
                    return nodes_now[0].content

                start = nodes_now[0].start
                end = nodes_now[-1].end
                base_layer = max(node.layer for node in nodes_now)
                layer = self._next_layer_for_start_locked(term, start, minimum_layer=base_layer)

                merged_node = SummaryNode(
                    content=summary_content,
                    layer=layer,
                    start=start,
                    end=end,
                    token_size=self.estimate_tokens(summary_content),
                )
                self._persist_node(term, merged_node)
                self._save_node(term, merged_node)
                self._add_to_buffer_only(term, merged_node.layer, merged_node)

    def close(self) -> None:
        """Close database connection and stop event loop."""
        if self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            if self._event_loop_thread is not None:
                self._event_loop_thread.join(timeout=5.0)
        self.db.close()
