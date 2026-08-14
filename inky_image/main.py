"""Main entry point for Inky Image Viewer service."""

from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path

from waitress import serve

from inky_image.button_handler import ButtonHandler
from inky_image.config import ConfigManager
from inky_image.display import DisplayManager
from inky_image.image_manager import ImageManager
from inky_image.renderer import Renderer
from inky_image.slideshow import SlideshowController
from inky_image.web_app import create_web_app


logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


class Application(Renderer):
	"""Coordinates display, buttons, slideshow and web UI."""

	def __init__(self) -> None:
		self.config = ConfigManager()
		# Service should always boot with slideshow stopped.
		self.config.set("slideshow_running", False)
		self.image_manager = ImageManager(self.config)
		self.display = DisplayManager()
		self._render_lock = threading.RLock()
		self._shutdown_event = threading.Event()
		self._button_handler: ButtonHandler | None = None
		self._web_server_failed = False
		self.no_image_path = Path(__file__).resolve().parent.parent / "static" / "no-image.jpg"
		self._last_render_signature: tuple[str, float, bool, int, int] | None = None
		self._last_action: dict[str, str] | None = None
		self._action_lock = threading.RLock()

		self.slideshow = SlideshowController(
			interval_seconds_getter=lambda: int(self.config.get("slideshow_interval", 30)),
			on_tick=self.render_next_image,
		)

		self.web_app = create_web_app(
			config=self.config,
			image_manager=self.image_manager,
			slideshow=self.slideshow,
			renderer=self,
		)

	def render_current_image(self) -> bool:
		"""Render current image on the e-ink display."""
		if not self._acquire_render_lock():
			return False
		try:
			image_path = self.image_manager.current_image_path()
			if image_path:
				return self._render_image_path_locked(image_path, "image")

			if self.image_manager.get_mode() == "directory":
				if self.image_manager.get_active_directory() is None:
					return self._render_no_image_placeholder_locked()
				logger.warning("No image available to display")
				return False
			return self._render_no_image_placeholder_locked()
		finally:
			self._render_lock.release()

	def _render_no_image_placeholder_locked(self) -> bool:
		"""Render placeholder when no directories are configured."""
		if not self.no_image_path.exists():
			logger.warning("No directories configured and placeholder missing: %s", self.no_image_path)
			return False
		return self._render_image_path_locked(str(self.no_image_path), "no-image placeholder")

	def render_next_image(self) -> bool:
		"""Advance image index and render."""
		if not self._acquire_render_lock():
			return False
		try:
			image_path = self.image_manager.next_image_path()
			if not image_path:
				logger.warning("No next image to display")
				return False
			return self._render_image_path_locked(image_path, "next image", force=True)
		finally:
			self._render_lock.release()

	def render_previous_image(self) -> bool:
		"""Go back image index and render."""
		if not self._acquire_render_lock():
			return False
		try:
			image_path = self.image_manager.previous_image_path()
			if not image_path:
				logger.warning("No previous image to display")
				return False
			return self._render_image_path_locked(image_path, "previous image", force=True)
		finally:
			self._render_lock.release()

	def cycle_mode_and_render(self) -> bool:
		"""Switch to next slideshow mode and render current image."""
		if not self._acquire_render_lock():
			return False
		try:
			modes = ["directory", "image_list", "url", "upload"]
			current_mode = self.image_manager.get_mode()
			if current_mode in modes:
				next_mode = modes[(modes.index(current_mode) + 1) % len(modes)]
			else:
				next_mode = "directory"
			ok = self.image_manager.set_mode(next_mode)
			if not ok:
				logger.warning("Failed to cycle slideshow mode from %s", current_mode)
				return False
			logger.info("Switched slideshow mode from %s to %s", current_mode, next_mode)
			image_path = self.image_manager.current_image_path()
			if not image_path:
				return self._render_no_image_placeholder_locked()
			return self._render_image_path_locked(image_path, f"{next_mode} mode image")
		finally:
			self._render_lock.release()

	def _acquire_render_lock(self) -> bool:
		"""Acquire render lock without waiting; drop action if display is busy."""
		acquired = self._render_lock.acquire(blocking=False)
		if not acquired:
			logger.info("Display is busy refreshing, dropping action")
		return acquired

	def _render_image_path_locked(self, image_path: str, label: str, force: bool = False) -> bool:
		"""Render image while render lock is held."""
		saturation = float(self.config.get("saturation", 0.5))
		scale_to_fit = bool(self.config.get("scale_to_fit", True))
		render_width = int(self.config.get("render_width", 800))
		render_height = int(self.config.get("render_height", 480))
		signature = (image_path, saturation, scale_to_fit, render_width, render_height)
		if not force and self._last_render_signature == signature:
			logger.info("Skipping render for %s (same image and settings)", label)
			return True

		try:
			self.display.display_image_path(
				image_path=image_path,
				saturation=saturation,
				scale_to_fit=scale_to_fit,
				target_width=render_width,
				target_height=render_height,
			)
			self._last_render_signature = signature
			self.config.set("last_rendered_image_path", image_path)
			logger.info("Displayed %s: %s", label, image_path)
			return True
		except Exception as exc:  # pragma: no cover - hardware path
			logger.exception("Failed to display %s %s: %s", label, image_path, exc)
			return False

	def _setup_buttons(self) -> None:
		callbacks = {
			"A": lambda: self._run_button_action("A", self._toggle_slideshow_from_button),
			"B": lambda: self._run_button_action("B", self.render_next_image),
			"C": lambda: self._run_button_action("C", self.render_previous_image),
			"D": lambda: self._run_button_action("D", self.cycle_mode_and_render),
		}
		self._button_handler = ButtonHandler(callbacks=callbacks, debounce_seconds=0.3)
		self._button_handler.start()

	def _run_button_action(self, label: str, action) -> None:
		"""Execute physical button callback unless button lock is enabled."""
		if bool(self.config.get("lock_buttons", False)):
			logger.info("Ignoring button %s: physical buttons are locked", label)
			return
		with self._action_lock:
			self._last_action = {"action": label, "ts": str(time.monotonic())}
		action()

	def _toggle_slideshow_from_button(self) -> None:
		is_running = self.slideshow.toggle()
		self.config.set("slideshow_running", is_running)
		logger.info("Slideshow running: %s", is_running)

	def _setup_signals(self) -> None:
		def _signal_handler(signum, _frame):
			logger.info("Received signal %s, shutting down", signum)
			self._shutdown_event.set()

		signal.signal(signal.SIGTERM, _signal_handler)
		signal.signal(signal.SIGINT, _signal_handler)

	def _start_web_server(self) -> None:
		port = int(self.config.get("web_port", 80))
		try:
			serve(self.web_app, host="0.0.0.0", port=port, threads=8)
		except Exception:
			self._web_server_failed = True
			logger.exception("Web UI server failed to start on port %s", port)
			self._shutdown_event.set()

	def run(self) -> None:
		"""Start all components and block until shutdown."""
		self._setup_signals()
		self._setup_buttons()
		# Avoid an expensive startup repaint on e-ink. Keep whatever is already on
		# screen until an explicit user action or slideshow tick requests a render.
		logger.info("Skipping startup render to speed up service restart")

		web_thread = threading.Thread(target=self._start_web_server, name="web-ui", daemon=True)
		web_thread.start()
		logger.info("Web UI started on port %s", self.config.get("web_port", 80))

		while not self._shutdown_event.is_set():
			time.sleep(0.3)

		self.stop()
		if self._web_server_failed:
			raise RuntimeError("Web UI server startup failed")

	def stop(self) -> None:
		"""Stop background services cleanly."""
		self.slideshow.shutdown()
		if self._button_handler:
			self._button_handler.stop()
		logger.info("Inky Image Viewer stopped")

	def get_last_rendered_image_path(self) -> str | None:
		"""Return image path last rendered to the physical e-ink display."""
		path = self.config.get("last_rendered_image_path")
		if not isinstance(path, str) or not path.strip():
			return None
		return path

	def get_last_action(self) -> dict[str, str] | None:
		"""Return the last physical button action without clearing it."""
		with self._action_lock:
			return self._last_action

	def pop_last_action(self) -> dict[str, str] | None:
		"""Atomically read and clear the last button action."""
		with self._action_lock:
			result = self._last_action
			self._last_action = None
			return result


def main() -> None:
	"""Executable entry point."""
	app = Application()
	app.run()


if __name__ == "__main__":
	main()

