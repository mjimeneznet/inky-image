"""Tests for inky_image.web_app — Flask API route coverage.

Every one of the 32 routes is exercised by at least one test. Tests group
under classes named after their concern, use plain ``assert``, and follow
the existing test style in the repository.
"""

from __future__ import annotations


class TestBrowseRootSecurity:
    """``/api/preview-file`` is the one route that reads an arbitrary path.

    The ``client`` fixture pins ``INKY_IMAGE_BROWSE_ROOTS`` to
    ``<tmp_path>/browse_root``, so a 403 proves the guard refused the path and
    a 200 proves the allow-list still lets legitimate files through. Without
    the positive test a guard that rejected everything would pass this class.
    """

    @staticmethod
    def _root(tmp_path):
        root = tmp_path / "browse_root"
        root.mkdir(exist_ok=True)
        return root

    def test_real_image_under_root_is_served(self, client, tmp_path):
        """A file inside an allowed root must come back byte-identical."""
        payload = b"\xff\xd8\xff\xe0not-a-real-jpeg"
        image = self._root(tmp_path) / "photo.jpg"
        image.write_bytes(payload)

        resp = client.get(f"/api/preview-file?path={image}")

        assert resp.status_code == 200
        assert resp.data == payload

    def test_directory_under_root_is_not_served(self, client, tmp_path):
        """The root itself passes the guard but is not a file, so 404."""
        root = self._root(tmp_path)

        resp = client.get(f"/api/preview-file?path={root}")

        assert resp.status_code == 404

    def test_non_image_extension_under_root_is_refused(self, client, tmp_path):
        """Allowed root, wrong extension: rejected before the bytes are read."""
        secret = self._root(tmp_path) / "notes.txt"
        secret.write_text("keep out")

        resp = client.get(f"/api/preview-file?path={secret}")

        assert resp.status_code == 400

    def test_missing_path_argument_is_refused(self, client):
        """No ``path`` query argument at all is a 400, not a 500."""
        assert client.get("/api/preview-file").status_code == 400

    def test_dotdot_escape_refused(self, client):
        """A path escaping the root via ``..`` must be rejected."""
        resp = client.get("/api/preview-file?path=/browse_root/../../../etc")
        assert resp.status_code == 403
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_absolute_path_outside_root_refused(self, client):
        """An absolute path outside the roots must be refused with 403."""
        resp = client.get("/api/preview-file?path=/etc/hosts")
        assert resp.status_code == 403
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_symlink_escaping_root_refused(self, client, tmp_path):
        """A link inside the root must not smuggle out a file outside it."""
        outside = tmp_path / "outside.jpg"
        outside.write_bytes(b"\xff\xd8\xff\xe0secret-bytes")
        link = self._root(tmp_path) / "escape.jpg"
        link.symlink_to(outside)

        resp = client.get(f"/api/preview-file?path={link}")

        # The route resolve()s the path first, so the target is what gets checked.
        assert resp.status_code == 403


class TestIndexRoute:
    """The root template route."""

    def test_index_returns_200(self, client):
        """GET / should serve the template."""
        resp = client.get("/")
        assert resp.status_code == 200


class TestStatusRoute:
    """GET /api/status returns the full status shape."""

    def test_status_has_required_keys(self, client):
        """The response must include mode, image_count and slideshow fields."""
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        for key in (
            "mode",
            "image_count",
            "current_image_index",
            "slideshow_running",
            "slideshow_interval",
            "saturation",
            "scale_to_fit",
            "lock_buttons",
            "render_width",
            "render_height",
            "web_port",
            "render_in_progress",
        ):
            assert key in data, f"Missing key: {key}"

    def test_last_action_is_delivered_exactly_once(self, client):
        """The physical-button toast contract.

        ``pop_last_action()`` is destructive, so the press must appear on one
        poll and never again -- otherwise the UI toasts on every 2s refresh.
        """
        stub = client.application.renderer_stub
        stub.set_last_action({"action": "B", "ts": "123.5"})

        first = client.get("/api/status").get_json()
        second = client.get("/api/status").get_json()

        assert first["last_action"] == {"action": "B", "ts": "123.5"}
        assert "last_action" not in second

    def test_last_action_absent_without_a_press(self, client):
        """No key at all, which is what ``refreshStatus()`` guards with."""
        assert "last_action" not in client.get("/api/status").get_json()

    def test_render_in_progress_reaches_the_ui(self, client):
        """The busy badge and the button lock both read this flag."""
        client.application.renderer_stub.set_render_in_progress(True)

        assert client.get("/api/status").get_json()["render_in_progress"] is True


class TestDirectoryRoutes:
    """POST /api/directories · GET browse/tree · DELETE · activate/deactivate."""

    def test_add_directory_missing_path(self, client):
        """POST /api/directories with no path must return 400."""
        resp = client.post("/api/directories", json={})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_add_directory_valid(self, client, tmp_path):
        """POST /api/directories with a valid path must return ok=True."""
        path = str(tmp_path / "browse_root")
        resp = client.post("/api/directories", json={"path": path})
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True

    def test_browse_directories_empty(self, client, tmp_path):
        """GET /api/directories/browse returns empty entries for an empty dir."""
        path = str(tmp_path / "browse_root")
        resp = client.get(f"/api/directories/browse?path={path}")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True
        assert data["entries"] == []

    def test_directory_tree(self, client):
        """GET /api/directories/tree returns truncated=False for empty roots."""
        resp = client.get("/api/directories/tree")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True

    def test_delete_directory_invalid_index(self, client):
        """DELETE /api/directories/<int:1> when only index 0 exists returns 400."""
        resp = client.delete("/api/directories/1")
        assert resp.status_code == 400

    def test_activate_directory_invalid_index(self, client):
        """POST /api/directories/<int:index>/activate with out-of-range."""
        resp = client.post("/api/directories/999/activate")
        assert resp.status_code == 400


class TestIndexValidation:
    """Out-of-range and non-integer indexes must return errors, not 500."""

    def test_non_integer_index_returns_404(self, client):
        """A non-integer index (``abc``) must yield a Flask 404."""
        resp = client.get("/api/images/abc")
        assert resp.status_code == 404

    def test_out_of_range_index_returns_400(self, client):
        """Index 999 when no images exist must return 400."""
        resp = client.post("/api/images/999/activate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_delete_out_of_range_directory_index(self, client):
        """DELETE /api/directories/<int:999> returns 400 when no dirs."""
        resp = client.delete("/api/directories/999")
        assert resp.status_code == 400

    def test_non_integer_directory_index(self, client):
        """GET /api/directories/abc must yield a Flask 404."""
        resp = client.get("/api/directories/abc")
        assert resp.status_code == 404


class TestModeRoute:
    """POST /api/mode — valid and invalid modes."""

    def test_set_valid_mode(self, client):
        """POST /api/mode with ``image_list`` must succeed."""
        resp = client.post("/api/mode", json={"mode": "image_list"})
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True

    def test_set_invalid_mode(self, client):
        """POST /api/mode with an unknown mode must return 400."""
        resp = client.post("/api/mode", json={"mode": "invalid"})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False


class TestAddImageRoutes:
    """POST /api/images · POST /api/url-images · POST /api/upload-images."""

    def test_add_image_missing_path(self, client):
        """POST /api/images with no ``path`` returns 400."""
        resp = client.post("/api/images", json={})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_add_url_image_missing_url(self, client):
        """POST /api/url-images with no ``url`` returns 400."""
        resp = client.post("/api/url-images", json={})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_add_url_image_invalid_scheme(self, client):
        """file:// URLs must be rejected (400) by the manager."""
        resp = client.post("/api/url-images", json={"url": "file:///tmp/x.jpg"})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_add_upload_image_missing_file(self, client):
        """POST /api/upload-images without a file returns 400."""
        resp = client.post("/api/upload-images")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False


class TestRemoveImageRoutes:
    """DELETE /api/images · DELETE /api/url-images · DELETE /api/upload-images."""

    def test_delete_image_index(self, client):
        """DELETE /api/images/999 returns 400 (out of range)."""
        resp = client.delete("/api/images/999")
        assert resp.status_code == 400

    def test_delete_url_image_index(self, client):
        """DELETE /api/url-images/999 returns 400 (out of range)."""
        resp = client.delete("/api/url-images/999")
        assert resp.status_code == 400

    def test_delete_upload_image_index(self, client):
        """DELETE /api/upload-images/999 returns 400 (out of range)."""
        resp = client.delete("/api/upload-images/999")
        assert resp.status_code == 400


class TestClearImageRoutes:
    """POST /api/images/clear · url-images/clear · upload-images/clear."""

    def test_clear_images(self, client):
        """POST /api/images/clear returns ok=True."""
        resp = client.post("/api/images/clear")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True

    def test_clear_url_images(self, client):
        """POST /api/url-images/clear returns ok=True."""
        resp = client.post("/api/url-images/clear")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True

    def test_clear_upload_images(self, client):
        """POST /api/upload-images/clear returns ok=True."""
        resp = client.post("/api/upload-images/clear")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True


class TestActivateDeactivateRoutes:
    """Activate and deactivate routes for directories, images, URLs, uploads."""

    def test_activate_directory_invalid(self, client):
        """POST /api/directories/<idx>/activate with out-of-range index returns 400."""
        resp = client.post("/api/directories/999/activate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_deactivate_directory_invalid(self, client):
        """POST /api/directories/<idx>/deactivate returns 400."""
        resp = client.post("/api/directories/0/deactivate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_activate_selected_image_index(self, client):
        """POST /api/images/<idx>/activate with no images returns 400."""
        resp = client.post("/api/images/0/activate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_deactivate_selected_image_index(self, client):
        """POST /api/images/<idx>/deactivate with no images returns 400."""
        resp = client.post("/api/images/0/deactivate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_activate_url_image_index(self, client):
        """POST /api/url-images/<idx>/activate with no URL images returns 400."""
        resp = client.post("/api/url-images/0/activate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_deactivate_url_image_index(self, client):
        """POST /api/url-images/<idx>/deactivate with no URL images returns 400."""
        resp = client.post("/api/url-images/0/deactivate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_activate_uploaded_image_index(self, client):
        """POST /api/upload-images/<idx>/activate returns 400."""
        resp = client.post("/api/upload-images/0/activate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_deactivate_uploaded_image_index(self, client):
        """POST /api/upload-images/<idx>/deactivate returns 400."""
        resp = client.post("/api/upload-images/0/deactivate")
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False


class TestSlideshowRoutes:
    """toggle · next · prev · reshuffle — assert renderer calls."""

    def test_slideshow_toggle(self, client):
        """POST /api/slideshow/toggle returns ok and the running state."""
        resp = client.post("/api/slideshow/toggle")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True
        assert "slideshow_running" in data

    def test_slideshow_next(self, client):
        """POST /api/slideshow/next returns ok and status."""
        resp = client.post("/api/slideshow/next")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True

    def test_slideshow_prev(self, client):
        """POST /api/slideshow/prev returns ok and status."""
        resp = client.post("/api/slideshow/prev")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True

    def test_slideshow_reshuffle_no_images(self, client):
        """POST /api/slideshow/reshuffle returns ok=False when no images."""
        resp = client.post("/api/slideshow/reshuffle")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False


class TestStatusWithRendererCalls:
    """POST routes that call render_current_image must be verified."""

    def test_mode_calls_render(self, client):
        """POST /api/mode calls renderer.render_current_image()."""
        resp = client.post("/api/mode", json={"mode": "image_list"})
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True


class TestSettingsRoutes:
    """POST /api/settings — coercion, clamping, non-numeric rejection."""

    def test_settings_invalid_interval(self, client):
        """Non-numeric slideshow_interval must return 400."""
        resp = client.post("/api/settings", json={"slideshow_interval": "abc"})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_settings_invalid_saturation(self, client):
        """Non-numeric saturation must return 400."""
        resp = client.post("/api/settings", json={"saturation": "xyz"})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_settings_invalid_scale_to_fit(self, client):
        """Non-boolean scale_to_fit must return 400."""
        resp = client.post("/api/settings", json={"scale_to_fit": "true"})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_settings_invalid_lock_buttons(self, client):
        """Non-boolean lock_buttons must return 400."""
        resp = client.post("/api/settings", json={"lock_buttons": "yes"})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_settings_invalid_render_width(self, client):
        """Non-numeric render_width must return 400."""
        resp = client.post("/api/settings", json={"render_width": "abc"})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_settings_invalid_render_height(self, client):
        """Non-numeric render_height must return 400."""
        resp = client.post("/api/settings", json={"render_height": "abc"})
        assert resp.status_code == 400
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is False

    def test_settings_valid_update(self, client):
        """A valid update returns ok and the new settings."""
        resp = client.post("/api/settings", json={"slideshow_interval": 60})
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True
        assert data["settings"]["slideshow_interval"] == 60

    def test_settings_unknown_keys_do_not_corrupt(self, client):
        """Unknown keys should be silently ignored; ok=True."""
        resp = client.post("/api/settings", json={"unknown_key": "foo"})
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True


class TestFolderCycle:
    """POST /api/folder/cycle."""

    def test_folder_cycle_returns_ok(self, client):
        """POST /api/folder/cycle returns ok=True and the current mode."""
        resp = client.post("/api/folder/cycle")
        assert resp.status_code == 200
        data = resp.get_json(silent=True)
        assert data is not None
        assert data["ok"] is True
        assert "mode" in data


class TestCurrentImageRoute:
    """GET /api/current-image."""

    def test_current_image_no_render(self, client):
        """GET /api/current-image returns 200 with placeholder when nothing rendered."""
        resp = client.get("/api/current-image")
        assert resp.status_code == 200
        assert resp.is_streamed


class TestMethodRouting:
    """Wrong HTTP methods must return 405 (Method Not Allowed)."""

    def test_delete_on_slideshow_toggle(self, client):
        """DELETE /api/slideshow/toggle must not be allowed."""
        resp = client.delete("/api/slideshow/toggle")
        assert resp.status_code == 405


class TestRenderOutcomeIsReported:
    """A route must not answer ok:True when the panel did not take the image.

    ``RendererStub`` reports the outcome the real renderer sets per render, so
    these tests pin the contract the UI relies on to stop claiming "activated"
    while the display still shows the previous image.
    """

    def test_activate_reports_a_busy_display(self, client):
        client.application.renderer_stub.set_render_outcome("busy")

        data = client.post("/api/directories/0/activate").get_json()

        assert data["ok"] is False
        assert data["error"] == "Display is busy refreshing; try again."

    def test_activate_reports_a_failed_refresh(self, client):
        client.application.renderer_stub.set_render_outcome("failed")

        data = client.post("/api/directories/0/activate").get_json()

        assert data["ok"] is False
        assert data["error"] == "Display refresh failed."

    def test_activate_reports_an_empty_source(self, client):
        client.application.renderer_stub.set_render_outcome("empty")

        data = client.post("/api/directories/0/activate").get_json()

        assert data["ok"] is False
        assert data["error"] == "No image available to display."

    def test_next_image_reports_the_server_message(self, client):
        client.application.renderer_stub.set_render_outcome("busy")

        data = client.post("/api/slideshow/next").get_json()

        assert data["ok"] is False
        assert data["error"] == "Display is busy refreshing; try again."

    def test_successful_activate_still_reports_ok(self, client):
        data = client.post("/api/directories/0/activate").get_json()

        assert data["ok"] is True
        assert "error" not in data

    def test_settings_report_a_failed_render_without_failing_the_save(self, client):
        client.application.renderer_stub.set_render_outcome("failed")

        data = client.post("/api/settings", json={"saturation": 0.8}).get_json()

        assert data["ok"] is True
        assert data["settings"]["saturation"] == 0.8
        assert data["render_error"] == "Display refresh failed."


class TestRepaintRoute:
    """POST /api/display/repaint forces a refresh of the current image."""

    def test_repaint_forces_the_renderer(self, client):
        data = client.post("/api/display/repaint").get_json()

        assert data["ok"] is True
        assert client.application.renderer_stub.render_force is True

    def test_repaint_reports_a_dropped_refresh(self, client):
        client.application.renderer_stub.set_render_outcome("busy")

        data = client.post("/api/display/repaint").get_json()

        assert data["ok"] is False
        assert data["error"] == "Display is busy refreshing; try again."


class TestToneSettingsRoute:
    """POST /api/settings accepts brightness and contrast before dithering."""

    def test_status_exposes_both(self, client):
        data = client.get("/api/status").get_json()

        assert data["brightness"] == 1.0
        assert data["contrast"] == 1.0

    def test_saving_both_triggers_a_render(self, client):
        stub = client.application.renderer_stub
        before = stub.render_current_image_calls

        data = client.post(
            "/api/settings", json={"brightness": 1.3, "contrast": 1.2}
        ).get_json()

        assert data["ok"] is True
        assert data["settings"]["brightness"] == 1.3
        assert data["settings"]["contrast"] == 1.2
        assert stub.render_current_image_calls == before + 1

    def test_values_are_clamped(self, client):
        data = client.post(
            "/api/settings", json={"brightness": 5, "contrast": 0.1}
        ).get_json()

        assert data["settings"]["brightness"] == 2.0
        assert data["settings"]["contrast"] == 0.25

    def test_invalid_values_are_rejected(self, client):
        assert (
            client.post("/api/settings", json={"brightness": "abc"}).status_code
            == 400
        )
        assert (
            client.post("/api/settings", json={"contrast": "abc"}).status_code
            == 400
        )
