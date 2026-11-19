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

    def display_image_path(self, image_path: str, **_kwargs) -> None:
        self.rendered.append(image_path)
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
