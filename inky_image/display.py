"""E-ink display rendering for Inky Impression."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:
    from inky.auto import auto
except ImportError:  # pragma: no cover - hardware dependency
    auto = None


logger = logging.getLogger(__name__)


class DisplayManager:
    """Wraps Inky display initialization and image rendering pipeline."""

    def __init__(self) -> None:
        if auto is None:
            raise RuntimeError(
                "inky library is not available. Install dependencies first."
            )
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
        brightness: float = 1.0,
        contrast: float = 1.0,
        render_mode: str = "default",
        palette_source: str = "driver",
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
            brightness=brightness,
            contrast=contrast,
            render_mode=render_mode,
            palette_source=palette_source,
        )

    def display_pil_image(
        self,
        image: Image.Image,
        saturation: float = 0.5,
        scale_to_fit: bool = True,
        target_width: int | None = None,
        target_height: int | None = None,
        brightness: float = 1.0,
        contrast: float = 1.0,
        render_mode: str = "default",
        palette_source: str = "driver",
    ) -> None:
        """Process and show a PIL image on Inky display."""
        processed = self._prepare_image(
            image,
            scale_to_fit=scale_to_fit,
            target_width=target_width,
            target_height=target_height,
            brightness=brightness,
            contrast=contrast,
            render_mode=render_mode,
        )
        self._show_prepared(processed, saturation, render_mode, palette_source)

    def prepare_image_path(
        self,
        image_path: str,
        scale_to_fit: bool = True,
        target_width: int | None = None,
        target_height: int | None = None,
        brightness: float = 1.0,
        contrast: float = 1.0,
        render_mode: str = "default",
        palette_source: str = "driver",
    ) -> Image.Image:
        """Load and convert a file exactly as a real render would.

        Split out so a caller can inspect the frame without touching the panel.
        """
        path_obj = Path(image_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        with Image.open(path_obj) as source:
            image = source.copy()
        return self._prepare_image(
            image,
            scale_to_fit=scale_to_fit,
            target_width=target_width,
            target_height=target_height,
            brightness=brightness,
            contrast=contrast,
            render_mode=render_mode,
        )

    def preview_image_path(
        self,
        image_path: str,
        saturation: float = 0.5,
        scale_to_fit: bool = True,
        target_width: int | None = None,
        target_height: int | None = None,
        brightness: float = 1.0,
        contrast: float = 1.0,
        render_mode: str = "default",
        palette_source: str = "driver",
    ) -> Image.Image:
        """Return the frame the panel would show, dithering included.

        Runs the same preparation as a real render and then the driver's own
        quantiser, rebuilding the result with the blended palette. ``show()`` is
        never called, so the panel is untouched.
        """
        prepared = self.prepare_image_path(
            image_path,
            scale_to_fit=scale_to_fit,
            target_width=target_width,
            target_height=target_height,
            brightness=brightness,
            contrast=contrast,
            render_mode=render_mode,
            palette_source=palette_source,
        )
        if render_mode == "default":
            return self._quantise_for_preview(prepared, saturation)
        return self._palette_image(prepared, render_mode, palette_source).convert(
            "RGB"
        )

    def _quantise_for_preview(
        self, image: Image.Image, saturation: float
    ) -> Image.Image:
        """Map a prepared frame through the driver palette, without showing it."""
        driver = self._display
        blend = getattr(driver, "_palette_blend", None)
        set_image = getattr(driver, "set_image", None)
        if blend is None or set_image is None:
            return image
        saturation = max(0.0, min(1.0, float(saturation)))
        try:
            set_image(image, saturation=saturation)
            buf = getattr(driver, "buf", None)
            palette = list(blend(saturation))
            if buf is None or len(palette) < 24:
                return image
            preview = Image.fromarray(buf.astype("uint8"), mode="P")
            preview.putpalette([int(value) for value in palette] + [0, 0, 0] * 248)
            return preview.convert("RGB")
        except Exception:  # pragma: no cover - driver internals changed
            logger.warning("Panel preview unavailable; returning prepared frame")
            return image

    def _show_prepared(
        self,
        prepared: Image.Image,
        saturation: float,
        render_mode: str = "default",
        palette_source: str = "driver",
    ) -> None:
        """Quantise an already prepared frame and push it to the panel."""
        if render_mode == "default":
            saturation = max(0.0, min(1.0, float(saturation)))
            self._display.set_image(prepared, saturation=saturation)
        else:
            # A P image makes the driver copy indices straight to its buffer:
            # no second dithering pass over our own.
            self._display.set_image(
                self._palette_image(prepared, render_mode, palette_source)
            )
        self._display.show()

    def _panel_palette(self, source: str = "driver") -> list[int]:
        """Ink palette for the custom modes, flattened, in driver index order.

        ``source`` is ``driver`` (the panel's measured inks), ``pure`` (the
        theoretical primaries) or a comma separated list of seven hex values.
        """
        if source.startswith("#"):
            parsed = []
            for code in source.replace(" ", "").split(","):
                text = code.lstrip("#")
                if len(text) != 6:
                    continue
                parsed.extend(int(text[index : index + 2], 16) for index in (0, 2, 4))
            if len(parsed) == 21:
                return parsed + [255, 255, 255]
        if source == "pure":
            return [
                0, 0, 0,
                255, 255, 255,
                0, 255, 0,
                0, 0, 255,
                255, 0, 0,
                255, 255, 0,
                255, 140, 0,
                255, 255, 255,
            ]
        blend = getattr(self._display, "_palette_blend", None)
        if callable(blend):
            try:
                palette = [int(value) for value in blend(1.0)]
                if len(palette) >= 24:
                    return palette
            except Exception:  # pragma: no cover - driver internals changed
                logger.warning("Could not read the panel palette")
        # Measured inks of the 7.3" Impression (AC073TC1A SATURATED_PALETTE).
        return [
            0, 0, 0,
            217, 242, 255,
            3, 124, 76,
            27, 46, 198,
            245, 80, 34,
            255, 255, 68,
            239, 121, 44,
            255, 255, 255,
        ]

    def _palette_image(
        self, image: Image.Image, render_mode: str, palette_source: str = "driver"
    ) -> Image.Image:
        """Reduce a prepared frame to the panel palette with the chosen strategy."""
        palette = self._panel_palette(palette_source)
        if render_mode == "oklab":
            try:
                indices = self._oklab_indices(image, palette)
            except Exception:  # pragma: no cover - missing numpy or odd frame
                logger.warning("Oklab quantisation unavailable; using Floyd-Steinberg")
                return self._floyd_steinberg(image, palette)
            return self._index_image(indices, palette)
        return self._floyd_steinberg(image, palette)

    def _floyd_steinberg(
        self, image: Image.Image, palette: list[int]
    ) -> Image.Image:
        """Error-diffusion dithering against the measured palette."""
        palette_image = Image.new("P", (1, 1))
        palette_image.putpalette(self._pad_palette(palette))
        return image.quantize(
            palette=palette_image, dither=Image.Dither.FLOYDSTEINBERG
        )

    @staticmethod
    def _pad_palette(palette: list[int]) -> list[int]:
        return ([int(value) for value in palette] + [0, 0, 0] * 256)[:768]

    def _index_image(self, indices, palette: list[int]) -> Image.Image:
        image = Image.fromarray(indices, mode="P")
        image.putpalette(self._pad_palette(palette))
        return image

    _BAYER8 = (
        (0, 32, 8, 40, 2, 34, 10, 42),
        (48, 16, 56, 24, 50, 18, 58, 26),
        (12, 44, 4, 36, 14, 46, 6, 38),
        (60, 28, 52, 20, 62, 30, 54, 22),
        (3, 35, 11, 43, 1, 33, 9, 41),
        (51, 19, 59, 27, 49, 17, 57, 25),
        (15, 47, 7, 39, 13, 45, 5, 37),
        (63, 31, 55, 23, 61, 29, 53, 21),
    )
    # How far the ordered pattern pushes a pixel in Oklab before matching an ink.
    _OKLAB_AMPLITUDE = 0.09

    def _oklab_indices(self, image: Image.Image, palette: list[int]):
        """Ordered-dither in Oklab against the measured inks (vectorised)."""
        import numpy

        rgb = numpy.asarray(image.convert("RGB"), dtype="float32") / 255.0
        inks = numpy.asarray(
            [palette[index : index + 3] for index in range(0, 21, 3)],
            dtype="float32",
        ) / 255.0
        lab = self._srgb_to_oklab(rgb)
        ink_lab = self._srgb_to_oklab(inks)
        height, width = lab.shape[:2]
        bayer = numpy.asarray(self._BAYER8, dtype="float32") / 64.0 - 0.5
        tile = numpy.tile(
            bayer, (height // 8 + 1, width // 8 + 1)
        )[:height, :width]
        lab = lab + tile[:, :, None] * self._OKLAB_AMPLITUDE
        delta = lab[:, :, None, :] - ink_lab[None, None, :, :]
        return numpy.argmin((delta * delta).sum(-1), axis=-1).astype("uint8")

    @staticmethod
    def _srgb_to_oklab(rgb):
        """sRGB 0..1 to Oklab (Bjorn Ottosson's reference matrices)."""
        import numpy

        linear = numpy.where(
            rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4
        )
        lms = linear @ numpy.array(
            [
                [0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005],
            ],
            dtype="float32",
        ).T
        lms = numpy.cbrt(lms)
        return lms @ numpy.array(
            [
                [0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660],
            ],
            dtype="float32",
        ).T

    def _prepare_image(
        self,
        image: Image.Image,
        scale_to_fit: bool = True,
        target_width: int | None = None,
        target_height: int | None = None,
        brightness: float = 1.0,
        contrast: float = 1.0,
        render_mode: str = "default",
    ) -> Image.Image:
        """Apply orientation fix, tone, colorspace conversion and resize.

        Brightness and contrast run before the resize and before the driver
        quantises the frame: on a seven ink panel they decide which ink each
        pixel picks, which is the lever that actually makes photos readable.
        """
        img = ImageOps.exif_transpose(image)
        if img.mode != "RGB":
            img = img.convert("RGB")
        brightness = max(0.25, min(2.0, float(brightness)))
        contrast = max(0.25, min(2.0, float(contrast)))
        if brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        width = int(target_width) if target_width is not None else self.width
        height = int(target_height) if target_height is not None else self.height
        width = max(64, width)
        height = max(64, height)
        resized = self._resize_image(img, (width, height), scale_to_fit=scale_to_fit)
        if (width, height) != (self.width, self.height):
            # Keep compatibility with hardware by adapting configured render
            # size to real panel size.
            resized = self._resize_image(
                resized, (self.width, self.height), scale_to_fit=scale_to_fit
            )
        if render_mode == "oklab":
            # Sharpening belongs before quantisation: it changes which ink each
            # edge picks, and the panel cannot sharpen anything afterwards.
            resized = resized.filter(
                ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3)
            )
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

        Padding is white to match the panel background, so an uncropped photo
        looks like it sits on the paper rather than inside a frame.
        """
        desired_width, desired_height = int(desired_size[0]), int(desired_size[1])
        dimensions = (desired_width, desired_height)
        if scale_to_fit:
            return ImageOps.fit(image, dimensions, method=Image.LANCZOS)
        return ImageOps.pad(image, dimensions, color="white", method=Image.LANCZOS)

