"""Shared fixtures and mocks for inky-image tests.

All hardware-dependent modules (PIL, inky, gpiod, gpiodevice) are mocked in
sys.modules before any inky_image module is imported so tests run without a
Raspberry Pi, Inky display, or network.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# System-level mocks — installed before any inky_image import so module-level
# ``from PIL import Image`` etc. resolve to mock objects.
# ---------------------------------------------------------------------------

_pil_mock = MagicMock()
_pil_image_mock = MagicMock()
_pil_imageops_mock = MagicMock()

# Ensure Image.open returns a useful mock
_fake_image = MagicMock()
_fake_image.format = "JPEG"
_fake_image.verify.return_value = None
_pil_image_mock.open.return_value.__enter__.return_value = _fake_image

_pil_mock.Image = _pil_image_mock
_pil_mock.ImageOps = _pil_imageops_mock

_inky_mock = MagicMock()
_gpiod_mock = MagicMock()
_gpiodevice_mock = MagicMock()

_SYSTEM_MOCKS: dict[str, MagicMock] = {
    "PIL": _pil_mock,
    "PIL.Image": _pil_image_mock,
    "PIL.ImageOps": _pil_imageops_mock,
    "inky": _inky_mock,
    "inky.auto": MagicMock(),
    "gpiod": _gpiod_mock,
    "gpiodevice": _gpiodevice_mock,
}

for _mod_name, _mock in _SYSTEM_MOCKS.items():
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _mock

# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

import pytest


@pytest.fixture(autouse=True)
def mock_pil():
    """Ensure PIL mocks are active during every test (belt-and-braces)."""
    with patch.dict("sys.modules", _SYSTEM_MOCKS, clear=False):
        yield


@pytest.fixture
def config(tmp_path):
    """Create a ConfigManager backed by a temporary JSON file."""
    from inky_image.config import ConfigManager

    cfg_path = tmp_path / "config.json"
    cfg = ConfigManager(str(cfg_path))
    # Reset mutable collections so tests start clean
    cfg._data["directories"] = []
    cfg._data["selected_images"] = []
    cfg._data["url_images"] = []
    cfg._data["uploaded_images"] = []
    cfg._data["active_directory_index"] = -1
    cfg._data["current_image_index"] = 0
    cfg.save()
    return cfg


@pytest.fixture
def manager(config, tmp_path):
    """Create an ImageManager with a temp directory containing test images."""
    import time

    from inky_image.image_manager import ImageManager

    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "a.jpg").write_text("fake-a")
    (img_dir / "b.jpg").write_text("fake-b")
    time.sleep(0.01)  # ensure distinct mtimes
    (img_dir / "c.jpg").write_text("fake-c")

    config.add_directory(str(img_dir))
    im = ImageManager(config)
    return im


@pytest.fixture
def empty_manager(config):
    """Create an ImageManager with no directories configured."""
    from inky_image.image_manager import ImageManager

    return ImageManager(config)