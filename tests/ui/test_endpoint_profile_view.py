"""Tests for endpoint profile view interactions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

from context_aware_translation.storage.endpoint_profile import EndpointProfile

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _make_profile(profile_id: str, name: str) -> EndpointProfile:
    return EndpointProfile(
        profile_id=profile_id,
        name=name,
        created_at=1.0,
        updated_at=1.0,
        base_url="https://example.com/v1",
        model="model-a",
    )


def test_duplicate_uses_incremented_copy_name_when_copy_exists():
    from context_aware_translation.ui.views.endpoint_profile_view import EndpointProfileView

    original = _make_profile("p1", "Alpha")
    copy = _make_profile("p2", "Alpha (Copy)")
    duplicated = _make_profile("p3", "Alpha (Copy) 2")

    manager = MagicMock()
    manager.list_endpoint_profiles.return_value = [original, copy]
    manager.create_endpoint_profile.return_value = duplicated

    view = EndpointProfileView(manager)
    view.table.selectRow(0)
    view._on_duplicate()

    assert manager.create_endpoint_profile.call_count == 1
    kwargs = manager.create_endpoint_profile.call_args.kwargs
    assert kwargs["name"] == "Alpha (Copy) 2"


def test_get_selected_profile_falls_back_to_current_index():
    from context_aware_translation.ui.views.endpoint_profile_view import EndpointProfileView

    profile = _make_profile("p1", "Alpha")
    manager = MagicMock()
    manager.list_endpoint_profiles.return_value = [profile]

    view = EndpointProfileView(manager)
    first_index = view.model.index(0, 0)
    view.table.setCurrentIndex(first_index)
    view.table.clearSelection()

    selected = view._get_selected_profile()
    assert selected is not None
    assert selected.profile_id == "p1"


def test_refresh_preserves_selection():
    from context_aware_translation.ui.views.endpoint_profile_view import EndpointProfileView

    profile1 = _make_profile("p1", "Alpha")
    profile2 = _make_profile("p2", "Beta")

    manager = MagicMock()
    manager.list_endpoint_profiles.return_value = [profile1, profile2]

    view = EndpointProfileView(manager)
    view.table.selectRow(1)
    assert view._get_selected_profile() is not None
    assert view._get_selected_profile().profile_id == "p2"

    view.refresh()

    selected = view._get_selected_profile()
    assert selected is not None
    assert selected.profile_id == "p2"
