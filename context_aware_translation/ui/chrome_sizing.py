from __future__ import annotations

from shiboken6 import isValid


def sync_qml_host_height(chrome_host) -> None:  # noqa: ANN001
    if chrome_host is None or not isValid(chrome_host):
        return
    root = chrome_host.rootObject()
    if root is None:
        return
    implicit_height = root.property("implicitHeight")
    try:
        chrome_height = max(int(float(implicit_height)), 0)
    except (TypeError, ValueError):
        return
    if chrome_height <= 0:
        return
    chrome_host.setMinimumHeight(chrome_height)
    chrome_host.setMaximumHeight(chrome_height)
    chrome_host.updateGeometry()
