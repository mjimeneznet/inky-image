"""Tests for ButtonHandler — debounce window, non-blocking dispatch.

Hardware dependencies (gpiod, gpiodevice) are mocked in conftest.py.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from inky_image.button_handler import ButtonHandler, BUTTONS


@pytest.fixture
def handler():
    """ButtonHandler with fake GPIO offsets and a drained executor."""
    h = ButtonHandler({}, debounce_seconds=0.3)
    h._offsets = list(BUTTONS)
    yield h
    h._executor.shutdown(wait=False, cancel_futures=True)


def _event(offset: int) -> MagicMock:
    return MagicMock(line_offset=offset)


def _wait_for(calls: list, expected: int, timeout: float = 1.0) -> bool:
    """Poll until the worker has recorded `expected` calls."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(calls) >= expected:
            return True
        time.sleep(0.01)
    return False


class TestDebounce:
    """Rapid duplicate events from a single physical press are dropped."""

    def test_rapid_second_press_is_dropped(self, handler):
        calls: list[str] = []
        handler.callbacks["B"] = lambda: calls.append("press")
        b_offset = BUTTONS[1]

        handler._handle_event(_event(b_offset))
        # Second edge arrives a few ms later (physical bounce).
        handler._handle_event(_event(b_offset))

        assert _wait_for(calls, 1), "bounce event must not trigger a second action"
        assert len(calls) == 1

    def test_press_after_window_is_accepted(self, handler):
        calls: list[str] = []
        handler.callbacks["B"] = lambda: calls.append("press")
        b_offset = BUTTONS[1]

        handler._handle_event(_event(b_offset))
        # Simulate a genuine second press beyond the debounce window.
        handler._last_press["B"] = time.monotonic() - 0.5
        handler._handle_event(_event(b_offset))

        assert _wait_for(calls, 2), "presses separated by the debounce window must both fire"
        assert len(calls) == 2


class TestNonBlockingDispatch:
    """Callbacks run on a worker thread so the reader never blocks."""

    def test_callback_does_not_block_reader(self, handler):
        started = threading.Event()
        release = threading.Event()

        def slow_action() -> None:
            started.set()
            release.wait(timeout=2.0)

        handler.callbacks["B"] = slow_action
        b_offset = BUTTONS[1]

        t0 = time.monotonic()
        handler._handle_event(_event(b_offset))
        elapsed = time.monotonic() - t0

        assert started.wait(timeout=0.5), "callback should start on the worker thread"
        assert elapsed < 0.2, "reader thread must return without waiting for the callback"
        release.set()

    def test_repeat_presses_queue_in_order(self, handler):
        order: list[str] = []
        handler.callbacks["B"] = lambda: order.append("first")
        handler.callbacks["C"] = lambda: order.append("second")
        b_offset = BUTTONS[1]
        c_offset = BUTTONS[2]

        handler._handle_event(_event(b_offset))
        # A second press on a different button lands while the worker is busy.
        handler._handle_event(_event(c_offset))

        assert _wait_for(order, 2), "both queued actions must run"
        assert order == ["first", "second"], "queued actions must run in arrival order"


class TestLockedCallbacks:
    """Buttons with no registered callback are ignored silently."""

    def test_unregistered_button_is_ignored(self, handler):
        handler._handle_event(_event(BUTTONS[0]))
        assert handler._executor._work_queue.empty()
