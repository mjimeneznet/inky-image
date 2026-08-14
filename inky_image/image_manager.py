"""Image directory and navigation management."""

from __future__ import annotations

import hashlib
import os
import random
import threading
import time
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image

from inky_image.config import ConfigManager


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


class _RefreshResult:
    """Result of a handler refresh operation.

    Attributes:
        images: Resolved local file paths available for rendering.
        catalog: Logical source list used for change detection.  For directory
            mode this is the sorted file list (for shuffle stability); for URL
            mode this is the raw URL list; for image_list and upload modes it
            is identical to images.
        error: Human-readable error message, or None when the refresh
            completed with no errors.
    """
    __slots__ = ("images", "catalog", "error")

    def __init__(
        self,
        images: list[str],
        catalog: list[str],
        error: str | None,
    ) -> None:
        self.images = images
        self.catalog = catalog
        self.error = error


class _BaseSourceHandler(ABC):
    """Abstract base for slideshow source mode handlers.

    Each subclass implements the discovery / resolution logic for one
    slideshow mode (directory, image_list, url, upload).  Handlers share a
    common config reference and a static helper for safe cache-file deletion.
    """

    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    # --- Public interface ------------------------------------------------

    @abstractmethod
    def mode_name(self) -> str:
        """Return the slideshow mode string this handler supports."""

    @abstractmethod
    def refresh(self) -> _RefreshResult:
        """Resolve configured sources to valid local file paths.

        Returns:
            _RefreshResult containing resolved file paths for rendering,
            the logical catalog for change detection, and an optional error
            message when sources are missing, invalid or cannot be resolved.
        """

    @abstractmethod
    def list_sources(self) -> list[str]:
        """Return the raw configured source list (paths, URLs, …)."""

    # --- Shared helpers --------------------------------------------------

    @staticmethod
    def _delete_file_if_under(base_dir: Path, file_path: str) -> bool:
        """Safely delete *file_path* when it resides under *base_dir*."""
        path_obj = Path(file_path).expanduser()
        try:
            resolved = path_obj.resolve()
        except OSError:
            return False
        try:
            resolved.relative_to(base_dir.resolve())
        except ValueError:
            return False
        try:
            resolved.unlink()
            return True
        except OSError:
            return False


class _DirectorySource(_BaseSourceHandler):
    """Handler for *directory* slideshow mode.

    Discovers image files recursively inside the active configured directory
    and returns them sorted for stable random-shuffle comparison.
    """

    def mode_name(self) -> str:
        return "directory"

    def list_sources(self) -> list[str]:
        return list(self.config.get("directories", []))

    def get_active_directory(self) -> str | None:
        directories = self.list_sources()
        if not directories:
            return None
        index = int(self.config.get("active_directory_index", -1))
        if index < 0 or index >= len(directories):
            return None
        return directories[index]

    def refresh(self) -> _RefreshResult:
        active_dir = self.get_active_directory()
        if not active_dir:
            return _RefreshResult([], [], None)

        directory = Path(active_dir)
        if not directory.exists() or not directory.is_dir():
            return _RefreshResult(
                [], [], f"Active directory is not valid: {active_dir}"
            )

        try:
            files, warn = self._discover_images_recursive(directory)
        except OSError as exc:
            return _RefreshResult(
                [], [], f"Cannot read directory '{active_dir}': {exc}"
            )

        files = sorted(files, key=lambda value: value.lower())

        if not files:
            return _RefreshResult(
                [],
                [],
                (
                    "No supported image files found in active directory or"
                    f" subdirectories (extensions:"
                    f" {', '.join(sorted(SUPPORTED_EXTENSIONS))})."
                ),
            )

        return _RefreshResult(files, files, warn)

    def _discover_images_recursive(
        self, directory: Path
    ) -> tuple[list[str], str | None]:
        """Recursively scan *directory* for supported image files.

        Returns:
            Tuple of (file_paths, warning_or_None).  Raises OSError when the
            scan produced errors AND produced no results.
        """
        results: list[str] = []
        scan_errors: list[str] = []

        def _on_error(error: OSError) -> None:
            scan_errors.append(str(error))

        for root, dirs, files in os.walk(
            directory, onerror=_on_error, followlinks=False
        ):
            dirs.sort(key=lambda value: value.lower())
            for file_name in sorted(files, key=lambda value: value.lower()):
                suffix = Path(file_name).suffix.lower()
                if suffix in SUPPORTED_EXTENSIONS:
                    results.append(str(Path(root) / file_name))

        if scan_errors and not results:
            raise OSError(scan_errors[0])
        if scan_errors:
            return results, (
                f"Some subdirectories could not be read ({scan_errors[0]})."
            )
        return results, None


class _ImageListSource(_BaseSourceHandler):
    """Handler for *image_list* slideshow mode.

    Resolves configured selected image paths and keeps only valid existing
    files with supported extensions.
    """

    def mode_name(self) -> str:
        return "image_list"

    def list_sources(self) -> list[str]:
        return list(self.config.get("selected_images", []))

    def refresh(self) -> _RefreshResult:
        sources = self.list_sources()
        if not sources:
            return _RefreshResult([], [], None)

        results: list[str] = []
        for image_path in sources:
            path_obj = Path(image_path)
            if not path_obj.exists() or not path_obj.is_file():
                continue
            if path_obj.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            results.append(str(path_obj.resolve()))

        if not results:
            return _RefreshResult([], [], "No valid selected images available.")

        return _RefreshResult(results, results, None)


class _UrlSource(_BaseSourceHandler):
    """Handler for *url* slideshow mode.

    Downloads remote images to a local cache directory, resolves cached paths
    for rendering, and provides helpers for cache-file lifecycle management.
    """

    def __init__(self, config: ConfigManager) -> None:
        super().__init__(config)
        self._cache_dir = Path.home() / ".cache" / "inky-image" / "url-images"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_dl_error: str | None = None

    def mode_name(self) -> str:
        return "url"

    def list_sources(self) -> list[str]:
        return list(self.config.get("url_images", []))

    def refresh(self) -> _RefreshResult:
        sources = self.list_sources()
        if not sources:
            return _RefreshResult([], [], None)

        resolved_paths: list[str] = []
        last_error: str | None = None
        for image_url in sources:
            cached_path = self._cached_path_for_url(image_url)
            if not cached_path:
                cached_path = self._download_url_image(image_url)
                if cached_path is None:
                    last_error = self._last_dl_error
                    self._last_dl_error = None
                    continue
            resolved_paths.append(cached_path)

        if not resolved_paths:
            return _RefreshResult(
                [], [], "No valid URL images could be downloaded."
            )

        # Catalog is the raw URL list — used to detect URL list changes.
        return _RefreshResult(resolved_paths, list(sources), last_error)

    # --- URL cache helpers -----------------------------------------------

    def _cache_stem_for_url(self, image_url: str) -> str:
        """Deterministic cache filename stem for *image_url*."""
        return hashlib.sha256(image_url.encode("utf-8")).hexdigest()

    def _cached_path_for_url(self, image_url: str) -> str | None:
        """Return existing cached file path for *image_url*, or None."""
        stem = self._cache_stem_for_url(image_url)
        candidates = sorted(self._cache_dir.glob(f"{stem}.*"))
        if not candidates:
            return None
        path = candidates[0]
        if not path.exists() or not path.is_file():
            return None
        return str(path.resolve())

    def _delete_cached_url_file(self, image_url: str) -> None:
        """Remove all cached files for *image_url*."""
        stem = self._cache_stem_for_url(image_url)
        for candidate in self._cache_dir.glob(f"{stem}.*"):
            try:
                candidate.unlink()
            except OSError:
                continue

    def _extension_for_url_content(
        self, image_url: str, content_type: str
    ) -> str:
        """Resolve file extension from content-type or URL suffix."""
        content_type = str(content_type or "").lower().split(";")[0].strip()
        content_type_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }
        if content_type in content_type_map:
            return content_type_map[content_type]
        url_suffix = Path(urlparse(image_url).path).suffix.lower()
        if url_suffix in SUPPORTED_EXTENSIONS:
            return url_suffix
        return ".jpg"

    def _download_url_image(self, image_url: str) -> str | None:
        """Download *image_url* to cache and return local path, or None."""
        request = Request(
            image_url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux armv7l) InkyImage/1.0",
                "Accept": "*/*",
            },
        )
        content_type = ""
        try:
            with urlopen(request, timeout=12) as response:
                content_type = str(response.headers.get("Content-Type", ""))
                data = response.read(12 * 1024 * 1024 + 1)
        except Exception as exc:
            self._last_dl_error = (
                f"Cannot download URL image '{image_url}': {exc}"
            )
            return None

        if len(data) > 12 * 1024 * 1024:
            self._last_dl_error = (
                f"URL image too large (>12MB): {image_url}"
            )
            return None

        try:
            with Image.open(BytesIO(data)) as img:
                img.verify()
        except Exception:
            content_type_note = (
                f" (content-type: {content_type})" if content_type else ""
            )
            self._last_dl_error = (
                "Downloaded file is not a valid image:"
                f" {image_url}{content_type_note}"
            )
            return None

        stem = self._cache_stem_for_url(image_url)
        self._delete_cached_url_file(image_url)
        extension = self._extension_for_url_content(image_url, content_type)
        target_path = self._cache_dir / f"{stem}{extension}"
        try:
            target_path.write_bytes(data)
        except OSError as exc:
            self._last_dl_error = (
                f"Cannot write URL image cache: {exc}"
            )
            return None
        return str(target_path.resolve())


class _UploadSource(_BaseSourceHandler):
    """Handler for *upload* slideshow mode.

    Persists uploaded image bytes to a local cache directory, resolves cached
    paths for rendering, and provides helpers for upload-file lifecycle
    management.
    """

    def __init__(self, config: ConfigManager) -> None:
        super().__init__(config)
        self._cache_dir = Path.home() / ".cache" / "inky-image" / "upload-images"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def mode_name(self) -> str:
        return "upload"

    def list_sources(self) -> list[str]:
        return list(self.config.get("uploaded_images", []))

    def refresh(self) -> _RefreshResult:
        sources = self.list_sources()
        if not sources:
            return _RefreshResult([], [], None)

        results: list[str] = []
        for image_path in sources:
            path_obj = Path(image_path)
            if not path_obj.exists() or not path_obj.is_file():
                continue
            if path_obj.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            results.append(str(path_obj.resolve()))

        if not results:
            return _RefreshResult([], [], "No uploaded images available.")

        return _RefreshResult(results, results, None)

    # --- Upload helpers --------------------------------------------------

    def _extension_for_upload_content(
        self, file_name: str, image_format: str | None
    ) -> str:
        """Resolve file extension for an uploaded image."""
        suffix = Path(str(file_name or "")).suffix.lower()
        if suffix in SUPPORTED_EXTENSIONS:
            return suffix
        format_map = {
            "JPEG": ".jpg",
            "PNG": ".png",
            "GIF": ".gif",
            "WEBP": ".webp",
            "BMP": ".bmp",
        }
        return format_map.get(str(image_format or "").upper(), ".jpg")

    def _delete_uploaded_file(self, image_path: str) -> None:
        """Remove *image_path* from cache if it resides under our cache dir."""
        self._delete_file_if_under(self._cache_dir, image_path)


class ImageManager:
    """Handles active directory images and navigation state.

    Lock ordering:
    ImageManager._lock must be acquired before ConfigManager._lock.
    All internal methods that access config do so while holding self._lock,
    which is safe because ConfigManager's lock is acquired inside the config
    call.
    """

    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._images: list[str] = []
        self._catalog: list[str] = []
        self._last_scan_error: str | None = None
        self._dirty = True

        # Source handlers
        self._dir_source = _DirectorySource(config)
        self._image_list_source = _ImageListSource(config)
        self._url_source = _UrlSource(config)
        self._upload_source = _UploadSource(config)

        self.refresh_images()

    # --- Handler dispatch ------------------------------------------------

    def _handler_for_mode(self, mode: str) -> _BaseSourceHandler | None:
        mapping: dict[str, _BaseSourceHandler] = {
            "directory": self._dir_source,
            "image_list": self._image_list_source,
            "url": self._url_source,
            "upload": self._upload_source,
        }
        return mapping.get(mode)

    # --- Refresh ---------------------------------------------------------

    def refresh_images(self) -> list[str]:
        """Rebuild active image file list."""
        with self._lock:
            if not self._dirty:
                return list(self._images)
            self._dirty = False
            self._last_scan_error = None
            previous_current = self._current_image_path_no_refresh()
            mode = self.get_mode()

            handler = self._handler_for_mode(mode)
            if handler is None:
                self._images = []
                self._catalog = []
                self.config.set("current_image_index", 0)
                return []

            result = handler.refresh()
            self._last_scan_error = result.error
            previous_catalog = list(self._catalog)

            if mode == "directory":
                # Directory mode: compare sorted catalog to preserve shuffle
                # stability across status refreshes.
                sorted_files = result.catalog
                if sorted_files != self._catalog:
                    self._catalog = list(sorted_files)
                    self._images = list(sorted_files)
                    random.shuffle(self._images)
                else:
                    # Keep existing _images (already shuffled).
                    self._catalog = list(sorted_files)
            elif mode == "url":
                # URL mode: catalog is the raw URL list (for change detection).
                self._catalog = list(result.catalog)
                self._images = list(result.images)
            else:
                # image_list / upload: catalog == images (resolved paths).
                self._catalog = list(result.images)
                self._images = list(result.images)

            if not self._images:
                self.config.set("current_image_index", 0)
                return []

            current_index = self._normalized_current_image_index(
                len(self._images), allow_inactive=True
            )
            if previous_current and previous_current in self._images:
                current_index = self._images.index(previous_current)
            elif (
                mode == "url"
                and current_index != -1
                and list(result.catalog) != previous_catalog
            ):
                current_index = 0
            self.config.set("current_image_index", current_index)
            return list(self._images)

    def _normalized_current_image_index(
        self, image_count: int, allow_inactive: bool = False
    ) -> int:
        """Normalize the configured image index against an image list."""
        current_index = int(self.config.get("current_image_index", 0))
        if image_count == 0:
            return 0
        if allow_inactive and current_index == -1:
            return -1
        return current_index % image_count

    # --- Source list accessors -------------------------------------------

    def get_directories(self) -> list[str]:
        """Return configured directory list."""
        return self._dir_source.list_sources()

    def get_selected_images(self) -> list[str]:
        """Return selected image list."""
        return self._image_list_source.list_sources()

    def get_url_images(self) -> list[str]:
        """Return configured URL image list."""
        return self._url_source.list_sources()

    def get_uploaded_images(self) -> list[str]:
        """Return configured uploaded image list."""
        return self._upload_source.list_sources()

    # --- Mode ------------------------------------------------------------

    def get_mode(self) -> str:
        """Return active slideshow source mode."""
        mode = str(self.config.get("slideshow_mode", "directory")).strip().lower()
        if mode not in {"directory", "image_list", "url", "upload"}:
            return "directory"
        return mode

    def set_mode(self, mode: str) -> bool:
        """Switch slideshow source mode and reset image index."""
        with self._lock:
            ok = self.config.set_slideshow_mode(mode)
            self._dirty = True
            self.refresh_images()
            return ok

    # --- Directory operations --------------------------------------------

    def get_active_directory(self) -> str | None:
        """Return active directory path."""
        return self._dir_source.get_active_directory()

    def set_active_directory(self, index: int) -> bool:
        """Set active directory and refresh image list."""
        with self._lock:
            ok = self.config.set_active_directory(index)
            self._dirty = True
            self.refresh_images()
            return ok

    def cycle_directory(self) -> bool:
        """Move to next configured directory and refresh list."""
        with self._lock:
            if self.get_mode() != "directory":
                return False
            ok = self.config.cycle_active_directory()
            self._dirty = True
            self.refresh_images()
            return ok

    def add_directory(self, directory_path: str) -> bool:
        """Add directory without auto-activating it."""
        with self._lock:
            ok = self.config.add_directory(directory_path)
            self._dirty = True
            self.refresh_images()
            return ok

    def remove_directory(self, index: int) -> bool:
        """Remove directory and refresh image list."""
        with self._lock:
            ok = self.config.remove_directory(index)
            self._dirty = True
            self.refresh_images()
            return ok

    def deactivate_directory(self, index: int) -> bool:
        """Deactivate directory if currently active."""
        with self._lock:
            active_index = int(self.config.get("active_directory_index", -1))
            if active_index != index:
                return False
            self.config.deactivate_active_directory()
            self._dirty = True
            self.refresh_images()
            return True

    # --- Selected image operations ---------------------------------------

    def add_selected_image(self, image_path: str) -> bool:
        """Add image path to selected list without duplicates."""
        with self._lock:
            normalized = Path(image_path).expanduser().resolve()
            if normalized.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return False
            ok = self.config.add_selected_image(str(normalized))
            self._dirty = True
            self.refresh_images()
            return ok

    def remove_selected_image(self, index: int) -> bool:
        """Remove selected image by index."""
        with self._lock:
            ok = self.config.remove_selected_image(index)
            self._dirty = True
            self.refresh_images()
            return ok

    def clear_selected_images(self) -> bool:
        """Clear selected image list."""
        with self._lock:
            self.config.clear_selected_images()
            self._dirty = True
            self.refresh_images()
            return True

    def activate_selected_image(self, index: int) -> bool:
        """Activate selected image by setting image_list mode and active index."""
        with self._lock:
            images = self.get_selected_images()
            if index < 0 or index >= len(images):
                return False
            if not self.config.set_slideshow_mode("image_list"):
                return False
            self.config.set("current_image_index", index)
            self._dirty = True
            self.refresh_images()
            return True

    def deactivate_selected_image(self, index: int) -> bool:
        """Deactivate selected image if currently active in image_list mode."""
        with self._lock:
            if self.get_mode() != "image_list":
                return False
            current_index = int(self.config.get("current_image_index", 0))
            if current_index != index:
                return False
            self.config.set("current_image_index", -1)
            self._dirty = True
            self.refresh_images()
            return True

    # --- URL image operations --------------------------------------------

    def add_url_image(self, image_url: str) -> bool:
        """Add URL image source without duplicates."""
        with self._lock:
            self._last_scan_error = None
            normalized = str(image_url).strip()
            parsed = urlparse(normalized)
            if parsed.scheme not in {"http", "https"}:
                self._last_scan_error = "Only http/https URLs are supported."
                return False
            if not parsed.netloc:
                self._last_scan_error = "URL host is missing."
                return False

            cached_path = self._url_source._cached_path_for_url(normalized)
            if not cached_path:
                cached_path = self._url_source._download_url_image(normalized)
            if not cached_path:
                self._last_scan_error = self._url_source._last_dl_error
                return False

            ok = self.config.add_url_image(normalized)
            if not ok:
                self._last_scan_error = "URL already added."
            self._dirty = True
            self.refresh_images()
            return ok

    def remove_url_image(self, index: int) -> bool:
        """Remove URL image source by index."""
        with self._lock:
            urls = self.get_url_images()
            if index < 0 or index >= len(urls):
                return False
            image_url = urls[index]
            ok = self.config.remove_url_image(index)
            if ok:
                self._url_source._delete_cached_url_file(image_url)
            self._dirty = True
            self.refresh_images()
            return ok

    def clear_url_images(self) -> bool:
        """Clear URL image sources."""
        with self._lock:
            for image_url in self.get_url_images():
                self._url_source._delete_cached_url_file(image_url)
            self.config.clear_url_images()
            self._dirty = True
            self.refresh_images()
            return True

    def activate_url_image(self, index: int) -> bool:
        """Activate URL image by setting url mode and active index."""
        with self._lock:
            urls = self.get_url_images()
            if index < 0 or index >= len(urls):
                return False
            if not self.config.set_slideshow_mode("url"):
                return False
            self.config.set("current_image_index", index)
            self._dirty = True
            self.refresh_images()
            return True

    def deactivate_url_image(self, index: int) -> bool:
        """Deactivate URL image if currently active."""
        with self._lock:
            if self.get_mode() != "url":
                return False
            current_index = int(self.config.get("current_image_index", 0))
            if current_index != index:
                return False
            self.config.set("current_image_index", -1)
            self._dirty = True
            self.refresh_images()
            return True

    # --- Uploaded image operations ---------------------------------------

    def add_uploaded_image_data(self, file_name: str, content: bytes) -> bool:
        """Persist uploaded image bytes and add to upload image list."""
        with self._lock:
            if not content:
                return False
            if len(content) > 12 * 1024 * 1024:
                self._last_scan_error = "Uploaded image is too large (>12MB)."
                return False

            image_format: str | None = None
            try:
                with Image.open(BytesIO(content)) as image:
                    image_format = image.format
                    image.verify()
            except Exception:
                self._last_scan_error = "Uploaded file is not a valid image."
                return False

            extension = self._upload_source._extension_for_upload_content(
                file_name, image_format
            )
            target_name = (
                f"{int(time.time())}-"
                f"{hashlib.sha256(content).hexdigest()[:12]}{extension}"
            )
            target_path = self._upload_source._cache_dir / target_name
            try:
                target_path.write_bytes(content)
            except OSError as exc:
                self._last_scan_error = (
                    f"Cannot save uploaded image: {exc}"
                )
                return False

            ok = self.config.add_uploaded_image(str(target_path.resolve()))
            self._dirty = True
            self.refresh_images()
            return ok

    def remove_uploaded_image(self, index: int) -> bool:
        """Remove uploaded image source by index."""
        with self._lock:
            images = self.get_uploaded_images()
            if index < 0 or index >= len(images):
                return False
            image_path = images[index]
            ok = self.config.remove_uploaded_image(index)
            if ok:
                self._upload_source._delete_uploaded_file(image_path)
            self._dirty = True
            self.refresh_images()
            return ok

    def clear_uploaded_images(self) -> bool:
        """Clear uploaded image sources."""
        with self._lock:
            for image_path in self.get_uploaded_images():
                self._upload_source._delete_uploaded_file(image_path)
            self.config.clear_uploaded_images()
            self._dirty = True
            self.refresh_images()
            return True

    def activate_uploaded_image(self, index: int) -> bool:
        """Activate uploaded image by setting upload mode and active index."""
        with self._lock:
            images = self.get_uploaded_images()
            if index < 0 or index >= len(images):
                return False
            if not self.config.set_slideshow_mode("upload"):
                return False
            self.config.set("current_image_index", index)
            self._dirty = True
            self.refresh_images()
            return True

    def deactivate_uploaded_image(self, index: int) -> bool:
        """Deactivate uploaded image if currently active."""
        with self._lock:
            if self.get_mode() != "upload":
                return False
            current_index = int(self.config.get("current_image_index", 0))
            if current_index != index:
                return False
            self.config.set("current_image_index", -1)
            self._dirty = True
            self.refresh_images()
            return True

    # --- Error accessor --------------------------------------------------

    def get_last_scan_error(self) -> str | None:
        """Return latest scan/download error message for API responses."""
        return self._last_scan_error

    # --- Navigation ------------------------------------------------------

    def current_image_path(self) -> str | None:
        """Return current image file path."""
        with self._lock:
            if not self._images:
                self.refresh_images()
            return self._current_image_path_no_refresh()

    def next_image_path(self) -> str | None:
        """Move to next image and return path."""
        with self._lock:
            if not self._images:
                self.refresh_images()
            if not self._images:
                return None
            current_index = int(self.config.get("current_image_index", 0))
            if current_index < 0:
                index = 0
            else:
                index = (current_index + 1) % len(self._images)
            self.config.set("current_image_index", index)
            return self._images[index]

    def previous_image_path(self) -> str | None:
        """Move to previous image and return path."""
        with self._lock:
            if not self._images:
                self.refresh_images()
            if not self._images:
                return None
            current_index = int(self.config.get("current_image_index", 0))
            if current_index < 0:
                index = len(self._images) - 1
            else:
                index = (current_index - 1) % len(self._images)
            self.config.set("current_image_index", index)
            return self._images[index]

    # --- Shuffle ---------------------------------------------------------

    def reshuffle(self) -> bool:
        """Reshuffle current image order while keeping current image if possible."""
        with self._lock:
            self._dirty = True
            if not self._images:
                self.refresh_images()
            if not self._images:
                return False

            current_path = self._current_image_path_no_refresh()
            random.shuffle(self._images)
            new_index = 0
            if current_path and current_path in self._images:
                new_index = self._images.index(current_path)
            self.config.set("current_image_index", new_index)
            return True

    # --- Status ----------------------------------------------------------

    def get_status(self) -> dict:
        """Return state used by API/UI."""
        with self._lock:
            self.refresh_images()
            directories = self.get_directories()
            selected_images = self.get_selected_images()
            active_index = int(self.config.get("active_directory_index", -1))
            current_index = int(self.config.get("current_image_index", 0))
            current_path = self._current_image_path_no_refresh()
            return {
                "mode": self.get_mode(),
                "directories": directories,
                "active_directory_index": active_index,
                "active_directory": self.get_active_directory(),
                "selected_images": selected_images,
                "selected_images_count": len(selected_images),
                "url_images": self.get_url_images(),
                "url_images_count": len(self.get_url_images()),
                "uploaded_images": self.get_uploaded_images(),
                "uploaded_images_count": len(self.get_uploaded_images()),
                "image_count": len(self._images),
                "current_image_index": current_index if self._images else 0,
                "url_active_index": current_index
                if self.get_mode() == "url"
                else -1,
                "upload_active_index": current_index
                if self.get_mode() == "upload"
                else -1,
                "current_image_path": current_path,
                "current_image_name": Path(current_path).name if current_path else None,
                "scan_error": self._last_scan_error,
                "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
            }

    def _current_image_path_no_refresh(self) -> str | None:
        """Return current image path without triggering refresh."""
        if not self._images:
            return None
        index_raw = int(self.config.get("current_image_index", 0))
        if index_raw < 0:
            return None
        index = index_raw % len(self._images)
        return self._images[index]