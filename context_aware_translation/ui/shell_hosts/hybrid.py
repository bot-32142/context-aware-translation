from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QDialog, QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from context_aware_translation.ui.main import qml_root_path, qml_source


class QmlChromeHost(QQuickWidget):
    """Small QQuickWidget wrapper for reusable shell chrome loading."""

    def __init__(
        self,
        qml_relative_path: str,
        *,
        context_objects: Mapping[str, object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.engine().addImportPath(str(qml_root_path()))
        for name, value in (context_objects or {}).items():
            self.rootContext().setContextProperty(name, value)
        self.setSource(qml_source(qml_relative_path))
        self._raise_if_failed(qml_relative_path)

    def set_context_property(self, name: str, value: object) -> None:
        self.rootContext().setContextProperty(name, value)

    def _raise_if_failed(self, qml_relative_path: str) -> None:
        if self.status() != QQuickWidget.Status.Error:
            return
        errors = "\n".join(error.toString() for error in self.errors())
        raise RuntimeError(f"Failed to load QML chrome '{qml_relative_path}':\n{errors}")


class HybridShellHost(QWidget):
    """Generic QWidget host that combines QML chrome with swap-in QWidget content."""

    current_content_changed = Signal(str)

    def __init__(
        self,
        qml_relative_path: str,
        *,
        orientation: Qt.Orientation = Qt.Orientation.Vertical,
        chrome_first: bool = True,
        context_objects: Mapping[str, object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._content_widgets: dict[str, QWidget] = {}
        self._current_content_key: str | None = None
        self.chrome_host = QmlChromeHost(qml_relative_path, context_objects=context_objects, parent=self)
        self.content_stack = QStackedWidget(self)
        self.content_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._layout = _new_layout(orientation, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        if chrome_first:
            self._layout.addWidget(self.chrome_host)
            self._layout.addWidget(self.content_stack, 1)
        else:
            self._layout.addWidget(self.content_stack, 1)
            self._layout.addWidget(self.chrome_host)

    def set_context_property(self, name: str, value: object) -> None:
        self.chrome_host.set_context_property(name, value)

    def register_content(self, key: str, widget: QWidget) -> QWidget:
        if key in self._content_widgets:
            old_widget = self.remove_content(key)
            if old_widget is not None:
                old_widget.deleteLater()
        self._content_widgets[key] = widget
        self.content_stack.addWidget(widget)
        if self._current_content_key is None:
            self.show_content(key)
        return widget

    def remove_content(self, key: str) -> QWidget | None:
        widget = self._content_widgets.pop(key, None)
        if widget is None:
            return None
        self.content_stack.removeWidget(widget)
        if self._current_content_key == key:
            self._current_content_key = None
            next_key = next(iter(self._content_widgets), None)
            if next_key is not None:
                self.show_content(next_key)
        return widget

    def show_content(self, key: str) -> None:
        widget = self._content_widgets[key]
        self._current_content_key = key
        self.content_stack.setCurrentWidget(widget)
        self.current_content_changed.emit(key)

    def current_content_key(self) -> str | None:
        return self._current_content_key

    def content_widget(self, key: str) -> QWidget | None:
        return self._content_widgets.get(key)

    def cleanup(self) -> None:
        for key in list(self._content_widgets):
            widget = self.remove_content(key)
            if widget is None:
                continue
            cleanup = getattr(widget, "cleanup", None)
            if callable(cleanup):
                cleanup()
            widget.deleteLater()


class HybridDialogHost(QDialog):
    """Simple dialog container for QML chrome plus one hosted QWidget body."""

    def __init__(
        self,
        qml_relative_path: str,
        *,
        context_objects: Mapping[str, object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.chrome_host = QmlChromeHost(qml_relative_path, context_objects=context_objects, parent=self)
        self.body_widget: QWidget | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self.chrome_host)

    def set_context_property(self, name: str, value: object) -> None:
        self.chrome_host.set_context_property(name, value)

    def set_body_widget(self, widget: QWidget) -> QWidget:
        if self.body_widget is not None:
            self._layout.removeWidget(self.body_widget)
            self.body_widget.deleteLater()
        self.body_widget = widget
        self._layout.addWidget(widget, 1)
        return widget


def _new_layout(orientation: Qt.Orientation, parent: QWidget) -> QVBoxLayout | QHBoxLayout:
    if orientation == Qt.Orientation.Horizontal:
        return QHBoxLayout(parent)
    return QVBoxLayout(parent)
