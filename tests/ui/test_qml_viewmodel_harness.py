from __future__ import annotations

from pathlib import Path

import pytest

from context_aware_translation.application.contracts.common import DocumentSection
from context_aware_translation.ui.viewmodels.router import PrimaryRoute, RouteStateViewModel

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_qml_component_can_bind_to_route_state_viewmodel(tmp_path: Path):
    from context_aware_translation.ui.main import create_qml_engine

    qml_file = tmp_path / "RouteStateHarness.qml"
    qml_file.write_text(
        """
import QtQuick

QtObject {
    id: root
    objectName: "routeStateHarness"
    property string primaryRoute: routeModel.primary_route
    property string scopeName: routeModel.scope
    property string modalRoute: routeModel.modal_route
}
""".strip(),
        encoding="utf-8",
    )

    engine = create_qml_engine()
    route_model = RouteStateViewModel()
    engine.rootContext().setContextProperty("routeModel", route_model)

    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_file)))
    errors = [error.toString() for error in component.errors()]
    assert not errors

    instance = component.create()
    try:
        assert instance is not None
        assert instance.objectName() == "routeStateHarness"
        assert instance.property("primaryRoute") == "projects"
        assert instance.property("scopeName") == "app"
        assert instance.property("modalRoute") == ""

        route_model.open_project("proj-1", primary=PrimaryRoute.TERMS)
        assert instance.property("primaryRoute") == "terms"
        assert instance.property("scopeName") == "project"

        route_model.open_document("proj-1", 4, DocumentSection.TRANSLATION)
        assert instance.property("primaryRoute") == "work"
        assert instance.property("scopeName") == "document"

        route_model.open_queue(project_id="proj-1")
        assert instance.property("modalRoute") == "queue"
    finally:
        if instance is not None:
            instance.deleteLater()
