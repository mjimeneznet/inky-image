"""Image directory and navigation management."""

from __future__ import annotations

import hashlib
import os
import random
import threading
import time
from io import BytesIO
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from pathlib import Path

from PIL import Image

from inky_image.config import ConfigManager


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


class ImageManager:
    """Handles active directory images and navigation state."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._images: list[str] = []
        self._catalog: list[str] = []
        self._last_scan_error: str | None = None
        self._url_cache_dir = Path.home() / ".cache" / "inky-image" / "url-images"
        self._url_cache_dir.mkdir(parents=True, exist_ok=True)
        self._upload_cache_dir = Path.home() / ".cache" / "inky-image" / "upload-images"
        self._upload_cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_images()

    def refresh_images(self) -> list[str]:
        """Rebuild active directory file list."""
        with self._lock:
            self._last_scan_error = None
            previous_current = self._current_image_path_no_refresh()
            mode = self.get_mode()
            if mode == "image_list":
                images = self._discover_selected_images()
                self._catalog = list(images)
                self._images = list(images)
                if not self._images:
                    self.config.set("current_image_index", 0)
                    self._last_scan_error = "No valid selected images available."
                    return []
                current_index = self._normalized_current_image_index(
                    len(self._images), allow_inactive=True
                )
                if previous_current and previous_current in self._images:
                    current_index = self._images.index(previous_current)
                self.config.set("current_image_index", current_index)
                return list(self._images)

            if mode == "url":
                url_images = self.get_url_images()
                previous_catalog = list(self._catalog)
                resolved_paths: list[str] = []
                for image_url in url_images:
                    cached_path = self._cached_path_for_url(image_url)
                    if not cached_path:
                        cached_path = self._download_url_image(image_url)
                    if cached_path:
                        resolved_paths.append(cached_path)
                self._catalog = list(url_images)
                self._images = list(resolved_paths)
                if not url_images:
                    self.config.set("current_image_index", 0)
                    self._last_scan_error = "No URL images configured."
                    return []
                if not self._images:
                    self.config.set("current_image_index", 0)
                    self._last_scan_error = "No valid URL images could be downloaded."
                    return []
                current_index = self._normalized_current_image_index(
                    len(self._images), allow_inactive=True
                )
                if previous_current and previous_current in self._images:
                    current_index = self._images.index(previous_current)
                elif current_index != -1 and previous_catalog != self._catalog:
                    current_index = 0
                self.config.set("current_image_index", current_index)
                return list(self._images)

            if mode == "upload":
                images = self._discover_uploaded_images()
                self._catalog = list(images)
                self._images = list(images)
                if not self._images:
                    self.config.set("current_image_index", 0)
                    self._last_scan_error = "No uploaded images available."
                    return []
                current_index = self._normalized_current_image_index(
                    len(self._images), allow_inactive=True
                )
                if previous_current and previous_current in self._images:
                    current_index = self._images.index(previous_current)
                self.config.set("current_image_index", current_index)
                return list(self._images)

            active_dir = self.get_active_directory()
            if not active_dir:
                self._images = []
                self._catalog = []
                self.config.set("current_image_index", 0)
                return []

            directory = Path(active_dir)
            if not directory.exists() or not directory.is_dir():
                self._images = []
                self._catalog = []
                self.config.set("current_image_index", 0)
                self._last_scan_error = f"Active directory is not valid: {active_dir}"
                return []

            try:
                files = self._discover_images_recursive(directory)
            except OSError as exc:
                self._images = []
                self._catalog = []
                self.config.set("current_image_index", 0)
                self._last_scan_error = f"Cannot read directory '{active_dir}': {exc}"
                return []
            files = sorted(files, key=lambda value: value.lower())

            # Keep random slideshow order stable across status refreshes.
            if files != self._catalog:
                self._catalog = files
                self._images = list(files)
                random.shuffle(self._images)

            if not self._images:
                self.config.set("current_image_index", 0)
                self._last_scan_error = (
                    "No supported image files found in active directory or subdirectories "
                    f"(extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))})."
                )
                return []

            current_index = int(self.config.get("current_image_index", 0)) % len(
                self._images
            )
            if previous_current and previous_current in self._images:
                current_index = self._images.index(previous_current)
            self.config.set("current_image_index", current_index)
            return list(self._images)

    def _normalized_current_image_index(
        self, image_count: int, allow_inactive: bool = False
    ) -> int:
        """Normalize the configured image index against a non-empty image list."""
        current_index = int(self.config.get("current_image_index", 0))
        if allow_inactive and current_index == -1:
            return -1
        return current_index % image_count

    def _discover_selected_images(self) -> list[str]:
        """Resolve configured selected image list and keep only valid files."""
        results: list[str] = []
        for image_path in self.get_selected_images():
            path_obj = Path(image_path)
            if not path_obj.exists() or not path_obj.is_file():
                continue
            if path_obj.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            results.append(str(path_obj.resolve()))
        return results

    def _discover_uploaded_images(self) -> list[str]:
        """Resolve uploaded image list and keep only valid files."""
        results: list[str] = []
        for image_path in self.get_uploaded_images():
            path_obj = Path(image_path)
            if not path_obj.exists() or not path_obj.is_file():
                continue
            if path_obj.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            results.append(str(path_obj.resolve()))
        return results

    def _discover_images_recursive(self, directory: Path) -> list[str]:
        """Recursively scan directory tree for supported image files."""
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
            self._last_scan_error = (
                f"Some subdirectories could not be read ({scan_errors[0]})."
            )

        return results

    def get_directories(self) -> list[str]:
        """Return configured directory list."""
        return list(self.config.get("directories", []))

    def get_selected_images(self) -> list[str]:
        """Return selected image list."""
        return list(self.config.get("selected_images", []))

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
            self.refresh_images()
            return ok

    def get_active_directory(self) -> str | None:
        """Return active directory path."""
        directories = self.get_directories()
        if not directories:
            return None
        index = int(self.config.get("active_directory_index", -1))
        if index < 0 or index >= len(directories):
            return None
        return directories[index]

    def set_active_directory(self, index: int) -> bool:
        """Set active directory and refresh image list."""
        with self._lock:
            ok = self.config.set_active_directory(index)
            self.refresh_images()
            return ok

    def cycle_directory(self) -> bool:
        """Move to next configured directory and refresh list."""
        with self._lock:
            if self.get_mode() != "directory":
                return False
            ok = self.config.cycle_active_directory()
            self.refresh_images()
            return ok

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

    def add_directory(self, directory_path: str) -> bool:
        """Add directory without auto-activating it."""
        with self._lock:
            ok = self.config.add_directory(directory_path)
            self.refresh_images()
            return ok

    def add_selected_image(self, image_path: str) -> bool:
        """Add image path to selected list without duplicates."""
        with self._lock:
            normalized = Path(image_path).expanduser().resolve()
            if normalized.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return False
            ok = self.config.add_selected_image(str(normalized))
            self.refresh_images()
            return ok

    def activate_selected_image(self, index: int) -> bool:
        """Activate selected image by setting image_list mode and active index."""
        with self._lock:
            images = self.get_selected_images()
            if index < 0 or index >= len(images):
                return False
            if not self.config.set_slideshow_mode("image_list"):
                return False
            self.config.set("current_image_index", index)
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
            self.refresh_images()
            return True

    def get_url_images(self) -> list[str]:
        """Return configured URL image list."""
        return list(self.config.get("url_images", []))

    def get_uploaded_images(self) -> list[str]:
        """Return configured uploaded image list."""
        return list(self.config.get("uploaded_images", []))

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
            cached_path = self._cached_path_for_url(normalized)
            if not cached_path:
                cached_path = self._download_url_image(normalized)
            if not cached_path:
                return False
            ok = self.config.add_url_image(normalized)
            if not ok:
                self._last_scan_error = "URL already added."
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
                self._delete_cached_url_file(image_url)
            self.refresh_images()
            return ok

    def activate_url_image(self, index: int) -> bool:
        """Activate URL image by setting url mode and active index."""
        with self._lock:
            urls = self.get_url_images()
            if index < 0 or index >= len(urls):
                return False
            if not self.config.set_slideshow_mode("url"):
                return False
            self.config.set("current_image_index", index)
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
            self.refresh_images()
            return True

    def clear_url_images(self) -> bool:
        """Clear URL image sources."""
        with self._lock:
            for image_url in self.get_url_images():
                self._delete_cached_url_file(image_url)
            self.config.clear_url_images()
            self.refresh_images()
            return True

    def _extension_for_upload_content(
        self, file_name: str, image_format: str | None
    ) -> str:
        """Resolve extension for uploaded image."""
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

            extension = self._extension_for_upload_content(file_name, image_format)
            target_name = f"{int(time.time())}-{hashlib.sha256(content).hexdigest()[:12]}{extension}"
            target_path = self._upload_cache_dir / target_name
            try:
                target_path.write_bytes(content)
            except OSError as exc:
                self._last_scan_error = f"Cannot save uploaded image: {exc}"
                return False

            ok = self.config.add_uploaded_image(str(target_path.resolve()))
            self.refresh_images()
            return ok

    def _delete_uploaded_file(self, image_path: str) -> None:
        """Delete uploaded cache file for an uploaded image if present."""
        path_obj = Path(image_path).expanduser()
        try:
            resolved = path_obj.resolve()
        except OSError:
            return
        try:
            resolved.relative_to(self._upload_cache_dir.resolve())
        except ValueError:
            return
        try:
            resolved.unlink()
        except OSError:
            return

    def remove_uploaded_image(self, index: int) -> bool:
        """Remove uploaded image source by index."""
        with self._lock:
            images = self.get_uploaded_images()
            if index < 0 or index >= len(images):
                return False
            image_path = images[index]
            ok = self.config.remove_uploaded_image(index)
            if ok:
                self._delete_uploaded_file(image_path)
            self.refresh_images()
            return ok

    def clear_uploaded_images(self) -> bool:
        """Clear uploaded image sources."""
        with self._lock:
            for image_path in self.get_uploaded_images():
                self._delete_uploaded_file(image_path)
            self.config.clear_uploaded_images()
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
            self.refresh_images()
            return True

    def _cache_stem_for_url(self, image_url: str) -> str:
        """Build deterministic cache filename stem for URL."""
        return hashlib.sha256(image_url.encode("utf-8")).hexdigest()

    def _cached_path_for_url(self, image_url: str) -> str | None:
        """Return cached local file path for URL when available."""
        stem = self._cache_stem_for_url(image_url)
        candidates = sorted(self._url_cache_dir.glob(f"{stem}.*"))
        if not candidates:
            return None
        path = candidates[0]
        if not path.exists() or not path.is_file():
            return None
        return str(path.resolve())

    def _delete_cached_url_file(self, image_url: str) -> None:
        """Delete cached local file for URL if present."""
        stem = self._cache_stem_for_url(image_url)
        for candidate in self._url_cache_dir.glob(f"{stem}.*"):
            try:
                candidate.unlink()
            except OSError:
                continue

    def _extension_for_url_content(self, image_url: str, content_type: str) -> str:
        """Resolve file extension for downloaded URL image."""
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
        """Download URL image to cache and return local path."""
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
            self._last_scan_error = f"Cannot download URL image '{image_url}': {exc}"
            return None

        if len(data) > 12 * 1024 * 1024:
            self._last_scan_error = f"URL image too large (>12MB): {image_url}"
            return None

        try:
            with Image.open(BytesIO(data)) as img:
                img.verify()
        except Exception:
            content_type_note = (
                f" (content-type: {content_type})" if content_type else ""
            )
            self._last_scan_error = (
                f"Downloaded file is not a valid image: {image_url}{content_type_note}"
            )
            return None

        stem = self._cache_stem_for_url(image_url)
        self._delete_cached_url_file(image_url)
        extension = self._extension_for_url_content(image_url, content_type)
        target_path = self._url_cache_dir / f"{stem}{extension}"
        try:
            target_path.write_bytes(data)
        except OSError as exc:
            self._last_scan_error = f"Cannot write URL image cache: {exc}"
            return None
        return str(target_path.resolve())

    def get_last_scan_error(self) -> str | None:
        """Return latest scan/download error message for API responses."""
        return self._last_scan_error

    def remove_selected_image(self, index: int) -> bool:
        """Remove selected image by index."""
        with self._lock:
            ok = self.config.remove_selected_image(index)
            self.refresh_images()
            return ok

    def clear_selected_images(self) -> bool:
        """Clear selected image list."""
        with self._lock:
            self.config.clear_selected_images()
            self.refresh_images()
            return True

    def remove_directory(self, index: int) -> bool:
        """Remove directory and refresh image list."""
        with self._lock:
            ok = self.config.remove_directory(index)
            self.refresh_images()
            return ok

    def deactivate_directory(self, index: int) -> bool:
        """Deactivate directory if currently active."""
        with self._lock:
            active_index = int(self.config.get("active_directory_index", -1))
            if active_index != index:
                return False
            self.config.deactivate_active_directory()
            self.refresh_images()
            return True

    def reshuffle(self) -> bool:
        """Reshuffle current image order while keeping current image if possible."""
        with self._lock:
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
                "url_active_index": current_index if self.get_mode() == "url" else -1,
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
