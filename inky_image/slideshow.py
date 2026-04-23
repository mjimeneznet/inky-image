"""Slideshow controller."""

from __future__ import annotations

import logging
import threading
from typing import Callable


logger = logging.getLogger(__name__)


class SlideshowController:
	"""Threaded slideshow loop with start/stop/toggle controls."""

	def __init__(
		self,
		interval_seconds_getter: Callable[[], int],
		on_tick: Callable[[], None],
	) -> None:
		self.interval_seconds_getter = interval_seconds_getter
		self.on_tick = on_tick
		self._running_event = threading.Event()
		self._stop_event = threading.Event()
		self._thread: threading.Thread | None = None
		self._lock = threading.RLock()

	def start(self) -> None:
		"""Start slideshow loop."""
		with self._lock:
			self._running_event.set()
			if self._thread and self._thread.is_alive():
				logger.info("Slideshow resumed")
				return
			self._stop_event.clear()
			self._thread = threading.Thread(target=self._loop, name="slideshow", daemon=True)
			self._thread.start()
			logger.info("Slideshow started")

	def stop(self) -> None:
		"""Pause slideshow loop."""
		with self._lock:
			self._running_event.clear()
			logger.info("Slideshow stopped")

	def toggle(self) -> bool:
		"""Toggle slideshow state. Returns True when running."""
		if self.is_running():
			self.stop()
			return False
		self.start()
		return True

	def is_running(self) -> bool:
		"""Return True if slideshow is currently active."""
		return self._running_event.is_set()

	def shutdown(self) -> None:
		"""Fully terminate slideshow thread."""
		self._running_event.clear()
		self._stop_event.set()
		if self._thread and self._thread.is_alive():
			self._thread.join(timeout=3.0)

	def _loop(self) -> None:
		while not self._stop_event.is_set():
			if not self._running_event.is_set():
				self._stop_event.wait(0.2)
				continue
			interval = max(1, int(self.interval_seconds_getter()))
			interrupted = self._stop_event.wait(interval)
			if interrupted:
				break
			if self._running_event.is_set():
				self.on_tick()

