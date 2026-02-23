from types import TracebackType
from typing import TYPE_CHECKING

from context_aware_translation.config import Config, WorkflowRuntimeConfig
from context_aware_translation.core.context_tree_registry import ContextTreeRegistry
from context_aware_translation.workflow.bootstrap import _build_context_tree, _build_llm_client, build_workflow_runtime
from context_aware_translation.workflow.runtime import WorkflowRuntime
from context_aware_translation.workflow.service import WorkflowService

if TYPE_CHECKING:
    from context_aware_translation.storage.book_manager import BookManager


class WorkflowSession:
    """Lifecycle owner that boots runtime resources and exposes WorkflowService."""

    def __init__(self, config: Config):
        self.config = config
        self._workflow: WorkflowService | None = None
        self._runtime: WorkflowRuntime | None = None
        self._book_id: str | None = None

    @classmethod
    def from_book(
        cls,
        book_manager: "BookManager",
        book_id: str,
    ) -> "WorkflowSession":
        """Create a workflow session using a book's resolved config."""
        book = book_manager.get_book(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        config = Config.from_book(book, book_manager.library_root, book_manager.registry)
        session = cls(config)
        session._book_id = book_id
        return session

    def _build_runtime(self, runtime_config: WorkflowRuntimeConfig) -> WorkflowRuntime:
        if self._book_id is not None:
            context_tree = ContextTreeRegistry.acquire(
                self._book_id,
                lambda: _build_context_tree(runtime_config, _build_llm_client(runtime_config)),
            )
            return build_workflow_runtime(self.config, runtime_config, book_id=self._book_id, context_tree=context_tree)
        return build_workflow_runtime(self.config, runtime_config, book_id=self._book_id)

    @staticmethod
    def _build_workflow_service(runtime: WorkflowRuntime) -> WorkflowService:
        return WorkflowService(
            config=runtime.config,
            llm_client=runtime.llm_client,
            context_tree=runtime.context_tree,
            manager=runtime.manager,
            db=runtime.db,
            document_repo=runtime.document_repo,
            book_id=runtime.book_id,
        )

    def __enter__(self) -> WorkflowService:
        runtime_config = self.config.get_workflow_runtime_config()
        try:
            self._runtime = self._build_runtime(runtime_config)
        except Exception:
            # If build fails after registry acquire, release the ref
            if self._book_id is not None:
                ContextTreeRegistry.release(self._book_id)
            raise
        self._workflow = self._build_workflow_service(self._runtime)
        return self._workflow

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        try:
            if self._runtime is not None:
                self._runtime.close()
        finally:
            if self._book_id is not None:
                ContextTreeRegistry.release(self._book_id)
        self._runtime = None
        self._workflow = None
