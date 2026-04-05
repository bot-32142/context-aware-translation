"""Worker for async translate-and-export task run/cancel operations."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from context_aware_translation.adapters.qt.workers.base_worker import BaseWorker
from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
from context_aware_translation.storage.library.book_manager import BookManager
from context_aware_translation.storage.repositories.task_store import TaskStore
from context_aware_translation.workflow.ops import bootstrap_ops, export_ops, glossary_ops, ocr_ops, translation_ops
from context_aware_translation.workflow.session import WorkflowSession
from context_aware_translation.workflow.tasks.execution.batch_translation_executor import (
    BatchTranslationExecutor,
    _PauseRequestedError,
)
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import (
    apply_results,
    ensure_payload_prepared,
    is_item_translation_success,
    run_polish_stage,
    run_translation_stage,
)
from context_aware_translation.workflow.tasks.models import PHASE_DONE, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING
from context_aware_translation.workflow.tasks.translate_and_export_support import with_resume_guard

logger = logging.getLogger(__name__)


class TranslateAndExportTaskWorker(BaseWorker):
    """Worker to run/cancel persistent one-shot translate-and-export tasks."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        *,
        action: str,
        task_id: str | None = None,
        document_id: int,
        format_id: str,
        output_path: str,
        use_batch: bool,
        use_reembedding: bool,
        enable_polish: bool,
        options: dict[str, Any],
        task_store: TaskStore | None = None,
        notify_task_changed: Callable[[str], None] | None = None,
        config_snapshot_json: str | None = None,
    ) -> None:
        super().__init__()
        self._book_manager = book_manager
        self._book_id = book_id
        self._action = action
        self._task_id = task_id
        self._document_id = document_id
        self._format_id = format_id
        self._output_path = output_path
        self._use_batch = use_batch
        self._use_reembedding = use_reembedding
        self._enable_polish = enable_polish
        self._options = dict(options)
        self._task_store = task_store
        self._notify_task_changed = notify_task_changed
        self._config_snapshot_json = config_snapshot_json

    def _execute(self) -> None:
        if self._action == "run":
            self._run_pipeline()
            return
        if self._action == "cancel":
            self._run_cancel()
            return
        raise ValueError(f"Unknown action: {self._action!r}")

    def _run_pipeline(self) -> None:
        payload = self._current_payload()
        record = self._load_record()
        if (
            self._use_batch
            and record is not None
            and (record.cancel_requested or record.status in {STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})
        ):
            self._request_batch_cancel(payload)
            self.finished_success.emit({"action": "run", "task_id": self._task_id})
            self._notify()
            return

        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(self._task_id, status="running", last_error=None)
        self._notify()
        try:
            session_ctx = (
                WorkflowSession.from_snapshot(self._config_snapshot_json, self._book_id)
                if self._config_snapshot_json
                else WorkflowSession.from_book(self._book_manager, self._book_id)
            )
            with session_ctx as workflow:
                translator_config = workflow.config.translator_config
                if translator_config is not None:
                    translator_config.enable_polish = self._enable_polish

                asyncio.run(self._run_pipeline_async(workflow, payload))

            if self._task_store is not None and self._task_id is not None:
                self._task_store.update(
                    self._task_id,
                    status="completed",
                    phase=PHASE_DONE,
                    cancel_requested=False,
                    last_error=None,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                )
            self.finished_success.emit({"action": "run", "task_id": self._task_id})
        except (_PauseRequestedError, OperationCancelledError):
            self._handle_interrupted(payload)
            raise
        except Exception as exc:
            self._persist_terminal_state("failed", payload, last_error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self._notify()

    async def _run_pipeline_async(self, workflow: Any, payload: dict[str, Any]) -> None:
        if self._needs_ocr(workflow):
            await ocr_ops.run_ocr(
                workflow,
                document_loader=lambda _repo, _ocr_config: bootstrap_ops.load_documents(workflow, [self._document_id]),
                progress_callback=self._on_progress,
                cancel_check=self._is_cancelled,
            )

        await glossary_ops.build_glossary(
            workflow,
            document_ids=[self._document_id],
            progress_callback=self._on_progress,
            cancel_check=self._is_cancelled,
        )
        term_keys = workflow.manager.get_term_keys_for_documents([self._document_id])

        self._update_phase(WorkflowStep.RARE_FILTER.value, completed=0, total=0)
        await workflow.manager.mark_noise_terms(cancel_check=self._is_cancelled, term_keys=term_keys)

        await glossary_ops.review_terms(
            workflow,
            document_ids=[self._document_id],
            term_keys=term_keys,
            progress_callback=self._on_progress,
            cancel_check=self._is_cancelled,
        )
        await glossary_ops.translate_glossary(
            workflow,
            document_ids=[self._document_id],
            term_keys=term_keys,
            progress_callback=self._on_progress,
            cancel_check=self._is_cancelled,
        )

        if self._use_batch:
            payload.update(await self._run_batch_translation(workflow, payload))
        else:
            await translation_ops.translate(
                workflow,
                document_ids=[self._document_id],
                progress_callback=self._on_progress,
                force=False,
                cancel_check=self._is_cancelled,
            )

        if self._use_reembedding:
            documents = bootstrap_ops.load_documents(workflow, [self._document_id])
            for document in documents:
                await export_ops.materialize_document_translation_state(
                    workflow,
                    document,
                    allow_original_fallback=False,
                    cancel_check=self._is_cancelled,
                    progress_callback=self._on_progress,
                )
                await document.reembed(
                    workflow.config.image_reembedding_config,
                    force=False,
                    source_ids=None,
                    cancel_check=self._is_cancelled,
                    progress_callback=self._on_progress,
                )

        preserve_structure = bool(self._options.get("preserve_structure", False))
        if preserve_structure:
            await export_ops.export_preserve_structure(
                workflow,
                output_folder=Path(self._output_path),
                document_ids=[self._document_id],
                allow_original_fallback=False,
                cancel_check=self._is_cancelled,
                progress_callback=self._on_progress,
            )
        else:
            await export_ops.export(
                workflow,
                file_path=Path(self._output_path),
                export_format=self._format_id,
                document_ids=[self._document_id],
                allow_original_fallback=False,
                use_original_images=bool(self._options.get("use_original_images", False)),
                epub_force_horizontal_ltr=bool(self._options.get("epub_force_horizontal_ltr", False)),
                cancel_check=self._is_cancelled,
                progress_callback=self._on_progress,
            )

    async def _run_batch_translation(self, workflow: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if self._task_store is None or self._task_id is None:
            raise ValueError("task_store and task_id are required for one-shot batch translation.")
        executor = BatchTranslationExecutor.from_workflow(
            workflow,
            task_store=self._task_store,
            notify_task_changed=self._notify_task_changed,
        )
        try:
            task = self._task_store.get(self._task_id)
            if task is None:
                raise ValueError(f"Task not found: {self._task_id}")
            payload = await ensure_payload_prepared(
                executor,
                task,
                payload,
                cancel_check=self._is_cancelled,
                progress_callback=self._on_progress,
            )
            if not payload.get("items"):
                return payload

            payload = await run_translation_stage(
                executor,
                self._task_id,
                payload,
                force=False,
                cancel_check=self._is_cancelled,
                progress_callback=self._on_progress,
            )
            payload = await run_polish_stage(
                executor,
                self._task_id,
                payload,
                force=False,
                cancel_check=self._is_cancelled,
                progress_callback=self._on_progress,
            )
            payload = apply_results(executor, self._task_id, payload, progress_callback=self._on_progress)
            failed_items = [item for item in payload.get("items", []) if not is_item_translation_success(item)]
            if failed_items:
                raise RuntimeError("One or more async batch translation items failed.")
            return payload
        finally:
            executor.close()

    def _run_cancel(self) -> None:
        payload = self._current_payload()
        if self._use_batch:
            self._request_batch_cancel(payload)
            self._notify()
            return
        self._persist_terminal_state("cancelled", payload, last_error=None)
        self._notify()

    def _handle_interrupted(self, payload: dict[str, Any]) -> None:
        record = self._load_record()
        if self._use_batch and record is not None and record.cancel_requested:
            self._persist_payload(payload)
            self._request_batch_cancel(payload)
            return

        status = "cancelled" if record is not None and record.cancel_requested else "failed"
        self._persist_terminal_state(status, payload, last_error=None if status == "cancelled" else "Task interrupted.")

    def _persist_terminal_state(self, status: str, payload: dict[str, Any], *, last_error: str | None) -> None:
        if self._task_store is None or self._task_id is None:
            return
        guarded_payload = with_resume_guard(
            payload,
            self._book_manager.get_book_db_path(self._book_id),
            self._document_id,
            required=True,
        )
        self._task_store.update(
            self._task_id,
            status=status,
            phase=PHASE_DONE,
            cancel_requested=False,
            last_error=last_error,
            payload_json=json.dumps(guarded_payload, ensure_ascii=False),
        )

    def _persist_payload(self, payload: dict[str, Any]) -> None:
        if self._task_store is None or self._task_id is None:
            return
        guarded_payload = with_resume_guard(
            payload,
            self._book_manager.get_book_db_path(self._book_id),
            self._document_id,
            required=False,
        )
        self._task_store.update(self._task_id, payload_json=json.dumps(guarded_payload, ensure_ascii=False))

    def _request_batch_cancel(self, payload: dict[str, Any]) -> None:
        if self._task_store is None or self._task_id is None:
            raise ValueError("task_store and task_id are required for one-shot batch cancellation.")
        self._persist_payload(payload)
        session_ctx = self._batch_cancel_session()
        with session_ctx as workflow:
            executor = BatchTranslationExecutor.from_workflow(
                workflow,
                task_store=self._task_store,
                notify_task_changed=self._notify_task_changed,
            )
            try:
                asyncio.run(executor.request_cancel(self._task_id))
            finally:
                executor.close()

    def _batch_cancel_session(self) -> Any:
        if not self._config_snapshot_json:
            return WorkflowSession.from_book(self._book_manager, self._book_id)
        try:
            return WorkflowSession.from_snapshot(self._config_snapshot_json, self._book_id)
        except Exception as snap_exc:
            logger.warning(
                "Config snapshot restore failed for one-shot batch cancel task %s; falling back to live config: %s",
                self._task_id,
                snap_exc,
            )
            return WorkflowSession.from_book(self._book_manager, self._book_id)

    def _load_record(self) -> Any | None:
        if self._task_store is None or self._task_id is None:
            return None
        return self._task_store.get(self._task_id)

    def _needs_ocr(self, workflow: Any) -> bool:
        document = workflow.document_repo.get_document_by_id(self._document_id)
        if document is None:
            return False
        document_type = str(document.get("document_type") or "")
        if document_type not in {"pdf", "scanned_book", "manga"}:
            return False
        return bool(workflow.document_repo.get_document_sources_needing_ocr(self._document_id))

    def _current_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "document_ids": [self._document_id],
            "format_id": self._format_id,
            "output_path": self._output_path,
            "use_batch": self._use_batch,
            "use_reembedding": self._use_reembedding,
            "enable_polish": self._enable_polish,
            "options": dict(self._options),
        }
        if self._task_store is None or self._task_id is None:
            return payload
        record = self._task_store.get(self._task_id)
        if record is None or not record.payload_json:
            return payload
        try:
            existing = json.loads(record.payload_json)
        except (json.JSONDecodeError, TypeError):
            return payload
        if not isinstance(existing, dict):
            return payload
        existing.update(payload)
        return existing

    def _update_phase(self, phase: str, *, completed: int, total: int) -> None:
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(
                self._task_id,
                phase=phase,
                completed_items=completed,
                total_items=total,
            )
        self._notify()

    def _on_progress(self, update: ProgressUpdate) -> None:
        self._raise_if_cancelled()
        self._update_phase(update.step.value, completed=update.current, total=update.total)

    def _notify(self) -> None:
        if self._notify_task_changed is not None:
            self._notify_task_changed(self._book_id)
