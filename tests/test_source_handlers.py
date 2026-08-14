"""Tests for source handlers — discovery, URL validation, cache lifecycle.

All hardware dependencies (PIL, inky, gpiod) are mocked in conftest.py so
these tests run on any machine.  Network access is mocked via unittest.mock.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from inky_image.image_manager import (
    _DirectorySource,
    _ImageListSource,
    _UrlSource,
    _UploadSource,
    SUPPORTED_EXTENSIONS,
)


class TestDirectorySource:
    """_DirectorySource: image discovery in active directory."""

    def test_responds_to_expected_methods(self, config, tmp_path):
        handler = _DirectorySource(config)
        assert handler.mode_name() == "directory"
        assert handler.list_sources() == list(config.get("directories", []))

    def test_refresh_empty_when_no_directories(self, config):
        handler = _DirectorySource(config)
        result = handler.refresh()
        assert result.images == []
        assert result.error is None

    def test_refresh_with_images(self, config, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        (img_dir / "pic1.jpg").write_text("data")
        (img_dir / "pic2.png").write_text("data")

        config.add_directory(str(img_dir))
        config.set_active_directory(0)

        handler = _DirectorySource(config)
        result = handler.refresh()
        assert len(result.images) == 2
        assert all(p.endswith((".jpg", ".png")) for p in result.images)

    def test_refresh_nonexistent_directory(self, config):
        config._data["directories"] = ["/nonexistent/path"]
        config._data["active_directory_index"] = 0

        handler = _DirectorySource(config)
        result = handler.refresh()
        assert result.images == []
        assert "not valid" in (result.error or "")


class TestImageListSource:
    """_ImageListSource: selected image resolution."""

    def test_responds_to_expected_methods(self, config):
        handler = _ImageListSource(config)
        assert handler.mode_name() == "image_list"
        assert handler.list_sources() == []

    def test_refresh_empty(self, config):
        handler = _ImageListSource(config)
        result = handler.refresh()
        assert result.images == []
        assert result.error is None

    def test_refresh_with_valid_images(self, config, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_text("data")
        config.add_selected_image(str(img))

        handler = _ImageListSource(config)
        result = handler.refresh()
        assert len(result.images) == 1
        assert result.images[0].endswith("photo.jpg")


class TestUrlSource:
    """_UrlSource: URL validation, caching, download orchestration."""

    def test_responds_to_expected_methods(self, config):
        handler = _UrlSource(config)
        assert handler.mode_name() == "url"
        assert handler.list_sources() == []

    def test_refresh_empty(self, config):
        handler = _UrlSource(config)
        result = handler.refresh()
        assert result.images == []
        assert result.error is None

    def test_invalid_url_scheme_handled_by_image_manager(self, config, manager):
        """ImageManager.add_url_image validates the URL scheme before calling the handler."""
        # add_url_image in ImageManager checks for http/https scheme
        result = manager.add_url_image("ftp://example.com/img.jpg")
        assert result is False
        error = manager.get_last_scan_error()
        assert error is not None and "http" in error.lower()

    def test_download_failure_graceful(self, config, manager):
        """A URL that can't be reached returns False without crashing."""
        result = manager.add_url_image("http://192.0.2.1/nonexistent.jpg")
        assert result is False


class TestUploadSource:
    """_UploadSource: uploaded image lifecycle."""

    def test_responds_to_expected_methods(self, config):
        handler = _UploadSource(config)
        assert handler.mode_name() == "upload"
        assert handler.list_sources() == []

    def test_refresh_empty(self, config):
        handler = _UploadSource(config)
        result = handler.refresh()
        assert result.images == []
        assert result.error is None

    def test_refresh_with_uploaded_files(self, config, tmp_path):
        img = tmp_path / "uploaded.png"
        img.write_text("data")
        config.add_uploaded_image(str(img))

        handler = _UploadSource(config)
        result = handler.refresh()
        assert len(result.images) == 1
        assert result.images[0].endswith("uploaded.png")