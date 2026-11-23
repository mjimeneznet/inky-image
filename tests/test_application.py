"""Tests for the Application render pipeline (no real display attached)."""

from __future__ import annotations

import threading

import pytest


class BlockingDisplay:
    """DisplayManager stand-in that reports when a refresh is under way."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.rendered: list[str] = []
        self.kwargs: list[dict] = []

    def display_image_path(self, image_path: str, **kwargs) -> None:
        self.rendered.append(image_path)
        self.kwargs.append(kwargs)
        self.entered.set()
        self.release.wait(5)


class FailingDisplay:
    """DisplayManager stand-in that always fails the refresh."""

    def display_image_path(self, image_path: str, **_kwargs) -> None:
        raise RuntimeError("panel write failed")


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Application backed by a temp config and a blocking display."""
    monkeypatch.setenv("INKY_IMAGE_CONFIG_PATH", str(tmp_path / "config.json"))

    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "a.jpg").write_text("fake-a")
    (img_dir / "b.jpg").write_text("fake-b")

    from inky_image.main import Application

    application = Application()
    application.display = BlockingDisplay()
    application.image_manager.add_directory(str(img_dir))
    application.image_manager.set_active_directory(0)
    yield application
    display = application.display
    if hasattr(display, "release"):
        display.release.set()
    application.slideshow.shutdown()


def test_render_in_progress_covers_the_whole_locked_section(app, monkeypatch):
    """The busy flag is up while the render lock is held, not just in show()."""
    entered = threading.Event()
    release = threading.Event()

    def blocking_next():
        entered.set()
        release.wait(5)
        return None

    monkeypatch.setattr(app.image_manager, "next_image_path", blocking_next)

    worker = threading.Thread(target=app.render_next_image, daemon=True)
    worker.start()
    assert entered.wait(5), "render action never reached the image manager"
    try:
        assert app.is_render_in_progress() is True
    finally:
        release.set()
        worker.join(5)

    assert app.is_render_in_progress() is False


def test_dropped_render_while_busy_leaves_flag_low(app):
    """A dropped action reports False and does not claim a refresh is running."""
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock():
        with app._render_lock:
            acquired.set()
            release.wait(5)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    assert acquired.wait(5)
    try:
        assert app.render_current_image() is False
        assert app.is_render_in_progress() is False
        assert app.last_render_outcome() == "busy"
    finally:
        release.set()
        holder.join(5)


def test_render_flag_is_cleared_after_a_failed_refresh(app, monkeypatch):
    """A failing panel write returns False and does not leave the flag stuck."""
    app.display = FailingDisplay()

    assert app.render_current_image() is False
    assert app.is_render_in_progress() is False
    assert app.last_render_outcome() == "failed"


def test_render_reports_an_empty_source(app, tmp_path):
    """Nothing to show is its own outcome, not a display failure."""
    for image in (tmp_path / "images").iterdir():
        image.unlink()
    app.image_manager.set_active_directory(0)

    assert app.render_current_image() is False
    assert app.last_render_outcome() == "empty"


def test_identical_render_is_skipped_but_reports_success(app):
    """A no-op repaint still means the panel already shows the image."""
    assert app.render_current_image() is True
    assert app.display.rendered == [str(app.image_manager.current_image_path())]

    assert app.render_current_image() is True
    assert len(app.display.rendered) == 1


def test_stop_waits_for_an_in_flight_refresh(app):
    """stop() must not return while the panel is being written."""
    render = threading.Thread(target=app.render_current_image, daemon=True)
    render.start()
    assert app.display.entered.wait(5), "the blocking display was never entered"

    stopper = threading.Thread(target=app.stop, daemon=True)
    stopper.start()
    stopper.join(0.3)
    assert stopper.is_alive(), "stop() returned while the panel was mid-refresh"

    app.display.release.set()
    render.join(5)
    stopper.join(5)
    assert stopper.is_alive() is False


def test_force_repaints_the_same_image(app):
    """The identical-render skip must not block healing a bad panel."""
    assert app.render_current_image() is True
    assert len(app.display.rendered) == 1

    assert app.render_current_image() is True
    assert len(app.display.rendered) == 1, "an identical render is still skipped"

    assert app.render_current_image(force=True) is True
    assert len(app.display.rendered) == 2, "force must repaint the same image"


def test_changing_tone_settings_forces_a_repaint(app):
    """Brightness and contrast are part of the render signature."""
    assert app.render_current_image() is True
    assert len(app.display.rendered) == 1
    assert app.display.kwargs[-1]["brightness"] == 1.0
    assert app.display.kwargs[-1]["contrast"] == 1.0

    app.config.set("brightness", 1.2)
    assert app.render_current_image() is True
    assert len(app.display.rendered) == 2
    assert app.display.kwargs[-1]["brightness"] == 1.2

    app.config.set("contrast", 1.4)
    assert app.render_current_image() is True
    assert len(app.display.rendered) == 3
    assert app.display.kwargs[-1]["contrast"] == 1.4


def test_preview_applies_form_overrides_without_saving(app):
    """The preview must run on candidate values, leaving the config alone."""
    seen: dict = {}

    class Preview:
        def save(self, _buffer, format=None):
            return None

    def fake_preview(image_path, **kwargs):
        seen.update(kwargs)
        seen["image_path"] = image_path
        return Preview()

    app.display.preview_image_path = fake_preview
    app.config.set("contrast", 1.1)

    app.render_preview_png({"contrast": 1.6, "scale_to_fit": False})

    assert seen["contrast"] == 1.6, "override must win over the saved value"
    assert seen["scale_to_fit"] is False
    assert seen["saturation"] == 0.5, "unrelated values still come from the config"
    assert app.config.get("contrast") == 1.1, "preview must not persist anything"
    assert app._render_lock.acquire(blocking=False) is True, "lock must be released"
    app._render_lock.release()


def test_preview_falls_back_to_the_last_rendered_image(app):
    """The panel shows the last render; the preview should show the same."""
    app.image_manager.deactivate_directory(0)
    app.config.set("last_rendered_image_path", str(app.no_image_path))
    seen: dict = {}

    class Preview:
        def save(self, _buffer, format=None):
            return None

    def fake_preview(image_path, **kwargs):
        seen["image_path"] = image_path
        return Preview()

    app.display.preview_image_path = fake_preview

    app.render_preview_png()

    assert seen["image_path"] == str(app.no_image_path)
    assert app.preview_unavailable_reason() == "", "a successful preview has no reason"


def test_preview_translates_size_overrides(app):
    """The route speaks render_width; the display takes target_width."""
    seen: dict = {}

    class Preview:
        def save(self, _buffer, format=None):
            return None

    def fake_preview(image_path, **kwargs):
        seen.update(kwargs)
        return Preview()

    app.display.preview_image_path = fake_preview

    app.render_preview_png({"render_width": 640, "render_height": 400})

    assert seen["target_width"] == 640
    assert seen["target_height"] == 400


def test_render_mode_reaches_the_display_and_forces_a_repaint(app):
    assert app.render_current_image() is True
    assert app.display.kwargs[-1]["render_mode"] == "default"
    assert len(app.display.rendered) == 1

    app.config.set("render_mode", "oklab")
    assert app.render_current_image() is True
    assert len(app.display.rendered) == 2, "switching strategy must repaint"
    assert app.display.kwargs[-1]["render_mode"] == "oklab"


def test_panel_palette_reaches_the_display_and_forces_a_repaint(app):
    assert app.render_current_image() is True
    assert app.display.kwargs[-1]["palette_source"] == "driver"
    assert len(app.display.rendered) == 1

    app.config.set("panel_palette", "pure")
    assert app.render_current_image() is True
    assert len(app.display.rendered) == 2, "a palette change must repaint"
    assert app.display.kwargs[-1]["palette_source"] == "pure"

    hexes = "#000000, #ffffff, #00ff00, #0000ff, #ff0000, #ffff00, #ff8c00"
    app.config.set("panel_palette", "custom")
    app.config.set("panel_palette_custom", hexes)
    assert app.render_current_image() is True
    assert len(app.display.rendered) == 3
    assert app.display.kwargs[-1]["palette_source"] == hexes
