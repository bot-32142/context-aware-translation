"""Helpers for startup display behavior across local and packaged runs."""

from __future__ import annotations

from collections.abc import Iterable

from context_aware_translation.ui.constants import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)


def preferred_style_name(platform: str, available_styles: Iterable[str]) -> str | None:
    """Return the best available style for the current platform."""
    style_map = {style.casefold(): style for style in available_styles}

    if platform == "darwin":
        candidates = ("macos", "macintosh", "fusion")
    elif platform.startswith("win"):
        candidates = ("windows11", "windowsvista", "windows", "fusion")
    else:
        return None

    for candidate in candidates:
        style_name = style_map.get(candidate)
        if style_name is not None:
            return style_name
    return next(iter(style_map.values()), None)


def bounds_fit_available_geometries(
    bounds: tuple[int, int, int, int],
    available_geometries: Iterable[tuple[int, int, int, int]],
) -> bool:
    """Return True when saved bounds fit at least one available screen."""
    x, y, width, height = bounds
    geometries = tuple(available_geometries)
    if not geometries:
        return True

    if width <= 0 or height <= 0:
        return False

    fits_screen_dimensions = any(
        width <= available_width and height <= available_height
        for _available_x, _available_y, available_width, available_height in geometries
    )
    if not fits_screen_dimensions:
        return False

    visible_area = sum(_intersection_area((x, y, width, height), available) for available in geometries)
    minimum_visible_area = (width * height) // 2
    return visible_area >= max(1, minimum_visible_area)


def _intersection_area(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> int:
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    overlap_width = min(first_x + first_width, second_x + second_width) - max(first_x, second_x)
    overlap_height = min(first_y + first_height, second_y + second_height) - max(first_y, second_y)
    if overlap_width <= 0 or overlap_height <= 0:
        return 0
    return overlap_width * overlap_height


def preferred_startup_window_size(available_width: int, available_height: int) -> tuple[int, int]:
    """Return a startup window size that stays comfortable on common displays."""
    min_width = min(MIN_WINDOW_WIDTH, available_width)
    min_height = min(MIN_WINDOW_HEIGHT, available_height)

    width = min(DEFAULT_WINDOW_WIDTH, max(min_width, round(available_width * 0.78)))
    height = min(DEFAULT_WINDOW_HEIGHT, max(min_height, round(available_height * 0.82)))
    return width, height
