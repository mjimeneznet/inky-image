"""Tests for ImageManager — mode switching, dirty flag, navigation guards.

All hardware dependencies (PIL, inky, gpiod) are mocked in conftest.py so
these tests run on any machine.
"""

from __future__ import annotations

import pytest


class TestDirtyFlag:
    """The _dirty flag controls whether refresh_images() rescans sources."""

    def test_dirty_flag_initial(self, empty_manager):
        """_dirty starts True, but __init__ calls refresh_images which clears it."""
        # refresh_images() runs during __init__ and clears _dirty
        assert empty_manager._dirty is False

    def test_dirty_flag_after_get_status(self, manager):
        """get_status refreshes and clears dirty flag."""
        manager._dirty = True
        manager.get_status()
        assert manager._dirty is False

    def test_dirty_after_mutation(self, manager):
        """Mutations like reshuffle set dirty flag."""
        # Ensure images exist so reshuffle doesn't trigger a refresh that clears _dirty
        manager.set_active_directory(0)
        manager.get_status()
        assert manager._dirty is False
        manager.reshuffle()
        assert manager._dirty is True


class TestModeSwitching:
    """Switching between slideshow modes."""

    def test_mode_switching(self, manager):
        manager.set_mode("image_list")
        assert manager.get_mode() == "image_list"
        manager.set_mode("url")
        assert manager.get_mode() == "url"
        manager.set_mode("upload")
        assert manager.get_mode() == "upload"
        manager.set_mode("directory")
        assert manager.get_mode() == "directory"

    def test_invalid_mode_fallback(self, manager):
        from inky_image.image_manager import ImageManager

        # Access the protected config to set an invalid mode
        manager.config.set("slideshow_mode", "bogus")
        result = ImageManager.get_mode(manager)
        assert result == "directory"


class TestZeroDivisionGuard:
    """_normalized_current_image_index doesn't crash on empty lists."""

    def test_zero_division_guard(self, manager):
        from inky_image.image_manager import ImageManager

        result = ImageManager._normalized_current_image_index(manager, 0, False)
        assert result == 0