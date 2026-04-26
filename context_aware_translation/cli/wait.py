from __future__ import annotations

from PySide6.QtCore import QEventLoop, QTimer

from context_aware_translation.application.composition import ApplicationContext
from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES

from .output import EXIT_NOT_FOUND, CliError


def wait_for_task(context: ApplicationContext, task_id: str, *, poll_interval_ms: int = 250) -> TaskRecord:
    record = context.runtime.task_store.get(task_id)
    if record is None:
        raise CliError(
            "not_found", f"Task not found: {task_id}", exit_code=EXIT_NOT_FOUND, details={"task_id": task_id}
        )
    if record.status in TERMINAL_TASK_STATUSES:
        return record

    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(poll_interval_ms)

    state: dict[str, TaskRecord | None] = {"record": record}

    def _poll() -> None:
        context.runtime.task_engine.tick()
        current = context.runtime.task_store.get(task_id)
        state["record"] = current
        if current is None or current.status in TERMINAL_TASK_STATUSES:
            loop.quit()

    timer.timeout.connect(_poll)
    timer.start()
    try:
        _poll()
        if state["record"] is not None and state["record"].status not in TERMINAL_TASK_STATUSES:
            loop.exec()
    except KeyboardInterrupt:
        context.runtime.task_engine.cancel(task_id)
        raise
    finally:
        timer.stop()

    final_record = state["record"]
    if final_record is None:
        raise CliError(
            "not_found", f"Task not found: {task_id}", exit_code=EXIT_NOT_FOUND, details={"task_id": task_id}
        )
    return final_record
