from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from context_aware_translation.adapters.qt.task_engine import TaskEngine
from context_aware_translation.workflow.session import WorkflowSession
from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps

if TYPE_CHECKING:
    from context_aware_translation.storage.library.book_manager import BookManager
    from context_aware_translation.storage.repositories.task_store import TaskStore


def _default_handler_types() -> tuple[type[Any], ...]:
    from context_aware_translation.workflow.tasks.handlers.batch_translation import BatchTranslationHandler
    from context_aware_translation.workflow.tasks.handlers.chunk_retranslation import ChunkRetranslationHandler
    from context_aware_translation.workflow.tasks.handlers.glossary_export import GlossaryExportHandler
    from context_aware_translation.workflow.tasks.handlers.glossary_extraction import GlossaryExtractionHandler
    from context_aware_translation.workflow.tasks.handlers.glossary_review import GlossaryReviewHandler
    from context_aware_translation.workflow.tasks.handlers.glossary_translation import GlossaryTranslationHandler
    from context_aware_translation.workflow.tasks.handlers.image_reembedding import ImageReembeddingHandler
    from context_aware_translation.workflow.tasks.handlers.ocr import OCRHandler
    from context_aware_translation.workflow.tasks.handlers.translate_and_export import TranslateAndExportHandler
    from context_aware_translation.workflow.tasks.handlers.translation_manga import TranslationMangaHandler
    from context_aware_translation.workflow.tasks.handlers.translation_text import TranslationTextHandler

    return (
        BatchTranslationHandler,
        GlossaryExtractionHandler,
        GlossaryReviewHandler,
        GlossaryTranslationHandler,
        ChunkRetranslationHandler,
        GlossaryExportHandler,
        TranslationTextHandler,
        TranslationMangaHandler,
        OCRHandler,
        ImageReembeddingHandler,
        TranslateAndExportHandler,
    )


def build_task_engine(
    *,
    book_manager: BookManager,
    task_store: TaskStore,
    parent: Any | None = None,
    on_task_changed: Callable[[str], None] | None = None,
) -> tuple[TaskEngine, WorkerDeps]:
    """Build the current task runtime without exposing MainWindow bootstrap details."""

    engine_ref: dict[str, TaskEngine] = {}

    def notify_task_changed(book_id: str) -> None:
        engine = engine_ref.get("engine")
        if engine is not None:
            engine.enqueue_task_changed.emit(book_id)
            return
        # During bootstrap there is no engine instance yet. Keep the fallback
        # callback for that narrow window, but once the engine exists all task
        # invalidations must flow through TaskEngine so queued worker updates are
        # coalesced on the UI thread.
        if on_task_changed is not None:
            on_task_changed(book_id)

    bootstrap_deps = WorkerDeps(
        book_manager=book_manager,
        task_store=task_store,
        create_workflow_session=lambda book_id: WorkflowSession.from_book(book_manager, book_id),
        notify_task_changed=notify_task_changed,
    )
    task_engine = TaskEngine(store=task_store, deps=bootstrap_deps, parent=parent)
    engine_ref["engine"] = task_engine

    worker_deps = WorkerDeps(
        book_manager=book_manager,
        task_store=task_store,
        create_workflow_session=lambda book_id: WorkflowSession.from_book(book_manager, book_id),
        notify_task_changed=notify_task_changed,
        enqueue_followup=task_engine.enqueue_followup_task,
    )
    task_engine._core._deps = worker_deps

    for handler_type in _default_handler_types():
        task_engine.register_handler(handler_type())

    task_engine.recover_interrupted_tasks()

    return task_engine, worker_deps
