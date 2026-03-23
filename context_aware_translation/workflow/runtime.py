from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from context_aware_translation.config import Config
from context_aware_translation.core.context_manager import TranslationContextManagerAdapter
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB


@dataclass
class WorkflowContext:
    """Data-only workflow context passed to workflow ops."""

    config: Config
    llm_client: LLMClient
    manager: TranslationContextManagerAdapter
    db: SQLiteBookDB
    document_repo: DocumentRepository
    context_tree: Any | None = None
    book_id: str | None = None

    def close(self) -> None:
        self.manager.close()
        self.db.close()
