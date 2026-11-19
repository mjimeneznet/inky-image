# review-hardening

Fix the 11 defects found in the deep code review of inky-image. Branch `fix/review-hardening`.
Ordering is by risk: the installer can destroy data, the render pipeline can lie, the
slideshow can race, and the URL source can freeze the whole API.

## Specs

S1 — Installer/updater must never destroy an unrelated directory.
`install.sh` and `update.sh` refuse a `--target-dir` that is `/`, the target user's home,
`/home`, `/root`, `/usr`, `/usr/local`, `/etc`, `/var`, `/opt`, `/srv`, `/bin`, `/boot`,
`/lib`, `/tmp`, or an ancestor of the checkout; they also refuse a non-empty directory that
is not an existing install (no `inky_image/main.py`). Exact messages:
`Refusing to install into unsafe target directory: <path>` and
`Refusing to overwrite a directory that is not an inky-image install: <path>`.
When the checkout is itself the target dir the sync step is skipped.

S2 — Deployment cannot corrupt the unit file and cannot leave new code with old deps.
Placeholders are substituted with `&`, `|`, `\` escaped. Python dependencies install
*before* project files are replaced, so a failed `pip install` leaves the previous tree
running. The unit orders after the network and gives up on a permanent start failure
instead of restarting forever.

S3 — A route reports what the display actually did.
`ok: true` only when the panel shows the requested image. A dropped or failed render answers
`{"ok": false, "error": "<reason>"}`, with the exact strings
`Display is busy refreshing; try again.` and `Display refresh failed.`

S4 — `SlideshowController.toggle()` is atomic, and `shutdown()` is terminal:
after it, `start()` and `toggle()` cannot spawn a new thread or report running.

S5 — `Application.stop()` does not return while a display refresh is in flight; it waits for
the render lock to drain so the panel is never left half-written.

S6 — `is_render_in_progress()` is true for the whole time the render lock is held, including
the early-return paths and the image refresh it performs.

S7 — No network I/O while `ImageManager._lock` or the render lock is held. URL downloads run
before the locks are taken, so `/api/status` never stalls behind `urlopen(timeout=12)`.

S8 — The 5s status poll never overwrites a settings field the user is editing; the URL add
button keeps the disabled state owned by URL validation; busy/failed text comes from the
server response instead of a hardcoded "Display is busy".

S9 — `requirements-dev.txt` alone is enough to run the full suite (flask, waitress), and the
renderer stub can report a non-ok outcome so the dropped-render contract is testable.

## Tasks

| ID | Specs | Route | Files | Commit |
| --- | --- | --- | --- | --- |
| T1 | S1-S2 | inline | install.sh, update.sh, inky-image.service | 1 |
| T2 | S6 | inline | inky_image/main.py, tests/test_application.py | 2 |
| T3 | S3 | inline | inky_image/main.py, renderer.py, web_app.py, tests | 3 |
| T4 | S4 | inline | inky_image/slideshow.py, tests/test_slideshow.py | 4 |
| T5 | S5 | inline | inky_image/main.py, button_handler.py, tests | 5 |
| T6 | S7 | inline | inky_image/image_manager.py, tests | 6 |
| T7 | S8 | inline | static/js/main.js, static/js/feedback.js | 7 |
| T8 | S9 | inline | requirements-dev.txt, tests/conftest.py, .github/workflows/ci.yml | 8 |

## Log

L1: arregla todo
L2: Context — the review reported, in severity order: rsync --delete data loss in
install.sh:85/update.sh:112; urlopen(timeout=12) under ImageManager._lock reached from the
render path; routes discarding render_current_image()'s bool; non-atomic toggle() plus a
resurrectable slideshow; shutdown killing an in-flight panel refresh; the render_in_progress
window; the status poll clobbering the settings form; sed without escaping plus no rollback
in the deploy scripts; unit-file crash loop; feedback.js re-enabling the URL button; and test
gaps (main/slideshow/renderer/display untested, RendererStub always True, CI missing flask).

L3: Slice boundary — commits 1-3 (12ac5e2 deploy safety, 9cdcd21 render flag,
and the render-outcome commit) are review slice 1 (~400 authored lines).
Further commits form slice 2. Push/PR shape is the user's decision.
