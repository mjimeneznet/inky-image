"""E-ink display rendering for Inky Impression."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageOps

try:
	from inky.auto import auto
except ImportError:  # pragma: no cover - hardware dependency
	auto = None


logger = logging.getLogger(__name__)


class DisplayManager:
	"""Wraps Inky display initialization and image rendering pipeline."""

	def __init__(self) -> None:
		if auto is None:
			raise RuntimeError("inky library is not available. Install dependencies first.")
		self._display = auto()
		self._display.set_border(self._display.BLACK)
		self.width = int(self._display.width)
		self.height = int(self._display.height)
		logger.info("Detected Inky display resolution %sx%s", self.width, self.height)

	def display_image_path(
		self,
		image_path: str,
		saturation: float = 0.5,
		scale_to_fit: bool = True,
		target_width: int | None = None,
		target_height: int | None = None,
	) -> None:
		"""Load a file, convert for e-ink and render on screen."""
		path_obj = Path(image_path)
		if not path_obj.exists():
			raise FileNotFoundError(f"Image not found: {image_path}")
		with Image.open(path_obj) as source:
			image = source.copy()
		self.display_pil_image(
			image,
			saturation=saturation,
			scale_to_fit=scale_to_fit,
			target_width=target_width,
			target_height=target_height,
		)

	def display_pil_image(
		self,
		image: Image.Image,
		saturation: float = 0.5,
		scale_to_fit: bool = True,
		target_width: int | None = None,
		target_height: int | None = None,
	) -> None:
		"""Process and show a PIL image on Inky display."""
		processed = self._prepare_image(
			image,
			scale_to_fit=scale_to_fit,
			target_width=target_width,
			target_height=target_height,
		)
		saturation = max(0.0, min(1.0, float(saturation)))
		self._display.set_image(processed, saturation=saturation)
		self._display.show()

	def _prepare_image(
		self,
		image: Image.Image,
		scale_to_fit: bool = True,
		target_width: int | None = None,
		target_height: int | None = None,
	) -> Image.Image:
		"""Apply orientation fix, colorspace conversion and resize."""
		img = ImageOps.exif_transpose(image)
		if img.mode != "RGB":
			img = img.convert("RGB")
		width = int(target_width) if target_width is not None else self.width
		height = int(target_height) if target_height is not None else self.height
		width = max(64, width)
		height = max(64, height)
		resized = self._resize_image(img, (width, height), scale_to_fit=scale_to_fit)
		if (width, height) != (self.width, self.height):
			# Keep compatibility with hardware by adapting configured render size to real panel size.
			return self._resize_image(resized, (self.width, self.height), scale_to_fit=scale_to_fit)
		return resized

	@staticmethod
	def _resize_image(
		image: Image.Image,
		desired_size: tuple[int, int],
		scale_to_fit: bool = True,
	) -> Image.Image:
		"""
		Resize image using InkyPi-like behavior:
		- scale_to_fit=True  -> crop/fill display (ImageOps.fit)
		- scale_to_fit=False -> keep full image + padding (ImageOps.pad)

		Based on InkyPi image_folder plugin behavior.
		"""
		desired_width, desired_height = int(desired_size[0]), int(desired_size[1])
		dimensions = (desired_width, desired_height)
		if scale_to_fit:
			return ImageOps.fit(image, dimensions, method=Image.LANCZOS)
		return ImageOps.pad(image, dimensions, color="white", method=Image.LANCZOS)

