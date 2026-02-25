"""Task UI view-models, mappers, and widgets."""

from .task_view_model_mapper import map_task_to_row_vm, map_tasks_to_row_vms
from .task_view_models import TaskRowVM

__all__ = [
    "TaskConsole",
    "TaskRowVM",
    "map_task_to_row_vm",
    "map_tasks_to_row_vms",
]


def __getattr__(name: str):  # lazy — keeps mapper-only imports free of PySide6
    if name == "TaskConsole":
        from .task_console import TaskConsole

        return TaskConsole
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
