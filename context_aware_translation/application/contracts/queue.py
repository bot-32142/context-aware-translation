from __future__ import annotations

from pydantic import Field

from context_aware_translation.application.contracts.common import (
    BlockerInfo,
    ContractModel,
    NavigationTarget,
    ProgressInfo,
    QueueActionKind,
    QueueStatus,
)


class QueueItem(ContractModel):
    queue_item_id: str
    title: str
    project_id: str | None = None
    document_id: int | None = None
    status: QueueStatus
    stage: str | None = None
    progress: ProgressInfo | None = None
    blocker: BlockerInfo | None = None
    error_message: str | None = None
    related_target: NavigationTarget | None = None
    available_actions: list[QueueActionKind] = Field(default_factory=list)


class QueueState(ContractModel):
    items: list[QueueItem] = Field(default_factory=list)


class QueueActionRequest(ContractModel):
    queue_item_id: str
    action: QueueActionKind
