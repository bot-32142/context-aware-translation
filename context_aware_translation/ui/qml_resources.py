"""Helpers for resolving bundled QML resources."""

from __future__ import annotations

import atexit
import importlib.resources as importlib_resources
from contextlib import ExitStack
from functools import cache
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

_RESOURCE_STACK = ExitStack()
_QML_DIR_NAME = "qml"


@atexit.register
def _close_resource_stack() -> None:
    _RESOURCE_STACK.close()


@cache
def _resource_path(package: str, resource_name: str) -> Path:
    resource = importlib_resources.files(package).joinpath(resource_name)
    return _RESOURCE_STACK.enter_context(importlib_resources.as_file(resource))


def qml_root_path() -> Path:
    """Return a stable filesystem path to bundled QML resources."""
    try:
        return _resource_path("context_aware_translation.ui", _QML_DIR_NAME)
    except Exception:
        qml_path = Path(__file__).parent / _QML_DIR_NAME
        if qml_path.exists():
            return qml_path
        raise


def qml_source(relative_path: str) -> QUrl:
    """Resolve a QML file under the bundled QML root into a local-file URL."""
    qml_path = qml_root_path() / relative_path
    if not qml_path.exists():
        raise FileNotFoundError(f"QML resource not found: {qml_path}")
    return QUrl.fromLocalFile(str(qml_path))


def create_qml_engine(*, parent: QObject | None = None) -> QQmlEngine:
    """Create a QQmlEngine with the packaged QML root on its import path."""
    engine = QQmlEngine(parent)
    engine.addImportPath(str(qml_root_path()))
    return engine


def load_qml_component(engine: QQmlEngine, relative_path: str) -> QQmlComponent:
    """Create a QQmlComponent for a bundled QML file."""
    return QQmlComponent(engine, qml_source(relative_path))
