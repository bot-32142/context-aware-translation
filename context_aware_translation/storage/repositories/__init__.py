"""Repository-style storage interfaces."""

from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.repositories.llm_batch_store import (
    STATUS_COMPLETED as LLM_STATUS_COMPLETED,
)
from context_aware_translation.storage.repositories.llm_batch_store import (
    STATUS_FAILED as LLM_STATUS_FAILED,
)
from context_aware_translation.storage.repositories.llm_batch_store import (
    STATUS_SUBMITTED as LLM_STATUS_SUBMITTED,
)
from context_aware_translation.storage.repositories.llm_batch_store import (
    LLMBatchRecord,
    LLMBatchStore,
)
from context_aware_translation.storage.repositories.task_store import TaskRecord, TaskStore
from context_aware_translation.storage.repositories.term_repository import BatchUpdate, StorageManager, TermRepository
from context_aware_translation.storage.repositories.translation_batch_task_store import (
    PHASE_APPLY,
    PHASE_DONE,
    PHASE_POLISH_FALLBACK,
    PHASE_POLISH_POLL,
    PHASE_POLISH_SUBMIT,
    PHASE_POLISH_VALIDATE,
    PHASE_PREPARE,
    PHASE_TRANSLATION_FALLBACK,
    PHASE_TRANSLATION_POLL,
    PHASE_TRANSLATION_SUBMIT,
    PHASE_TRANSLATION_VALIDATE,
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLED,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TERMINAL_TASK_STATUSES,
    TranslationBatchTaskRecord,
    TranslationBatchTaskStore,
)

__all__ = [
    "BatchUpdate",
    "DocumentRepository",
    "LLM_STATUS_COMPLETED",
    "LLM_STATUS_FAILED",
    "LLM_STATUS_SUBMITTED",
    "LLMBatchRecord",
    "LLMBatchStore",
    "PHASE_APPLY",
    "PHASE_DONE",
    "PHASE_POLISH_FALLBACK",
    "PHASE_POLISH_POLL",
    "PHASE_POLISH_SUBMIT",
    "PHASE_POLISH_VALIDATE",
    "PHASE_PREPARE",
    "PHASE_TRANSLATION_FALLBACK",
    "PHASE_TRANSLATION_POLL",
    "PHASE_TRANSLATION_SUBMIT",
    "PHASE_TRANSLATION_VALIDATE",
    "STATUS_CANCELLED",
    "STATUS_CANCELLING",
    "STATUS_CANCEL_REQUESTED",
    "STATUS_COMPLETED",
    "STATUS_COMPLETED_WITH_ERRORS",
    "STATUS_FAILED",
    "STATUS_PAUSED",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "StorageManager",
    "TaskRecord",
    "TaskStore",
    "TermRepository",
    "TERMINAL_TASK_STATUSES",
    "TranslationBatchTaskRecord",
    "TranslationBatchTaskStore",
]
