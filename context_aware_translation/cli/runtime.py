from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from context_aware_translation.application.composition import ApplicationContext, build_application_context


def ensure_core_application() -> QCoreApplication:
    app = QCoreApplication.instance()
    if isinstance(app, QCoreApplication):
        return app
    return QCoreApplication([])


@contextmanager
def cli_context(library_root: Path | None) -> Iterator[ApplicationContext]:
    ensure_core_application()
    context = build_application_context(library_root=library_root)
    try:
        yield context
    finally:
        context.close()
