from dataclasses import dataclass

from context_aware_translation.config import Config
from context_aware_translation.core.context_manager import TranslationContextManagerAdapter
from context_aware_translation.core.context_tree import ContextTree
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.document_repository import DocumentRepository


@dataclass
class WorkflowRuntime:
    """Owned runtime resources for a workflow context."""

    config: Config
    llm_client: LLMClient
    context_tree: ContextTree
    manager: TranslationContextManagerAdapter
    db: SQLiteBookDB
    document_repo: DocumentRepository
    book_id: str | None = None

    def close(self) -> None:
        self.manager.close()
        self.context_tree.close()
        self.db.close()
