from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.common import AcceptedCommand
from context_aware_translation.application.contracts.queue import QueueActionRequest, QueueState


class QueueService(Protocol):
    def get_queue(self, *, project_id: str | None = None) -> QueueState: ...

    def apply_action(self, request: QueueActionRequest) -> AcceptedCommand: ...
