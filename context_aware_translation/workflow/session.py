import json
from types import TracebackType
from typing import TYPE_CHECKING

from context_aware_translation.config import CONFIG_SNAPSHOT_VERSION, Config, WorkflowRuntimeConfig
from context_aware_translation.workflow.bootstrap import build_workflow_runtime
from context_aware_translation.workflow.runtime import WorkflowContext

if TYPE_CHECKING:
    from context_aware_translation.storage.library.book_manager import BookManager


class WorkflowSession:
    """Lifecycle owner for WorkflowContext resources."""

    def __init__(self, config: Config):
        self.config = config
        self._runtime: WorkflowContext | None = None
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

    @classmethod
    def from_snapshot(cls, config_snapshot_json: str, book_id: str) -> "WorkflowSession":
        payload = json.loads(config_snapshot_json)
        if isinstance(payload, dict) and "snapshot_version" in payload and "config" in payload:
            version = int(payload["snapshot_version"])
            if version != CONFIG_SNAPSHOT_VERSION:
                raise ValueError(f"Unsupported config snapshot version: {version}")
            config_dict = payload["config"]
        else:
            config_dict = payload
        config = Config.from_dict(config_dict)
        session = cls(config)
        session._book_id = book_id
        return session

    def _build_runtime(self, runtime_config: WorkflowRuntimeConfig) -> WorkflowContext:
        return build_workflow_runtime(self.config, runtime_config, book_id=self._book_id)

    def __enter__(self) -> WorkflowContext:
        runtime_config = self.config.get_workflow_runtime_config()
        self._runtime = self._build_runtime(runtime_config)
        return self._runtime

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        if self._runtime is not None:
            self._runtime.close()
        self._runtime = None
