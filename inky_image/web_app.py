"""Flask web UI and API for Inky Image Viewer."""

from __future__ import annotations

import os
import time
from collections import deque
from io import BytesIO
from pathlib import Path
from typing import Callable

from flask import Flask, jsonify, render_template, request, send_file

from inky_image.config import ConfigManager
from inky_image.image_manager import SUPPORTED_EXTENSIONS, ImageManager
from inky_image.renderer import Renderer
from inky_image.slideshow import SlideshowController


def _browse_roots_from_env() -> list[Path]:
    """Resolve filesystem roots allowed for browser and preview endpoints."""
    raw_roots = os.environ.get("INKY_IMAGE_BROWSE_ROOTS", "")
    raw_roots = raw_roots.replace(",", os.pathsep)
    root_values = [
        value.strip() for value in raw_roots.split(os.pathsep) if value.strip()
    ]
    if not root_values:
        root_values = [str(Path.home()), "/mnt", "/media"]

    roots: list[Path] = []
    for value in root_values:
        try:
            root = Path(value).expanduser().resolve()
        except OSError:
            continue
        if (not root.exists() or root.is_dir()) and root not in roots:
            roots.append(root)
    return roots


def _path_is_under_roots(path: Path, roots: list[Path]) -> bool:
    """Return true when path is inside one of the allowed browse roots."""
    return any(path == root or root in path.parents for root in roots)


def create_web_app(
    config: ConfigManager,
    image_manager: ImageManager,
    slideshow: SlideshowController,
    renderer: Renderer,
) -> Flask:
    """Create Flask app with all UI and API routes."""
    placeholder_path = (
        Path(__file__).resolve().parent.parent / "static" / "no-image.jpg"
    )
    browse_roots = _browse_roots_from_env()
    default_browse_root = browse_roots[0] if browse_roots else Path.home().resolve()

    # Why a render did not reach the panel; the UI shows these verbatim.
    render_errors = {
        "busy": "Display is busy refreshing; try again.",
        "failed": "Display refresh failed.",
        "empty": "No image available to display.",
    }

    def _render_error() -> str | None:
        """Message for the last render outcome on this request thread."""
        return render_errors.get(renderer.last_render_outcome())

    def _render_response(manager: ImageManager, rendered: bool):
        """Standard JSON response, honest about a render the panel never took."""
        if rendered:
            return jsonify({"ok": True, "status": manager.get_status()})
        return jsonify(
            {
                "ok": False,
                "error": _render_error() or "Display refresh failed.",
                "status": manager.get_status(),
            }
        )

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent.parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent.parent / "static"),
    )

    def _handle_remove_aftermath(
        manager: ImageManager, mode: str, count_key: str
    ) -> None:
        """After removing items, stop the slideshow if the pool is now empty."""
        status = manager.get_status()
        if manager.get_mode() == mode and int(status.get(count_key, 0)) == 0:
            slideshow.stop()
            config.set("slideshow_running", False)
            renderer.render_current_image()

    def _handle_activate(
        manager: ImageManager,
        activate_fn: Callable[[int], bool],
        index: int,
        error_msg: str,
    ):
        """Activate an item, re-render and return the standard JSON response."""
        if not activate_fn(index):
            return jsonify({"ok": False, "error": error_msg}), 400
        return _render_response(manager, renderer.render_current_image())

    def _handle_deactivate(
        manager: ImageManager,
        deactivate_fn: Callable[[int], bool],
        index: int,
        error_msg: str,
    ):
        """Deactivate an item, stop the slideshow, re-render and respond."""
        if not deactivate_fn(index):
            return jsonify({"ok": False, "error": error_msg}), 400
        slideshow.stop()
        config.set("slideshow_running", False)
        return _render_response(manager, renderer.render_current_image())

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def api_status():
        status = image_manager.get_status()
        status["slideshow_running"] = slideshow.is_running()
        status["slideshow_interval"] = int(config.get("slideshow_interval", 30))
        status["saturation"] = float(config.get("saturation", 0.5))
        status["brightness"] = float(config.get("brightness", 1.0))
        status["render_mode"] = str(config.get("render_mode", "default"))
        status["contrast"] = float(config.get("contrast", 1.0))
        status["scale_to_fit"] = bool(config.get("scale_to_fit", True))
        status["lock_buttons"] = bool(config.get("lock_buttons", False))
        status["render_width"] = int(config.get("render_width", 800))
        status["render_height"] = int(config.get("render_height", 480))
        status["web_port"] = int(config.get("web_port", 80))
        status["render_in_progress"] = renderer.is_render_in_progress()
        last_action = renderer.pop_last_action()
        if last_action:
            status["last_action"] = last_action
        return jsonify(status)

    @app.post("/api/directories")
    def add_directory():
        payload = request.get_json(silent=True) or {}
        directory_path = str(payload.get("path", "")).strip()
        if not directory_path:
            return jsonify({"ok": False, "error": "Missing directory path"}), 400
        ok = image_manager.add_directory(directory_path)
        if not ok:
            return jsonify(
                {"ok": False, "error": "Directory invalid or already added"}
            ), 400
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.get("/api/directories/browse")
    def browse_directories():
        raw_path = str(request.args.get("path", "")).strip()
        if raw_path:
            path_obj = Path(raw_path).expanduser().resolve()
        else:
            path_obj = default_browse_root

        if not _path_is_under_roots(path_obj, browse_roots):
            return jsonify({"ok": False, "error": "Path is outside allowed roots"}), 403

        if not path_obj.exists() or not path_obj.is_dir():
            return jsonify({"ok": False, "error": "Invalid directory path"}), 400

        try:
            entries = []
            for child in path_obj.iterdir():
                try:
                    resolved = child.resolve()
                except OSError:
                    continue
                if not _path_is_under_roots(resolved, browse_roots):
                    continue
                if child.is_dir():
                    entries.append(
                        {
                            "type": "directory",
                            "name": child.name,
                            "path": str(resolved),
                        }
                    )
                    continue
                if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    entries.append(
                        {
                            "type": "image",
                            "name": child.name,
                            "path": str(resolved),
                        }
                    )
        except OSError as exc:
            return jsonify({"ok": False, "error": f"Cannot read directory: {exc}"}), 400

        entries.sort(
            key=lambda value: (value["type"] != "directory", value["name"].lower())
        )
        parent_path = (
            str(path_obj.parent.resolve())
            if path_obj.parent != path_obj
            and _path_is_under_roots(path_obj.parent.resolve(), browse_roots)
            else None
        )

        return jsonify(
            {
                "ok": True,
                "path": str(path_obj),
                "parent_path": parent_path,
                "root_paths": [str(root) for root in browse_roots],
                "entries": entries,
                "is_root": path_obj.parent == path_obj,
            }
        )

    @app.get("/api/directories/tree")
    def directory_tree():
        """Return a flattened directory tree from root for dropdown navigation."""
        max_entries_raw = request.args.get("max_entries", "3000")
        max_depth_raw = request.args.get("max_depth", "8")
        timeout_ms_raw = request.args.get("timeout_ms", "1500")
        max_entries = 3000
        max_depth = 8
        timeout_ms = 1500
        try:
            max_entries = max(100, min(10000, int(max_entries_raw)))
        except (ValueError, TypeError):
            pass
        try:
            max_depth = max(1, min(30, int(max_depth_raw)))
        except (ValueError, TypeError):
            pass
        try:
            timeout_ms = max(250, min(10000, int(timeout_ms_raw)))
        except (ValueError, TypeError):
            pass

        directories = [
            {"path": str(root), "label": f"{root}/" if str(root) == "/" else str(root)}
            for root in browse_roots
        ]
        truncated = False
        timeout_hit = False
        deadline = time.monotonic() + (timeout_ms / 1000.0)

        queue = deque((str(root), 0) for root in browse_roots)
        while queue:
            if time.monotonic() >= deadline:
                timeout_hit = True
                truncated = True
                break

            current_path, depth = queue.popleft()
            if depth >= max_depth:
                continue

            try:
                with os.scandir(current_path) as entries:
                    children = sorted(
                        [
                            entry
                            for entry in entries
                            if entry.is_dir(follow_symlinks=False)
                        ],
                        key=lambda entry: entry.name.lower(),
                    )
            except OSError:
                continue

            for child in children:
                try:
                    child_path = Path(child.path).resolve()
                except OSError:
                    continue
                if not _path_is_under_roots(child_path, browse_roots):
                    continue
                path = str(child_path)
                child_depth = depth + 1
                indent = "  " * max(0, child_depth - 1)
                label = f"{indent}{child.name}/"
                directories.append({"path": path, "label": label})
                if len(directories) >= max_entries:
                    truncated = True
                    break
                queue.append((path, child_depth))
            if truncated:
                break

        return jsonify(
            {
                "ok": True,
                "directories": directories,
                "truncated": truncated,
                "max_entries": max_entries,
                "max_depth": max_depth,
                "timeout_ms": timeout_ms,
                "timeout_hit": timeout_hit,
            }
        )

    @app.delete("/api/directories/<int:index>")
    def remove_directory(index: int):
        ok = image_manager.remove_directory(index)
        if not ok:
            return jsonify({"ok": False, "error": "Invalid directory index"}), 400
        if image_manager.get_active_directory() is None:
            slideshow.stop()
            config.set("slideshow_running", False)
            renderer.render_current_image()
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.post("/api/directories/<int:index>/activate")
    def activate_directory(index: int):
        return _handle_activate(
            image_manager,
            image_manager.set_active_directory,
            index,
            "Invalid directory index",
        )

    @app.post("/api/mode")
    def set_mode():
        payload = request.get_json(silent=True) or {}
        mode = str(payload.get("mode", "")).strip().lower()
        if mode not in {"directory", "image_list", "url", "upload"}:
            return jsonify({"ok": False, "error": "Invalid mode"}), 400
        ok = image_manager.set_mode(mode)
        if not ok:
            return jsonify({"ok": False, "error": "Failed to set mode"}), 400
        return _render_response(image_manager, renderer.render_current_image())

    @app.post("/api/images")
    def add_image():
        payload = request.get_json(silent=True) or {}
        image_path = str(payload.get("path", "")).strip()
        if not image_path:
            return jsonify({"ok": False, "error": "Missing image path"}), 400
        ok = image_manager.add_selected_image(image_path)
        if not ok:
            return jsonify(
                {"ok": False, "error": "Image invalid, unsupported or already added"}
            ), 400
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.delete("/api/images/<int:index>")
    def remove_image(index: int):
        ok = image_manager.remove_selected_image(index)
        if not ok:
            return jsonify({"ok": False, "error": "Invalid image index"}), 400
        _handle_remove_aftermath(image_manager, "image_list", "image_count")
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.post("/api/images/clear")
    def clear_images():
        image_manager.clear_selected_images()
        _handle_remove_aftermath(image_manager, "image_list", "image_count")
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.post("/api/images/<int:index>/activate")
    def activate_selected_image(index: int):
        return _handle_activate(
            image_manager,
            image_manager.activate_selected_image,
            index,
            "Invalid selected image index",
        )

    @app.post("/api/images/<int:index>/deactivate")
    def deactivate_selected_image(index: int):
        return _handle_deactivate(
            image_manager,
            image_manager.deactivate_selected_image,
            index,
            "Selected image is not active",
        )

    @app.post("/api/url-images")
    def add_url_image():
        payload = request.get_json(silent=True) or {}
        image_url = str(payload.get("url", "")).strip()
        if not image_url:
            return jsonify({"ok": False, "error": "Missing image URL"}), 400
        ok = image_manager.add_url_image(image_url)
        if not ok:
            error = (
                image_manager.get_last_scan_error() or "URL invalid or already added"
            )
            return jsonify({"ok": False, "error": error}), 400
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.delete("/api/url-images/<int:index>")
    def remove_url_image(index: int):
        ok = image_manager.remove_url_image(index)
        if not ok:
            return jsonify({"ok": False, "error": "Invalid URL image index"}), 400
        _handle_remove_aftermath(image_manager, "url", "url_images_count")
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.post("/api/url-images/<int:index>/activate")
    def activate_url_image(index: int):
        return _handle_activate(
            image_manager,
            image_manager.activate_url_image,
            index,
            "Invalid URL image index",
        )

    @app.post("/api/url-images/<int:index>/deactivate")
    def deactivate_url_image(index: int):
        return _handle_deactivate(
            image_manager,
            image_manager.deactivate_url_image,
            index,
            "URL image is not active",
        )

    @app.post("/api/url-images/clear")
    def clear_url_images():
        image_manager.clear_url_images()
        _handle_remove_aftermath(image_manager, "url", "url_images_count")
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.post("/api/upload-images")
    def add_upload_image():
        if "image" not in request.files:
            return jsonify({"ok": False, "error": "Missing image file"}), 400
        file_storage = request.files["image"]
        file_name = str(file_storage.filename or "").strip()
        if not file_name:
            return jsonify({"ok": False, "error": "Missing image filename"}), 400
        content = file_storage.read()
        ok = image_manager.add_uploaded_image_data(file_name, content)
        if not ok:
            return jsonify(
                {"ok": False, "error": "Uploaded file is invalid or could not be saved"}
            ), 400
        if image_manager.get_mode() == "upload":
            return _render_response(
                image_manager, renderer.render_current_image()
            )
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.delete("/api/upload-images/<int:index>")
    def remove_upload_image(index: int):
        ok = image_manager.remove_uploaded_image(index)
        if not ok:
            return jsonify({"ok": False, "error": "Invalid uploaded image index"}), 400
        _handle_remove_aftermath(image_manager, "upload", "uploaded_images_count")
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.post("/api/upload-images/<int:index>/activate")
    def activate_upload_image(index: int):
        return _handle_activate(
            image_manager,
            image_manager.activate_uploaded_image,
            index,
            "Invalid uploaded image index",
        )

    @app.post("/api/upload-images/<int:index>/deactivate")
    def deactivate_upload_image(index: int):
        return _handle_deactivate(
            image_manager,
            image_manager.deactivate_uploaded_image,
            index,
            "Uploaded image is not active",
        )

    @app.post("/api/upload-images/clear")
    def clear_upload_images():
        image_manager.clear_uploaded_images()
        _handle_remove_aftermath(image_manager, "upload", "uploaded_images_count")
        return jsonify({"ok": True, "status": image_manager.get_status()})

    @app.post("/api/directories/<int:index>/deactivate")
    def deactivate_directory(index: int):
        return _handle_deactivate(
            image_manager,
            image_manager.deactivate_directory,
            index,
            "Directory is not active",
        )

    @app.post("/api/slideshow/toggle")
    def toggle_slideshow():
        is_running = slideshow.toggle()
        config.set("slideshow_running", is_running)
        return jsonify({"ok": True, "slideshow_running": is_running})

    @app.post("/api/slideshow/next")
    def next_image():
        return _render_response(image_manager, renderer.render_next_image())

    @app.post("/api/slideshow/prev")
    def previous_image():
        return _render_response(image_manager, renderer.render_previous_image())

    @app.post("/api/display/repaint")
    def repaint_display():
        """Force a full refresh of the current image and settings.

        Skips the identical-render optimisation, which is the only way to heal
        a panel left half written (a restart that interrupted a refresh).
        """
        return _render_response(
            image_manager, renderer.render_current_image(force=True)
        )

    @app.post("/api/settings")
    def update_settings():
        payload = request.get_json(silent=True) or {}
        interval = payload.get("slideshow_interval")
        saturation = payload.get("saturation")
        brightness = payload.get("brightness")
        contrast = payload.get("contrast")
        render_mode = payload.get("render_mode")
        scale_to_fit = payload.get("scale_to_fit")
        lock_buttons = payload.get("lock_buttons")
        render_width = payload.get("render_width")
        render_height = payload.get("render_height")

        updates = {}
        if interval is not None:
            try:
                updates["slideshow_interval"] = max(30, int(interval))
            except (ValueError, TypeError):
                return jsonify(
                    {"ok": False, "error": "Invalid slideshow_interval"}
                ), 400
        if saturation is not None:
            try:
                updates["saturation"] = max(0.0, min(1.0, float(saturation)))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "Invalid saturation"}), 400
        if brightness is not None:
            try:
                updates["brightness"] = max(0.25, min(2.0, float(brightness)))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "Invalid brightness"}), 400
        if contrast is not None:
            try:
                updates["contrast"] = max(0.25, min(2.0, float(contrast)))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "Invalid contrast"}), 400
        if render_mode is not None:
            normalized_mode = str(render_mode).strip().lower()
            if normalized_mode not in {"default", "palette", "oklab"}:
                return jsonify({"ok": False, "error": "Invalid render_mode"}), 400
            updates["render_mode"] = normalized_mode
        if scale_to_fit is not None:
            if isinstance(scale_to_fit, bool):
                updates["scale_to_fit"] = scale_to_fit
            else:
                return jsonify({"ok": False, "error": "Invalid scale_to_fit"}), 400
        if lock_buttons is not None:
            if isinstance(lock_buttons, bool):
                updates["lock_buttons"] = lock_buttons
            else:
                return jsonify({"ok": False, "error": "Invalid lock_buttons"}), 400
        if render_width is not None:
            try:
                updates["render_width"] = max(64, int(render_width))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "Invalid render_width"}), 400
        if render_height is not None:
            try:
                updates["render_height"] = max(64, int(render_height))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "Invalid render_height"}), 400

        render_error = None
        if updates:
            config.update(updates)
            if (
                "saturation" in updates
                or "render_mode" in updates
                or "brightness" in updates
                or "contrast" in updates
                or "scale_to_fit" in updates
                or "render_width" in updates
                or "render_height" in updates
            ):
                # The settings are saved either way; report a stale panel
                # separately instead of failing the save.
                if not renderer.render_current_image():
                    render_error = _render_error() or "Display refresh failed."

        payload = {
            "ok": True,
            "status": image_manager.get_status(),
            "settings": config.get_all(),
        }
        if render_error:
            payload["render_error"] = render_error
        return jsonify(payload)

    @app.post("/api/folder/cycle")
    def cycle_folder():
        ok = renderer.cycle_mode_and_render()
        payload = {
            "status": image_manager.get_status(),
            "mode": image_manager.get_mode(),
        }
        if ok:
            payload["ok"] = True
        else:
            payload["ok"] = False
            payload["error"] = _render_error() or "Display refresh failed."
        return jsonify(payload)

    @app.post("/api/slideshow/reshuffle")
    def reshuffle_slideshow():
        if not image_manager.reshuffle():
            return jsonify(
                {
                    "ok": False,
                    "error": "No images available to reshuffle.",
                    "status": image_manager.get_status(),
                }
            )
        return _render_response(image_manager, renderer.render_current_image())

    def _preview_overrides() -> dict | None:
        """Candidate settings from the query string, so preview runs before save."""
        overrides: dict = {}
        numeric = {
            "saturation": (0.0, 1.0),
            "brightness": (0.25, 2.0),
            "contrast": (0.25, 2.0),
            "render_width": (64, 10000),
            "render_height": (64, 10000),
        }
        for key, (low, high) in numeric.items():
            raw = request.args.get(key)
            if raw is None or not raw.strip():
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValueError(key) from None
            value = max(low, min(high, value))
            overrides[key] = (
                int(value) if key in {"render_width", "render_height"} else value
            )
        raw_mode = request.args.get("render_mode")
        if raw_mode is not None and raw_mode.strip():
            normalised = raw_mode.strip().lower()
            if normalised not in {"default", "palette", "oklab"}:
                raise ValueError("render_mode")
            overrides["render_mode"] = normalised
        raw_fit = request.args.get("scale_to_fit")
        if raw_fit is not None and raw_fit.strip():
            normalised = raw_fit.strip().lower()
            if normalised not in {"0", "1", "true", "false", "on", "off"}:
                raise ValueError("scale_to_fit")
            overrides["scale_to_fit"] = normalised in {"1", "true", "on"}
        return overrides or None

    @app.get("/api/debug/rendered-preview")
    def rendered_preview():
        """Return the frame the pipeline would send, without touching the panel."""
        try:
            overrides = _preview_overrides()
        except ValueError as exc:
            return jsonify({"ok": False, "error": f"Invalid {exc}"}), 400
        png = renderer.render_preview_png(overrides)
        if not png:
            messages = {
                "busy": (
                    "Display is busy refreshing; try again in a moment.",
                    409,
                ),
                "empty": ("No current image to preview; activate an image first.", 404),
            }
            reason = renderer.preview_unavailable_reason()
            if reason.startswith("failed: "):
                return jsonify({"ok": False, "error": reason[8:]}), 500
            message, code = messages.get(
                reason,
                ("Preview failed; check the service log.", 500),
            )
            return jsonify({"ok": False, "error": message}), code
        response = send_file(BytesIO(png), mimetype="image/png")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/current-image")
    def current_image():
        image_path = renderer.get_last_rendered_image_path()
        if not image_path:
            if placeholder_path.exists():
                return send_file(placeholder_path, mimetype="image/*")
            return jsonify({"ok": False, "error": "No current image"}), 404
        path_obj = Path(image_path)
        if not path_obj.exists():
            return jsonify({"ok": False, "error": "Image file missing"}), 404
        return send_file(path_obj, mimetype="image/*")

    @app.get("/api/preview-file")
    def preview_file():
        raw_path = str(request.args.get("path", "")).strip()
        if not raw_path:
            return jsonify({"ok": False, "error": "Missing path"}), 400
        path_obj = Path(raw_path).expanduser().resolve()
        if not _path_is_under_roots(path_obj, browse_roots):
            return jsonify({"ok": False, "error": "Path is outside allowed roots"}), 403
        if not path_obj.exists() or not path_obj.is_file():
            return jsonify({"ok": False, "error": "Invalid file path"}), 404
        if path_obj.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return jsonify({"ok": False, "error": "Unsupported image extension"}), 400
        return send_file(path_obj, mimetype="image/*")

    return app
