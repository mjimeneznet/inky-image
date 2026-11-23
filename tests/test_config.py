"""Tests for ConfigManager — configuration persistence, normalization, clamping."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from inky_image.config import DEFAULT_CONFIG, ConfigManager


class TestDefaults:
    """Empty / fresh config should match DEFAULT_CONFIG."""

    def test_default_values(self, config):
        for key, expected in DEFAULT_CONFIG.items():
            assert config.get(key) == expected, f"Mismatch for {key}"


class TestPersistAndReload:
    """Round-trip save / reload."""

    def test_persist_and_reload(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg = ConfigManager(str(cfg_path))
        cfg.set("slideshow_interval", 60)
        cfg.set("saturation", 0.8)
        cfg.set("render_width", 400)
        cfg.set("render_height", 300)

        # Reload from same path
        cfg2 = ConfigManager(str(cfg_path))
        assert cfg2.get("slideshow_interval") == 60
        assert cfg2.get("saturation") == 0.8
        assert cfg2.get("render_width") == 400
        assert cfg2.get("render_height") == 300


class TestTypeNormalization:
    """Persisted values with wrong types should be normalized on load."""

    def test_type_normalization(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        # Write raw data with wrong types
        raw = {
            "slideshow_interval": "abc",
            "saturation": "not-a-float",
            "render_width": "hello",
            "render_height": 12.7,
            "active_directory_index": None,
            "current_image_index": "invalid",
            "scale_to_fit": "yes",
            "lock_buttons": "true",
            "directories": [1, 2, "valid_path"],
            "selected_images": [None, "also_valid"],
        }
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(raw), encoding="utf-8")

        cfg = ConfigManager(str(cfg_path))
        # Integers that couldn't parse fall back to defaults
        assert isinstance(cfg.get("slideshow_interval"), int)
        assert cfg.get("slideshow_interval") == 30  # max(30, default)
        assert isinstance(cfg.get("saturation"), float)
        assert 0.0 <= cfg.get("saturation") <= 1.0
        assert isinstance(cfg.get("render_width"), int)
        assert cfg.get("render_width") >= 64
        assert isinstance(cfg.get("render_height"), int)
        assert cfg.get("render_height") >= 64
        # Lists should filter non-strings
        assert all(isinstance(p, str) for p in cfg.get("directories", []))
        assert all(isinstance(p, str) for p in cfg.get("selected_images", []))
        # Boolean strings resolved
        assert cfg.get("scale_to_fit") is True
        assert cfg.get("lock_buttons") is True


class TestClamping:
    """Value clamping for slideshow interval, saturation, render size."""

    def test_slideshow_interval_floor(self, config):
        config.set("slideshow_interval", 5)
        # Load() clamps to 30
        cfg2 = ConfigManager(str(config.config_path))
        assert cfg2.get("slideshow_interval") >= 30

    def test_saturation_clamp(self, config):
        config.set("saturation", -0.5)
        cfg = ConfigManager(str(config.config_path))
        sat = cfg.get("saturation")
        assert sat >= 0.0, f"{sat} should be >= 0.0"

        config.set("saturation", 5.0)
        cfg = ConfigManager(str(config.config_path))
        sat = cfg.get("saturation")
        assert sat <= 1.0, f"{sat} should be <= 1.0"

    def test_render_width_height_minimum(self, config):
        config.set("render_width", 10)
        config.set("render_height", 20)
        cfg = ConfigManager(str(config.config_path))
        assert cfg.get("render_width") >= 64
        assert cfg.get("render_height") >= 64


class TestDirectoryManagement:
    """Adding / removing directories."""

    def test_add_directory_duplicate(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg = ConfigManager(str(cfg_path))
        d = tmp_path / "testdir"
        d.mkdir()
        assert cfg.add_directory(str(d)) is True
        assert cfg.add_directory(str(d)) is False

    def test_add_directory_nonexistent(self, config):
        assert config.add_directory("/nonexistent/path/xyz123") is False

    def test_remove_directory_shifts_active(self, config, tmp_path):
        dirs = []
        for i in range(3):
            d = tmp_path / f"dir{i}"
            d.mkdir()
            dirs.append(str(d))
            config.add_directory(str(d))

        # Activate index 1
        config.set_active_directory(1)
        assert config.get("active_directory_index") == 1

        # Remove before active (index 0) → active shifts to 0
        config.remove_directory(0)
        assert config.get("active_directory_index") == 0

        # Remove active itself → index becomes -1
        config.remove_directory(0)
        assert config.get("active_directory_index") == -1

        # Re-add and test removing after active
        config.add_directory(str(tmp_path / "newdir"))
        config.set_active_directory(0)
        config.remove_directory(1)  # after active → no shift
        assert config.get("active_directory_index") == 0


class TestModeValidation:
    """Invalid slideshow modes fall back gracefully."""

    def test_mode_validation(self, tmp_path):
        raw = {"slideshow_mode": "invalid_weird_mode"}
        cfg_path = tmp_path / "config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(raw), encoding="utf-8")
        cfg = ConfigManager(str(cfg_path))
        assert cfg.get("slideshow_mode") == "directory"


class TestSyncIndexes:
    """_sync_indexes handles empty lists and out-of-bounds values."""

    def test_sync_indexes_empty(self, config):
        config._data["directories"] = []
        config._data["active_directory_index"] = 0
        config._sync_indexes()
        assert config._data["active_directory_index"] == -1

    def test_sync_indexes_clamp(self, config, tmp_path):
        d = tmp_path / "adir"
        d.mkdir()
        config.add_directory(str(d))
        config.set_active_directory(0)

        # Artificially set index beyond bounds
        config._data["active_directory_index"] = 99
        config._sync_indexes()
        assert config._data["active_directory_index"] == 0


class TestCacheWrites:
    """set() with unchanged value should not write to disk."""

    def test_cache_writes(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg = ConfigManager(str(cfg_path))

        # Force a write so mtime is fresh
        cfg.set("saturation", 0.5)
        mtime_before = os.path.getmtime(cfg_path)

        time.sleep(0.01)  # ensure filesystem timestamp would differ
        cfg.set("saturation", 0.5)  # same value — should be no-op

        mtime_after = os.path.getmtime(cfg_path)
        assert mtime_after == mtime_before, "File mtime changed despite same value"


class TestUploadOrder:
    """add_uploaded_image inserts at front (newest first)."""

    def test_upload_order(self, config, tmp_path):
        files = []
        for name in ("first.jpg", "second.jpg", "third.jpg"):
            p = tmp_path / name
            p.write_text("data")
            files.append(str(p))
            config.add_uploaded_image(str(p))

        images = config.get("uploaded_images", [])
        # Resolve for deterministic comparison (macOS /var vs /private/var)
        resolved = [str(Path(p).resolve()) for p in files]
        # add_uploaded_image appends (newest last, consistent with URL images)
        assert images[0] == resolved[0]
        assert images[1] == resolved[1]
        assert images[2] == resolved[2]


class TestClearEmptyState:
    """Clear operations on empty lists should not crash."""

    def test_clear_empty_state(self, config):
        # All of these should be no-ops
        config.clear_selected_images()
        config.clear_url_images()
        config.clear_uploaded_images()
        config.deactivate_active_directory()
        assert True  # reached without exception

class TestAtomicSave:
    """save() must never leave a truncated config at config_path.

    The service runs on a Raspberry Pi that loses power by being unplugged.
    A non-atomic write can land a partial JSON body at the real path, which
    load() then throws away, wiping directories/lists/URLs.
    """

    def test_failed_write_preserves_previous_config(self, tmp_path, monkeypatch):
        import os as os_module

        cfg_path = tmp_path / "config.json"
        photo_dir = tmp_path / "photos"
        photo_dir.mkdir()

        cfg = ConfigManager(str(cfg_path))
        cfg.set("slideshow_interval", 42)
        assert cfg.add_directory(str(photo_dir))
        cfg.save()

        # Simulate the write dying before the new content is in place.
        def boom(*args, **kwargs):
            raise OSError("disk gone")

        with monkeypatch.context() as patch:
            patch.setattr(os_module, "replace", boom)
            with pytest.raises(OSError):
                cfg.save()

        # The file on disk must still be the good, complete, previous version.
        untouched = ConfigManager(str(cfg_path))
        assert untouched.get("slideshow_interval") == 42
        assert untouched.get("directories") == [str(photo_dir.resolve())]

    def test_no_temp_file_left_behind(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg = ConfigManager(str(cfg_path))
        cfg.set("saturation", 0.9)
        cfg.save()
        strays = [p.name for p in tmp_path.iterdir() if p.name != "config.json"]
        assert strays == []

    def test_save_leaves_valid_json_for_large_config(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg = ConfigManager(str(cfg_path))
        pool = tmp_path / "pool"
        pool.mkdir()
        for i in range(500):
            shot = pool / f"img-{i:04d}.jpg"
            shot.write_text("x")
            assert cfg.add_selected_image(str(shot))

        loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert len(loaded["selected_images"]) == 500


class TestToneSettings:
    """Brightness and contrast default to a no-op and are clamped."""

    def test_defaults_are_neutral(self, config):
        assert config.get("brightness") == 1.0
        assert config.get("contrast") == 1.0

    def test_values_are_clamped_on_load(self, config):
        """set() is the raw setter; the normalisation happens when loading."""
        config.set("brightness", 9.0)
        config.set("contrast", 0.01)

        reloaded = type(config)(str(config.config_path))

        assert reloaded.get("brightness") == 2.0
        assert reloaded.get("contrast") == 0.25

    def test_values_survive_a_reload(self, config):
        config.set("brightness", 1.35)
        config.set("contrast", 0.8)

        reloaded = type(config)(str(config.config_path))

        assert reloaded.get("brightness") == 1.35
        assert reloaded.get("contrast") == 0.8
