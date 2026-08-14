"""Hardware button handling for Inky side buttons."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import gpiod
import gpiodevice
from gpiod.line import Bias, Direction, Edge


logger = logging.getLogger(__name__)

BUTTONS = [5, 6, 16, 24]
LABELS = ["A", "B", "C", "D"]
INPUT = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP, edge_detection=Edge.FALLING)


class ButtonHandler:
	"""Background button listener using gpiod edge events."""

	def __init__(
		self,
		callbacks: dict[str, Callable[[], None]],
		debounce_seconds: float = 0.3,
	) -> None:
		self.callbacks = callbacks
		self.debounce_seconds = debounce_seconds
		self._stop_event = threading.Event()
		self._thread: threading.Thread | None = None
		self._request = None
		self._offsets: list[int] = []
		self._last_press = {label: 0.0 for label in LABELS}
		# Single worker so button actions never overlap. The reader thread
		# stays free to debounce bounce events even while an e-ink render
		# (which can take seconds) is running in the worker.
		self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="button-action")

	def start(self) -> None:
		"""Start button listening thread."""
		if self._thread and self._thread.is_alive():
			return
		self._setup_gpio()
		self._thread = threading.Thread(target=self._run, name="button-handler", daemon=True)
		self._thread.start()
		logger.info("Button handler started")

	def stop(self) -> None:
		"""Stop listener and release GPIO lines."""
		self._stop_event.set()
		if self._thread and self._thread.is_alive():
			self._thread.join(timeout=2.0)
		self._executor.shutdown(wait=False, cancel_futures=True)
		if self._request is not None:
			try:
				self._request.release()
			except Exception:  # pragma: no cover - hardware cleanup path
				pass
		logger.info("Button handler stopped")

	def _setup_gpio(self) -> None:
		chip = gpiodevice.find_chip_by_platform()
		self._offsets = [chip.line_offset_from_id(gpio_id) for gpio_id in BUTTONS]
		line_config = dict.fromkeys(self._offsets, INPUT)
		self._request = chip.request_lines(consumer="inky-image-buttons", config=line_config)

	def _run(self) -> None:
		while not self._stop_event.is_set():
			try:
				events = self._read_events()
				if not events:
					continue
				# Drop backlog and process only latest press. The executor in
				# _handle_event keeps the reader free during renders, so this
				# only guards against bursts between read_edge_events calls.
				self._handle_event(events[-1])
			except Exception as exc:  # pragma: no cover - hardware runtime
				logger.exception("Button handling error: %s", exc)
				time.sleep(0.3)

	def _read_events(self) -> list:
		"""Read available events with compatibility for different gpiod versions."""
		if hasattr(self._request, "wait_edge_events"):
			if not self._request.wait_edge_events(timeout=1.0):
				return []
		return list(self._request.read_edge_events())

	def _handle_event(self, event) -> None:
		offset = event.line_offset
		if offset not in self._offsets:
			return
		index = self._offsets.index(offset)
		label = LABELS[index]
		now = time.monotonic()
		if now - self._last_press[label] < self.debounce_seconds:
			return
		self._last_press[label] = now
		logger.info("Button %s pressed", label)
		callback = self.callbacks.get(label)
		if callback:
			# Run on a worker thread so a long e-ink render does not block
			# this reader loop. While the worker renders, the reader keeps
			# reading edge events and the debounce check above correctly
			# drops bounce events from the same physical press. Genuine
			# repeat presses queue up and run in order after the render.
			future = self._executor.submit(callback)
			future.add_done_callback(self._log_action_exception)

	def _log_action_exception(self, future) -> None:
		"""Log exceptions raised by button action callbacks."""
		try:
			future.result()
		except Exception:  # pragma: no cover - defensive
			logger.exception("Button action failed")

