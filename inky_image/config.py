"""Configuration management for Inky Image Viewer."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


MODE_LIST_MAP: dict[str, str] = {
    "image_list": "selected_images",
    "url": "url_images",
    "upload": "uploaded_images",
}


DEFAULT_CONFIG = {
    "directories": [],
    "active_directory_index": -1,
    "selected_images": [],
    "url_images": [],
    "uploaded_images": [],
    "slideshow_mode": "directory",
    "slideshow_interval": 30,
    "slideshow_running": False,
    "saturation": 0.5,
    "scale_to_fit": True,
    "lock_buttons": False,
    "render_width": 800,
    "render_height": 480,
    "current_image_index": 0,
    "last_rendered_image_path": "",
    "web_port": 80,
}


def _safe_int(value: Any, default: int) -> int:
    """Return an int value, or a default when persisted config is invalid."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    """Return a float value, or a default when persisted config is invalid."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ConfigManager:
    """Thread-safe JSON config manager.

    Note on lock ordering:
    ConfigManager._lock must never be acquired while holding
    ImageManager._lock.  The correct order is
    ImageManager._lock -> ConfigManager._lock.
    Any external code holding a ConfigManager lock must not call into
    ImageManager.
    """

    def __init__(self, config_path: str | None = None) -> None:
        default_path = os.environ.get(
            "INKY_IMAGE_CONFIG_PATH",
            os.path.expanduser("~/.config/inky-image/config.json"),
        )
        self.config_path = Path(config_path or default_path)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load config from disk and apply defaults."""
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if self.config_path.exists():
                try:
                    loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self._data = loaded
                    else:
                        self._data = {}
                except (json.JSONDecodeError, OSError):
                    self._data = {}
            else:
                self._data = {}

            for key, value in DEFAULT_CONFIG.items():
                self._data.setdefault(key, value)

            # Normalize data types that can break navigation state.
            self._data["directories"] = [
                path
                for path in self._data.get("directories", [])
                if isinstance(path, str)
            ]
            self._data["selected_images"] = [
                path
                for path in self._data.get("selected_images", [])
                if isinstance(path, str)
            ]
            self._data["url_images"] = [
                url for url in self._data.get("url_images", []) if isinstance(url, str)
            ]
            self._data["uploaded_images"] = [
                path
                for path in self._data.get("uploaded_images", [])
                if isinstance(path, str)
            ]
            self._data["active_directory_index"] = _safe_int(
                self._data.get("active_directory_index", -1), -1
            )
            mode = str(self._data.get("slideshow_mode", "directory")).strip().lower()
            self._data["slideshow_mode"] = (
                mode
                if mode in {"directory", "image_list", "url", "upload"}
                else "directory"
            )
            self._data["current_image_index"] = _safe_int(
                self._data.get("current_image_index", 0), 0
            )
            last_rendered = self._data.get("last_rendered_image_path", "")
            self._data["last_rendered_image_path"] = (
                str(last_rendered) if last_rendered is not None else ""
            )
            self._data["slideshow_interval"] = max(
                30, _safe_int(self._data.get("slideshow_interval", 30), 30)
            )
            self._data["saturation"] = _safe_float(
                self._data.get("saturation", 0.5), 0.5
            )
            self._data["saturation"] = max(0.0, min(1.0, self._data["saturation"]))
            scale_raw = self._data.get("scale_to_fit", True)
            if isinstance(scale_raw, str):
                self._data["scale_to_fit"] = scale_raw.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
            else:
                self._data["scale_to_fit"] = bool(scale_raw)
            lock_buttons_raw = self._data.get("lock_buttons", False)
            if isinstance(lock_buttons_raw, str):
                self._data["lock_buttons"] = lock_buttons_raw.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
            else:
                self._data["lock_buttons"] = bool(lock_buttons_raw)
            self._data["render_width"] = max(
                64, _safe_int(self._data.get("render_width", 800), 800)
            )
            self._data["render_height"] = max(
                64, _safe_int(self._data.get("render_height", 480), 480)
            )
            web_port_raw = self._data.get("web_port", 80)
            self._data["web_port"] = _safe_int(web_port_raw, 80)
            if self._data["web_port"] == 8080:
                self._data["web_port"] = 80
            self._sync_indexes()
            self.save()

    def save(self) -> None:
        """Persist config to disk."""
        with self._lock:
            self.config_path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

    def get(self, key: str, default: Any = None) -> Any:
        """Read a single config value."""
        with self._lock:
            return self._data.get(key, default)

    def get_all(self) -> dict[str, Any]:
        """Return a copy of current config."""
        with self._lock:
            return dict(self._data)

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        """Set one config value."""
        with self._lock:
            if key in self._data and self._data[key] == value:
                return
            self._data[key] = value
            self._sync_indexes()
            if persist:
                self.save()

    def update(self, values: dict[str, Any], persist: bool = True) -> None:
        """Set multiple config values."""
        with self._lock:
            changed = {
                k: v
                for k, v in values.items()
                if k not in self._data or self._data[k] != v
            }
            if not changed:
                return
            self._data.update(changed)
            self._sync_indexes()
            if persist:
                self.save()

    def add_directory(self, directory_path: str) -> bool:
        """Add a directory if valid and not duplicate."""
        normalized = str(Path(directory_path).expanduser().resolve())
        with self._lock:
            if normalized in self._data["directories"]:
                return False
            if not Path(normalized).is_dir():
                return False
            self._data["directories"].append(normalized)
            self._sync_indexes()
            self.save()
            return True

    def remove_directory(self, index: int) -> bool:
        """Remove a directory by list index."""
        with self._lock:
            directories = self._data["directories"]
            if index < 0 or index >= len(directories):
                return False
            active_index = int(self._data.get("active_directory_index", -1))
            directories.pop(index)
            if active_index == index:
                self._data["active_directory_index"] = -1
            elif active_index > index:
                self._data["active_directory_index"] = active_index - 1
            self._sync_indexes()
            self.save()
            return True

    def set_active_directory(self, index: int) -> bool:
        """Set active directory index and reset image index."""
        with self._lock:
            directories = self._data["directories"]
            if not directories:
                self._data["active_directory_index"] = -1
                self._data["current_image_index"] = 0
                self.save()
                return False
            if index < 0 or index >= len(directories):
                return False
            self._data["active_directory_index"] = index
            self._data["current_image_index"] = 0
            self.save()
            return True

    def deactivate_active_directory(self) -> None:
        """Deactivate current directory selection."""
        with self._lock:
            self._data["active_directory_index"] = -1
            self._data["current_image_index"] = 0
            self.save()

    def cycle_active_directory(self) -> bool:
        """Move to next directory and reset image index."""
        with self._lock:
            directories = self._data["directories"]
            if not directories:
                return False
            current = int(self._data.get("active_directory_index", -1))
            if current < 0 or current >= len(directories):
                self._data["active_directory_index"] = 0
            else:
                self._data["active_directory_index"] = (current + 1) % len(directories)
            self._data["current_image_index"] = 0
            self.save()
            return True

    def set_slideshow_mode(self, mode: str) -> bool:
        """Set slideshow source mode and reset image index."""
        normalized = str(mode).strip().lower()
        if normalized not in {"directory", "image_list", "url", "upload"}:
            return False
        with self._lock:
            self._data["slideshow_mode"] = normalized
            self._data["current_image_index"] = 0
            self.save()
        return True

    def add_selected_image(self, image_path: str) -> bool:
        """Add an image path to selected image list without duplicates."""
        normalized = str(Path(image_path).expanduser().resolve())
        with self._lock:
            if normalized in self._data["selected_images"]:
                return False
            if not Path(normalized).is_file():
                return False
            self._data["selected_images"].append(normalized)
            self._sync_indexes()
            self.save()
            return True

    def remove_selected_image(self, index: int) -> bool:
        """Remove image path from selected list by index."""
        with self._lock:
            images = self._data["selected_images"]
            if index < 0 or index >= len(images):
                return False
            images.pop(index)
            self._sync_indexes()
            self.save()
            return True

    def clear_selected_images(self) -> None:
        """Clear selected image list and reset navigation index."""
        with self._lock:
            self._data["selected_images"] = []
            self._data["current_image_index"] = 0
            self.save()

    def add_url_image(self, image_url: str) -> bool:
        """Add URL to url image list without duplicates."""
        normalized = str(image_url).strip()
        with self._lock:
            if not normalized:
                return False
            if normalized in self._data["url_images"]:
                return False
            self._data["url_images"].append(normalized)
            self._sync_indexes()
            self.save()
            return True

    def remove_url_image(self, index: int) -> bool:
        """Remove URL image by index."""
        with self._lock:
            images = self._data["url_images"]
            if index < 0 or index >= len(images):
                return False
            images.pop(index)
            self._sync_indexes()
            self.save()
            return True

    def clear_url_images(self) -> None:
        """Clear URL image list and reset navigation index."""
        with self._lock:
            self._data["url_images"] = []
            self._data["current_image_index"] = 0
            self.save()

    def add_uploaded_image(self, image_path: str) -> bool:
        """Add uploaded image path to list without duplicates."""
        normalized = str(Path(image_path).expanduser().resolve())
        with self._lock:
            if normalized in self._data["uploaded_images"]:
                return False
            if not Path(normalized).is_file():
                return False
            # Keep newest uploads last so order is consistent with URL images.
            self._data["uploaded_images"].append(normalized)
            self._sync_indexes()
            self.save()
            return True

    def remove_uploaded_image(self, index: int) -> bool:
        """Remove uploaded image by index."""
        with self._lock:
            images = self._data["uploaded_images"]
            if index < 0 or index >= len(images):
                return False
            images.pop(index)
            self._sync_indexes()
            self.save()
            return True

    def clear_uploaded_images(self) -> None:
        """Clear uploaded image list and reset navigation index."""
        with self._lock:
            self._data["uploaded_images"] = []
            self._data["current_image_index"] = 0
            self.save()

    def _sync_indexes(self) -> None:
        """Normalize indexes against current list lengths."""
        directories = self._data.get("directories", [])
        active_index = _safe_int(self._data.get("active_directory_index", -1), -1)
        if not directories:
            active_index = -1
        else:
            if active_index < -1:
                active_index = -1
            if active_index >= len(directories):
                active_index = len(directories) - 1
        self._data["active_directory_index"] = active_index

        mode = str(self._data.get("slideshow_mode", "directory")).strip().lower()
        current_index = _safe_int(self._data.get("current_image_index", 0), 0)
        source_list_key = MODE_LIST_MAP.get(mode)

        if source_list_key:
            source_list = self._data.get(source_list_key, [])
            if not isinstance(source_list, list) or not source_list:
                self._data["current_image_index"] = 0
                return
            if current_index < -1:
                current_index = -1
            if current_index >= len(source_list):
                current_index = len(source_list) - 1
            self._data["current_image_index"] = current_index
            return

        # directory mode (or fallback)
        self._data["current_image_index"] = max(0, current_index)
