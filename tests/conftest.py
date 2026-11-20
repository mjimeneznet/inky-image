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
    "gpiod.line": _gpiod_mock,
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


# ---------------------------------------------------------------------------
# Flask-web-app fixtures — the ``client`` fixture needs a RendererStub so the
# app can be constructed without a real Inky display.
# ---------------------------------------------------------------------------


class RendererStub:
    """Minimal Renderer implementation tracking calls for test assertions."""

    def __init__(self) -> None:
        self.render_current_image_calls = 0
        self.render_next_image_calls = 0
        self.render_previous_image_calls = 0
        self.cycle_mode_and_render_calls = 0
        self._last_rendered_image_path: str | None = None
        self._last_action: dict[str, str] | None = None
        self._render_in_progress = False
        self._render_outcome = "ok"

    def _record_render(self) -> bool:
        """Report whether the simulated refresh reached the panel."""
        return self._render_outcome == "ok"

    def render_current_image(self) -> bool:
        self.render_current_image_calls += 1
        return self._record_render()

    def render_next_image(self) -> bool:
        self.render_next_image_calls += 1
        return self._record_render()

    def render_previous_image(self) -> bool:
        self.render_previous_image_calls += 1
        return self._record_render()

    def cycle_mode_and_render(self) -> bool:
        self.cycle_mode_and_render_calls += 1
        return self._record_render()

    def last_render_outcome(self) -> str:
        return self._render_outcome

    def set_render_outcome(self, outcome: str) -> None:
        """Drive the render-outcome contract the routes must report."""
        self._render_outcome = outcome

    def get_last_rendered_image_path(self) -> str | None:
        return self._last_rendered_image_path

    def get_last_action(self) -> dict[str, str] | None:
        return self._last_action

    def pop_last_action(self) -> dict[str, str] | None:
        action = self._last_action
        self._last_action = None
        return action

    def is_render_in_progress(self) -> bool:
        return self._render_in_progress

    def set_last_action(self, action: dict[str, str] | None) -> None:
        self._last_action = action

    def set_render_in_progress(self, value: bool) -> None:
        """Drive the busy-badge contract the UI polls for."""
        self._render_in_progress = value

    def set_last_rendered_image_path(self, path: str) -> None:
        self._last_rendered_image_path = path


@pytest.fixture
def client(config, manager, tmp_path):
    """Create a Flask test client for inky_image.web_app.create_web_app.

    Sets INKY_IMAGE_BROWSE_ROOTS to a temporary directory so all path-
    traversal and browse tests operate inside a known, safe sandbox.
    """
    import os

    browse_root = tmp_path / "browse_root"
    browse_root.mkdir()
    os.environ["INKY_IMAGE_BROWSE_ROOTS"] = str(browse_root)

    from inky_image.slideshow import SlideshowController
    from inky_image.web_app import create_web_app

    slideshow = SlideshowController(
        interval_seconds_getter=lambda: 30, on_tick=lambda: None
    )
    renderer = RendererStub()
    app = create_web_app(config, manager, slideshow, renderer)
    app.config["TESTING"] = True

    client = app.test_client()
    # Reach the stub from tests via ``client.application.renderer_stub``.
    app.renderer_stub = renderer
    yield client

    slideshow.shutdown()
    os.environ.pop("INKY_IMAGE_BROWSE_ROOTS", None)
