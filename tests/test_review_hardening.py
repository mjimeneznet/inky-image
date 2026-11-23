"""Characterization tests for behaviors the review named as untested (S10).

These pin behavior that already shipped on ``fix/review-hardening``; they are
expected to pass on the first run without any production change. Hardware
dependencies (PIL, inky, gpiod, gpiodevice) are mocked in conftest.py.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from unittest.mock import MagicMock

from inky_image.button_handler import BUTTONS, ButtonHandler
from inky_image.display import DisplayManager


class TestUploadHappyPath:
    """``POST /api/upload-images`` persists the file and reports the count."""

    def test_upload_saves_cache_file_and_grows_count(
        self, client, manager, tmp_path, monkeypatch
    ):
        upload_cache = tmp_path / "upload-cache"
        upload_cache.mkdir()
        monkeypatch.setattr(manager._upload_source, "_cache_dir", upload_cache)

        before = client.get("/api/status").get_json()["uploaded_images_count"]

        resp = client.post(
            "/api/upload-images",
            data={"image": (io.BytesIO(b"fake-image-bytes"), "photo.jpg")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["status"]["uploaded_images_count"] == before + 1
        stored = Path(body["status"]["uploaded_images"][0])
        assert stored.exists()


class TestCurrentImageServing:
    """``GET /api/current-image`` serves the rendered file verbatim."""

    def test_serves_rendered_file_byte_identical(self, client, tmp_path):
        payload = b"\x89PNG-fake-rendered-bytes"
        rendered = tmp_path / "rendered.png"
        rendered.write_bytes(payload)
        client.application.renderer_stub.set_last_rendered_image_path(str(rendered))

        resp = client.get("/api/current-image")

        assert resp.status_code == 200
        assert resp.data == payload


class TestRemoveAftermath:
    """Removing the last image stops the slideshow and re-renders once."""

    def test_removing_last_image_stops_slideshow_and_renders_once(
        self, client, tmp_path
    ):
        image_path = tmp_path / "images" / "a.jpg"
        assert client.post(
            "/api/images", json={"path": str(image_path)}
        ).status_code == 200
        # Activate switches the mode to image_list so the aftermath branch applies.
        assert client.post("/api/images/0/activate").status_code == 200

        stub = client.application.renderer_stub
        renders_before = stub.render_current_image_calls
        assert client.post("/api/slideshow/toggle").get_json()[
            "slideshow_running"
        ] is True

        resp = client.delete("/api/images/0")

        assert resp.status_code == 200
        status = client.get("/api/status").get_json()
        assert status["slideshow_running"] is False
        assert status["image_count"] == 0
        assert stub.render_current_image_calls - renders_before == 1


class TestDirectoryDeactivate:
    """Deactivating the active directory clears ``active_directory_index``."""

    def test_deactivate_active_directory_returns_ok(self, client):
        assert client.post("/api/directories/0/activate").status_code == 200

        resp = client.post("/api/directories/0/deactivate")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["status"]["active_directory_index"] == -1


class TestButtonHandlerStart:
    """``ButtonHandler.start()`` sets up GPIO and the loop runs until stop."""

    def test_start_runs_thread_and_stop_releases_request(self, monkeypatch):
        class FakeRequest:
            def __init__(self):
                self.wait_calls = 0
                self.released = False

            def wait_edge_events(self, timeout=None):
                self.wait_calls += 1
                return False  # no events: one clean loop iteration

            def read_edge_events(self):
                return []

            def release(self):
                self.released = True

        fake_request = FakeRequest()
        chip = MagicMock()
        chip.line_offset_from_id.side_effect = lambda gpio_id: 100 + BUTTONS.index(
            gpio_id
        )
        chip.request_lines.return_value = fake_request
        monkeypatch.setattr(
            "inky_image.button_handler.gpiodevice.find_chip_by_platform",
            lambda: chip,
        )

        handler = ButtonHandler({})
        handler.start()
        assert handler._thread is not None
        assert handler._thread.is_alive()

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and fake_request.wait_calls == 0:
            time.sleep(0.01)
        assert fake_request.wait_calls >= 1, "reader thread must have run the loop"

        handler.stop()
        assert fake_request.released is True


class TestDisplayManagerImagePreparation:
    """``_resize_image`` picks fit vs pad; ``_prepare_image`` adapts to panel."""

    @staticmethod
    def _make_manager():
        from PIL import ImageOps

        ImageOps.fit.reset_mock()
        ImageOps.pad.reset_mock()
        dm = DisplayManager()
        dm.width = 100
        dm.height = 100
        return dm

    def test_image_preparation_fit_pad_and_panel_re_resize(self):
        """Fit vs pad selection, and the panel-size adaptation, are exact."""
        from PIL import ImageOps

        dm = self._make_manager()

        dm._resize_image(MagicMock(), (64, 64), scale_to_fit=True)
        ImageOps.fit.assert_called_once()
        assert ImageOps.fit.call_args.args[1] == (64, 64)
        ImageOps.pad.assert_not_called()

        ImageOps.fit.reset_mock()
        ImageOps.pad.reset_mock()
        dm._resize_image(MagicMock(), (64, 64), scale_to_fit=False)
        ImageOps.pad.assert_called_once()
        assert ImageOps.pad.call_args.kwargs.get("color") == "white"
        ImageOps.fit.assert_not_called()

        ImageOps.fit.reset_mock()
        ImageOps.pad.reset_mock()
        dm._prepare_image(
            MagicMock(), scale_to_fit=True, target_width=64, target_height=64
        )
        assert ImageOps.fit.call_count == 2
        assert ImageOps.fit.call_args_list[0].args[1] == (64, 64)
        assert ImageOps.fit.call_args_list[1].args[1] == (100, 100)


class TestBrowserModuleScope:
    """browser.js must call its own closure helpers, not the owner object.

    ``createBrowser()`` returns an object that main.js keeps as ``browser``,
    but that name does not exist inside the factory. A handler written as
    ``browser.loadDirectoryBrowser(...)`` throws a ReferenceError the moment
    the user clicks, which is exactly what made the directory list
    unnavigable while every test and every other route stayed green.
    """

    def test_handlers_do_not_reference_an_owner_object(self):
        import re
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "static" / "js"
        text = (source / "browser.js").read_text(encoding="utf-8")
        offenders = [
            f"browser.js:{number}"
            for number, line in enumerate(text.splitlines(), start=1)
            if re.search(r"(?<![\w.$])browser\.\w+\s*\(", line)
        ]

        assert offenders == [], (
            "browser.js calls a `browser` object it does not have: "
            f"{offenders}"
        )


class TestRenderedPreviewRoute:
    """GET /api/debug/rendered-preview exposes the pipeline frame read-only."""

    def test_serves_the_pipeline_frame(self, client):
        png = b"\x89PNG\r\n\x1a\nfake-frame"
        client.application.renderer_stub.set_preview_png(png)

        resp = client.get("/api/debug/rendered-preview")

        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
        assert resp.data == png

    def test_reports_no_frame(self, client):
        client.application.renderer_stub.set_preview_png(None, reason="empty")

        resp = client.get("/api/debug/rendered-preview")

        assert resp.status_code == 404
        assert resp.get_json()["error"] == (
            "No current image to preview; activate an image first."
        )

    def test_reports_a_busy_display(self, client):
        client.application.renderer_stub.set_preview_png(None, reason="busy")

        resp = client.get("/api/debug/rendered-preview")

        assert resp.status_code == 409
        assert resp.get_json()["error"] == (
            "Display is busy refreshing; try again in a moment."
        )

    def test_reports_a_failed_preview(self, client):
        client.application.renderer_stub.set_preview_png(None, reason="failed")

        resp = client.get("/api/debug/rendered-preview")

        assert resp.status_code == 500
        assert "check the service log" in resp.get_json()["error"]

    def test_reports_the_cause_of_a_failed_preview(self, client):
        client.application.renderer_stub.set_preview_png(
            None, reason="failed: unexpected keyword argument"
        )

        resp = client.get("/api/debug/rendered-preview")

        assert resp.status_code == 500
        assert resp.get_json()["error"] == "unexpected keyword argument"
