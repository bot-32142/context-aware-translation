from __future__ import annotations

from dataclasses import dataclass

from context_aware_translation.application.contracts.common import DocumentRef, ProjectRef, SurfaceStatus
from context_aware_translation.application.contracts.work import (
    ContextFrontierState,
    DocumentRowAction,
    WorkboardState,
    WorkDocumentRow,
)
from context_aware_translation.application.events import ApplicationEventKind, WorkboardInvalidatedEvent
from tests.application.fakes import FakeApplicationContext, FakeApplicationServices, FakeWorkService


@dataclass
class WorkSurfaceHarness:
    context: FakeApplicationContext
    project_id: str
    state: WorkboardState | None = None
    refresh_count: int = 0

    def __post_init__(self) -> None:
        self._subscription = self.context.events.subscribe(
            self._on_event,
            kinds={ApplicationEventKind.WORKBOARD_INVALIDATED},
        )

    def load(self) -> None:
        self.state = self.context.services.work.get_workboard(self.project_id)
        self.refresh_count += 1

    def close(self) -> None:
        self._subscription.close()

    def _on_event(self, event: WorkboardInvalidatedEvent) -> None:
        if event.project_id not in {None, self.project_id}:
            return
        self.load()


def _make_state(summary: str) -> WorkboardState:
    return WorkboardState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        context_frontier=ContextFrontierState(summary=summary),
        rows=[
            WorkDocumentRow(
                document=DocumentRef(document_id=4, order_index=4, label="04.png"),
                status=SurfaceStatus.READY,
                state_summary=summary,
                primary_action=DocumentRowAction(kind="open", label="Open"),
            )
        ],
    )


def test_fake_service_pattern_supports_invalidation_plus_requery() -> None:
    services = FakeApplicationServices(work=FakeWorkService(state_by_project={"proj-1": _make_state("Initial")}))
    context = FakeApplicationContext(services=services)
    harness = WorkSurfaceHarness(context=context, project_id="proj-1")
    try:
        harness.load()
        assert harness.state is not None
        assert harness.state.context_frontier is not None
        assert harness.state.context_frontier.summary == "Initial"
        assert harness.refresh_count == 1

        services.work.state_by_project["proj-1"] = _make_state("Updated")
        context.events.publish(WorkboardInvalidatedEvent(project_id="proj-1"))

        assert harness.state is not None
        assert harness.state.context_frontier is not None
        assert harness.state.context_frontier.summary == "Updated"
        assert harness.refresh_count == 2
        assert services.work.calls == [("get_workboard", "proj-1"), ("get_workboard", "proj-1")]
    finally:
        harness.close()
