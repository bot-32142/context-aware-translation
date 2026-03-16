from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.common import DocumentSection
from context_aware_translation.ui.shell_hosts.document_shell_host import DocumentShellHost

try:
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

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


class _DocumentPane(QWidget):
    def __init__(self, name: str, running_operations: list[str] | None = None) -> None:
        super().__init__()
        self.setObjectName(name)
        self.running_operations = list(running_operations or [])
        self.activations = 0
        self.cancel_requests: list[bool] = []
        self.cleanup_calls = 0
        self.retranslate_calls = 0

    def activate_view(self) -> None:
        self.activations += 1

    def get_running_operations(self) -> list[str]:
        return list(self.running_operations)

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        self.cancel_requests.append(include_engine_tasks)

    def cleanup(self) -> None:
        self.cleanup_calls += 1

    def retranslate(self) -> None:
        self.retranslate_calls += 1


def test_document_shell_host_loads_qml_chrome_and_switches_sections() -> None:
    host = DocumentShellHost()
    ocr = _DocumentPane("ocr")
    terms = _DocumentPane("terms")
    translation = _DocumentPane("translation")
    images = _DocumentPane("images")
    export = _DocumentPane("export")

    host.set_ocr_widget(ocr)
    host.set_terms_widget(terms)
    host.set_translation_widget(translation)
    host.set_images_widget(images)
    host.set_export_widget(export)
    host.set_document_context("proj-1", 9, "Chapter 9", section=DocumentSection.TRANSLATION)

    root = host.chrome_host.rootObject()
    assert root is not None
    assert root.objectName() == "documentShellChrome"
    assert root.property("surfaceTitleText") == "Chapter 9"
    assert root.property("translationSelected") is True
    assert host.current_section() is DocumentSection.TRANSLATION
    assert host.current_content_key() == DocumentSection.TRANSLATION.value
    assert translation.activations == 1

    host.show_export_view()
    assert root.property("exportSelected") is True
    assert host.current_section() is DocumentSection.EXPORT
    assert host.current_content_key() == DocumentSection.EXPORT.value
    assert export.activations == 1


def test_document_shell_host_handles_qml_navigation_and_back_signal() -> None:
    host = DocumentShellHost()
    host.set_ocr_widget(QLabel("ocr"))
    host.set_terms_widget(QLabel("terms"))
    host.set_translation_widget(QLabel("translation"))
    host.set_images_widget(QLabel("images"))
    host.set_export_widget(QLabel("export"))
    host.set_document_context("proj-1", 11, "Chapter 11", section=DocumentSection.OCR)

    backs: list[bool] = []
    host.back_requested.connect(lambda: backs.append(True))

    root = host.chrome_host.rootObject()
    assert root is not None

    root.termsRequested.emit()
    assert host.current_section() is DocumentSection.TERMS
    assert host.current_content_key() == DocumentSection.TERMS.value

    root.imagesRequested.emit()
    assert host.current_section() is DocumentSection.IMAGES
    assert host.current_content_key() == DocumentSection.IMAGES.value

    root.backRequested.emit()
    assert backs == [True]


def test_document_shell_host_creates_missing_sections_on_demand() -> None:
    host = DocumentShellHost()
    created_sections: list[DocumentSection] = []
    activations: list[DocumentSection] = []

    def _factory(section: DocumentSection) -> QWidget:
        created_sections.append(section)
        return _DocumentPane(section.value)

    def _on_show(section: DocumentSection, widget: QWidget) -> None:
        activations.append(section)
        assert widget.objectName() == section.value

    host.set_section_widget_factory(_factory)
    host.set_section_show_handler(_on_show)
    host.set_document_context("proj-1", 13, "Chapter 13", section=DocumentSection.TRANSLATION)

    assert created_sections == [DocumentSection.TRANSLATION]
    assert activations == [DocumentSection.TRANSLATION]
    assert host.current_content_key() == DocumentSection.TRANSLATION.value

    host.show_images_view()
    assert created_sections == [DocumentSection.TRANSLATION, DocumentSection.IMAGES]
    assert activations == [DocumentSection.TRANSLATION, DocumentSection.IMAGES]
    assert host.current_content_key() == DocumentSection.IMAGES.value


def test_document_shell_host_delegates_running_operations_retranslate_and_cleanup() -> None:
    host = DocumentShellHost()
    ocr = _DocumentPane("ocr", running_operations=["ocr"])
    export = _DocumentPane("export", running_operations=["export"])

    host.set_ocr_widget(ocr)
    host.set_export_widget(export)
    host.set_document_context("proj-1", 15, "Chapter 15", section=DocumentSection.OCR)

    assert host.get_running_operations() == ["ocr"]

    host.request_cancel_running_operations(include_engine_tasks=True)
    assert ocr.cancel_requests == [True]

    host.show_export_view()
    assert host.get_running_operations() == ["export"]

    host.retranslate()
    assert ocr.retranslate_calls == 1
    assert export.retranslate_calls == 1

    host.cleanup()
    assert ocr.cleanup_calls == 1
    assert export.cleanup_calls == 1
    assert host.current_content_key() is None
