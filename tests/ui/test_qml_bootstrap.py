from __future__ import annotations

import pytest

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


def test_qml_bootstrap_probe_loads():
    from context_aware_translation.ui.main import create_qml_engine, load_qml_component, qml_root_path

    qml_dir = qml_root_path()
    assert qml_dir.name == "qml"
    assert (qml_dir / "BootstrapProbe.qml").exists()

    engine = create_qml_engine()
    component = load_qml_component(engine, "BootstrapProbe.qml")

    errors = [error.toString() for error in component.errors()]
    assert not errors

    instance = component.create()
    try:
        assert instance is not None
        assert instance.objectName() == "qmlBootstrapProbe"
        assert instance.property("bootstrapMessage") == "CAT QML bootstrap ready"
    finally:
        if instance is not None:
            instance.deleteLater()


def test_qml_bootstrap_resolves_nested_shell_resources():
    from context_aware_translation.ui.main import create_qml_engine, load_qml_component, qml_source
    from context_aware_translation.ui.viewmodels.app_shell import AppShellViewModel

    nested_urls = [
        qml_source("app/AppShellChrome.qml"),
        qml_source("dialogs/project_settings/ProjectSettingsDialogChrome.qml"),
        qml_source("document/DocumentShellChrome.qml"),
    ]
    assert all(url.isLocalFile() for url in nested_urls)
    assert all(url.toLocalFile().endswith(".qml") for url in nested_urls)

    engine = create_qml_engine()
    engine.rootContext().setContextProperty("appShell", AppShellViewModel())
    component = load_qml_component(engine, "app/AppShellChrome.qml")

    errors = [error.toString() for error in component.errors()]
    assert not errors

    instance = component.create()
    try:
        assert instance is not None
        assert instance.objectName() == "appShellChrome"
    finally:
        if instance is not None:
            instance.deleteLater()
