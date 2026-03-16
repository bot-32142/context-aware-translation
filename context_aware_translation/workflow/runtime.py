from __future__ import annotations

from dataclasses import dataclass

from context_aware_translation.config import Config
from context_aware_translation.core.context_manager import TranslationContextManagerAdapter
from context_aware_translation.core.context_tree import ContextTree
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB


@dataclass
class WorkflowContext:
    """Data-only workflow context passed to workflow ops."""

    config: Config
    llm_client: LLMClient
    context_tree: ContextTree
    manager: TranslationContextManagerAdapter
    db: SQLiteBookDB
    document_repo: DocumentRepository
    book_id: str | None = None
    owns_context_tree: bool = True

    def close(self) -> None:
        self.manager.close()
        if self.owns_context_tree:
            self.context_tree.close()
        self.db.close()
