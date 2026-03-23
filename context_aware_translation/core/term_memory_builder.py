from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from collections.abc import Callable, Coroutine
from typing import cast

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.term_memory import TermMemoryVersion
from context_aware_translation.core.translation_strategies import TermMemoryUpdater


class _EvidenceBatch:
    def __init__(self, chunk_index: int, descriptions: list[str]) -> None:
        self.chunk_index = chunk_index
        self.descriptions = descriptions


class TermMemoryBuilder:
    def __init__(self, updater: TermMemoryUpdater) -> None:
        self._bootstrap_async = updater.bootstrap_summary
        self._update_async = updater.update_summary
        self._event_loop_thread: threading.Thread | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._closed = False
        self._start_event_loop_thread()

    def _start_event_loop_thread(self) -> None:
        def run_event_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._event_loop = loop
            self._loop_ready.set()
            loop.run_forever()

        self._event_loop_thread = threading.Thread(target=run_event_loop, daemon=True)
        self._event_loop_thread.start()
        self._loop_ready.wait()

    def _run_async(self, coro: Coroutine[object, object, object]) -> object:
        if self._event_loop is None:
            raise RuntimeError("Event loop not available")
        future: concurrent.futures.Future[object] = asyncio.run_coroutine_threadsafe(coro, self._event_loop)
        return future.result()

    @staticmethod
    def _normalize_batches(data: dict[int, str]) -> list[_EvidenceBatch]:
        grouped: dict[int, list[str]] = {}
        for idx, content in sorted(data.items()):
            text = content.strip()
            if not text:
                continue
            grouped.setdefault(idx, []).append(text)
        return [_EvidenceBatch(idx, values) for idx, values in grouped.items()]

    @staticmethod
    def _initial_window_size(total_batches: int) -> int:
        return min(4, total_batches)

    @staticmethod
    def _effective_start_after(batch: _EvidenceBatch) -> int:
        return batch.chunk_index + 1

    def build_versions(
        self,
        term: str,
        data: dict[int, str],
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[TermMemoryVersion]:
        batches = self._normalize_batches(data)
        if len(batches) < 2:
            return []

        initial_window = self._initial_window_size(len(batches))
        bootstrap_inputs = [desc for batch in batches[:initial_window] for desc in batch.descriptions]
        bootstrap_summary = str(
            self._run_async(self._bootstrap_async(bootstrap_inputs, cancel_check=cancel_check))
        ).strip()
        if not bootstrap_summary:
            return []

        versions = [
            TermMemoryVersion(
                term=term,
                effective_start_chunk=self._effective_start_after(batches[initial_window - 1]),
                latest_evidence_chunk=batches[initial_window - 1].chunk_index,
                summary_text=bootstrap_summary,
                kind="bootstrap",
                source_count=initial_window,
                created_at=time.time(),
            )
        ]
        current_summary = bootstrap_summary
        cursor = initial_window
        dense_limit = min(len(batches), 8)

        while cursor < len(batches):
            raise_if_cancelled(cancel_check)
            window_size = 1 if cursor < dense_limit else min(32, len(batches) - cursor)
            end = min(len(batches), cursor + window_size)
            update = self._evaluate_window(
                term=term,
                current_summary=current_summary,
                batches=batches,
                start=cursor,
                end=end,
                cancel_check=cancel_check,
            )
            if update is not None:
                current_summary = update.summary_text
                versions.append(update)
            cursor = end

        return versions

    def _evaluate_window(
        self,
        *,
        term: str,
        current_summary: str,
        batches: list[_EvidenceBatch],
        start: int,
        end: int,
        cancel_check: Callable[[], bool] | None,
    ) -> TermMemoryVersion | None:
        window = batches[start:end]
        if not window:
            return None
        evidence = [(batch.chunk_index, "\n".join(batch.descriptions)) for batch in window]
        updated, new_summary = self._run_update(current_summary, evidence, cancel_check)
        if not updated:
            return None

        refined_end = end
        if len(window) > 2:
            refined_end, new_summary = self._refine_positive_window(
                current_summary=current_summary,
                batches=batches,
                start=start,
                end=end,
                cancel_check=cancel_check,
            )

        latest_batch = batches[refined_end - 1]
        return TermMemoryVersion(
            term=term,
            effective_start_chunk=self._effective_start_after(latest_batch),
            latest_evidence_chunk=latest_batch.chunk_index,
            summary_text=new_summary.strip(),
            kind="revision",
            source_count=refined_end,
            created_at=time.time(),
        )

    def _run_update(
        self,
        current_summary: str,
        evidence: list[tuple[int, str]],
        cancel_check: Callable[[], bool] | None,
    ) -> tuple[bool, str]:
        raw_result = self._run_async(
            self._update_async(
                current_summary,
                evidence,
                cancel_check=cancel_check,
            )
        )
        result = cast(tuple[bool, str], raw_result)
        updated, summary = result
        return bool(updated), str(summary)

    def _refine_positive_window(
        self,
        *,
        current_summary: str,
        batches: list[_EvidenceBatch],
        start: int,
        end: int,
        cancel_check: Callable[[], bool] | None,
    ) -> tuple[int, str]:
        best_end = end
        best_summary = current_summary
        for size in (8, 2):
            if (best_end - start) <= size:
                continue
            refined_end = start + size
            while refined_end <= best_end:
                window = batches[start:refined_end]
                evidence = [(batch.chunk_index, "\n".join(batch.descriptions)) for batch in window]
                updated, candidate_summary = self._run_update(
                    current_summary,
                    evidence,
                    cancel_check,
                )
                if updated:
                    best_end = refined_end
                    best_summary = candidate_summary.strip()
                    break
                refined_end += size
        return best_end, best_summary

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            if self._event_loop_thread is not None:
                self._event_loop_thread.join(timeout=5.0)
