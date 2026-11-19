"""Tests for SlideshowController lifecycle and concurrency."""

from __future__ import annotations

import pytest


@pytest.fixture
def controller():
    from inky_image.slideshow import SlideshowController

    ctrl = SlideshowController(
        interval_seconds_getter=lambda: 30, on_tick=lambda: None
    )
    yield ctrl
    ctrl.shutdown()


def test_toggle_flips_state(controller):
    assert controller.is_running() is False

    assert controller.toggle() is True
    assert controller.is_running() is True

    assert controller.toggle() is False
    assert controller.is_running() is False


def test_toggle_decides_while_holding_the_lock(controller, monkeypatch):
    """A racing toggle must not read the state outside the lock.

    A probe thread proves ownership: it cannot take the RLock while the
    deciding thread holds it.
    """
    import threading

    held: list[bool] = []
    real_is_running = controller.is_running

    def held_by_caller() -> bool:
        got: list[bool] = []

        def probe() -> None:
            acquired = controller._lock.acquire(timeout=0.05)
            got.append(acquired)
            if acquired:
                controller._lock.release()

        prober = threading.Thread(target=probe, daemon=True)
        prober.start()
        prober.join(1)
        return not got[0]

    def spy() -> bool:
        held.append(held_by_caller())
        return real_is_running()

    monkeypatch.setattr(controller, "is_running", spy)

    controller.toggle()

    assert held, "toggle() never consulted the run state"
    assert all(held), "toggle() read the run state outside the lock"


def test_shutdown_is_terminal(controller):
    """After shutdown a late web request cannot resurrect the slideshow."""
    controller.shutdown()

    assert controller.toggle() is False
    assert controller.is_running() is False

    thread_before = controller._thread
    controller.start()
    assert controller.is_running() is False
    assert controller._thread is thread_before
