"""Tests for ImageManager navigation — next/prev/wrap, reshuffle, empty state.

All hardware dependencies (PIL, inky, gpiod) are mocked in conftest.py so
these tests run on any machine.
"""

from __future__ import annotations

import pytest


class TestNavigationWraps:
    """Next/previous navigation wraps around image list."""

    def test_navigation_wraps(self, manager):
        """Next wraps around to first image."""
        manager.set_active_directory(0)
        manager.get_status()  # trigger full refresh

        first = manager.current_image_path()
        assert first is not None

        # Navigate through all 3 images + wrap
        manager.next_image_path()
        manager.next_image_path()
        manager.next_image_path()  # wrap to first
        assert manager.current_image_path() == first

    def test_next_prev_consistency(self, manager):
        """After N nexts, N prevs returns to start."""
        manager.set_active_directory(0)
        manager.get_status()
        first = manager.current_image_path()
        assert first is not None

        steps = 2
        for _ in range(steps):
            manager.next_image_path()
        for _ in range(steps):
            manager.previous_image_path()

        assert manager.current_image_path() == first


class TestReshuffle:
    """reshuffle keeps the current image in the list and as the active index."""

    def test_reshuffle_preserves_current(self, manager):
        manager.set_active_directory(0)
        manager.get_status()
        current = manager.current_image_path()
        assert current is not None

        manager.reshuffle()
        # After reshuffle, current_image_path should still return the same image
        assert manager.current_image_path() == current


class TestNoImages:
    """Navigation methods return None when no images available."""

    def test_no_images_returns_none(self, empty_manager):
        assert empty_manager.current_image_path() is None
        assert empty_manager.next_image_path() is None
        assert empty_manager.previous_image_path() is None