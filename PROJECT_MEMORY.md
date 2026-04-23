# Project Memory - Inky Image Viewer

Date: 2026-02-26

## Current Project Goal

Python image viewer for Inky e-ink display on Raspberry Pi (Debian), with:
- Hardware buttons (A/B/C/D)
- Web UI for directory management
- Slideshow and manual navigation
- Linux service deployment

## Current Behavior (Implemented)

### Buttons
- A: Start/Stop slideshow
- B: Next image
- C: Previous image
- D: Change slideshow mode (`directory` -> `image_list` -> `url` -> `upload`)

### Web UI
- Directory browser with:
	- Filter input
	- Current path display
	- Select list of subdirectories (including `..`)
	- Add current folder button
- Directory list with per-row actions:
	- `Activate` when row is inactive
	- `Deactivate` when row is active
	- `Remove`
- Current image panel:
	- Prev / Toggle / Next / Change Mode / Reshuffle
- Upload mode:
	- Upload image file from browser/mobile
	- Remove uploaded image
	- Clear uploaded image list
- Mode selection behavior:
	- Mode buttons in UI now select view context only (no immediate backend mode switch).
	- New `Activate selected mode` button applies selected mode to backend and triggers render.
	- UI shows active backend mode separately.
- Settings:
	- Slideshow interval (minimum 30s)
	- Saturation
	- Scale to fit
	- Configurable render resolution (`render_width` / `render_height`, default 800x480)
- Busy/feedback badge in UI for actions and long e-ink refreshes

### Rendering & Performance Rules
- E-ink refresh is treated as slow/blocking (30-45s expected).
- New render requests are dropped while display is busy (non-blocking lock).
- Repeated button events are de-queued to avoid backlog.
- UI actions are guarded to prevent spam while action in progress.
- Render deduplication:
	- If image path + saturation + scale_to_fit are identical to last render, skip display refresh.

### Active Directory Model
- `active_directory_index = -1` means "no active directory".
- Adding/removing directories does not auto-activate.
- Deactivating active directory shows `no-image`.
- If no active directory exists, UI preview and device fallback to `static/no-image.jpg`.

### Slideshow Rules
- Minimum interval: 30s (backend + UI enforced).
- Slideshow does not auto-start on service boot.
- Service startup forces `slideshow_running = false`.

## Installation/Service

- Install target: `/home/<user>/inky-image` (not `/opt`)
- Installer: `install.sh`
- Service: `inky-image.service`
- Service unit placeholders are replaced during install:
	- `__INKY_USER__`
	- `__INKY_HOME__`

## Key Files and Responsibilities

- `inky_image/main.py`
	- App orchestration, render lock, dedupe render, no-image behavior
- `inky_image/config.py`
	- Persistent config, active directory model, interval limits
- `inky_image/image_manager.py`
	- Recursive image discovery, shuffle order, active/inactive directory handling
- `inky_image/button_handler.py`
	- GPIO event handling, debounce, backlog drop
- `inky_image/display.py`
	- Inky device render pipeline and scale-to-fit behavior
- `inky_image/web_app.py`
	- API endpoints, browse/deactivate logic, status payload
- `templates/index.html`
	- Main UI and action orchestration
- `static/style.css`
	- UI styles + busy/success/warning badge styles

## API Notes (Current)

- `POST /api/directories`: add directory (no auto-render)
- `DELETE /api/directories/<index>`: remove directory (no auto-render)
- `POST /api/directories/<index>/activate`: activate + render
- `POST /api/directories/<index>/deactivate`: deactivate + render no-image
- `POST /api/slideshow/toggle`
- `POST /api/slideshow/next`
- `POST /api/slideshow/prev`
- `POST /api/folder/cycle`
- `POST /api/slideshow/reshuffle`
- `POST /api/settings`: render only if `saturation` or `scale_to_fit` changed
- `GET /api/current-image`: returns active image, or `no-image.jpg` if no active directory

## Known Operational Notes

- After UI/JS changes, restart service:
	- `sudo systemctl restart inky-image.service`
- Check logs:
	- `sudo journalctl -u inky-image.service -f`
- Placeholder image expected at:
	- `static/no-image.jpg`

## Recommended First Checks Tomorrow

1. Validate Activate/Deactivate flow in UI (button text and action).
2. Validate no auto-render on add/remove directory.
3. Validate no-image fallback when `active_directory_index = -1`.
4. Validate slideshow interval floor at 30s.
5. Validate e-ink busy state drops extra actions as expected.

## Feature Backlog (Captured)

Prioritized proposals to evaluate in next iterations:

1. Scheduled operation windows
	- Enable slideshow only during configured time ranges.
2. Auto-rotation between directories
	- Change active folder every N images or every N minutes.
3. Directory/image exclusion filters
	- Ignore subdirectories or filename patterns.
4. UI state persistence
	- Remember last browsed path and active filter text.
5. Health endpoint + basic metrics
	- Add `/healthz` and counters for render requests/dropped actions.
6. Maintenance mode
	- Temporarily pause UI/buttons without stopping the service.

## In Progress Feature Request

Date: 2026-02-27
Status: implemented (pending runtime validation)

Feature: Mixed slideshow sources (directories + individual images)

User requirement summary:
- Keep current behavior:
	- Slideshow over one active directory (existing flow with A/B/C/D buttons).
- Add new behavior:
	- Build slideshow from individually selected images that can come from different directories.
- Both modes must coexist:
	- Directory mode (existing).
	- Image list mode (new).
- Button behavior in image list mode:
	- A/B/C must continue working.
	- D (change directory) should be disabled/ignored because it does not apply.
- UI/Browser behavior:
	- Existing explorer should show individual files as selectable entries in addition to directories.
	- Depending on selected entry type (directory or image), UI should trigger the corresponding add action.
	- Use existing preview panel to show image before adding it to slideshow list.

Implementation notes (done):
- New config keys:
	- `slideshow_mode` with values: `directory` or `image_list`.
	- `selected_images` list with unique absolute image paths.
- New APIs:
	- `POST /api/mode` to switch mode (resets index to first image).
	- `POST /api/images` add selected image (no duplicates).
	- `DELETE /api/images/<index>` remove selected image.
	- `POST /api/images/clear` clear selected image list.
	- `GET /api/preview-file?path=...` preview any supported image file from browser selection.
- Updated API behavior:
	- `GET /api/directories/browse` now returns mixed `entries` (`directory` + `image`).
	- `POST /api/folder/cycle` returns non-applicable error in `image_list` mode.
- Button behavior:
	- In `image_list` mode, A/B/C keep working.
	- D is disabled in UI and ignored at backend level.
- UI updates:
	- Mode selector.
	- Browser supports selecting either directory or image entries.
	- Add action auto-detects entry type and calls add directory/image endpoint.
	- Selected image list panel with per-item remove and `Clear image list`.
	- Preview panel can show selected image before adding.

Pending manual validation:
1. End-to-end workflow in both modes (`directory` and `image_list`).
2. Confirm no duplicates accepted for selected images.
3. Confirm mode switch starts from first image.
4. Confirm D button/cycle endpoint behavior in `image_list` mode.

Follow-up fix (2026-02-27):
- UI preview behavior adjusted to avoid mismatch while slideshow is running.
- Added two separate preview areas:
	1. Current image preview (tracks `/api/current-image`, intended to mirror e-ink content).
	2. Selected image preview (tracks browser-selected file before adding).
- Removed old single-preview override behavior that could pin UI preview to last selected file.

Follow-up fix (2026-02-27, sync e-ink on empty sources):
- When removing directories, if there is no active directory after deletion, backend now:
	- stops slideshow,
	- updates `slideshow_running=false`,
	- forces `render_current_image()` so e-ink shows `no-image`.
- When removing selected images in `image_list` mode, if image pool becomes empty, backend now:
	- stops slideshow,
	- updates `slideshow_running=false`,
	- forces `render_current_image()` so e-ink shows `no-image`.

Follow-up UI tweak (2026-02-27):
- In `image_list` mode, selected-file preview moved under the file browser in the directories panel.
- In `directory` mode, selected-file preview is hidden to keep current directory workflow unchanged.

Follow-up fix (2026-02-27, preview must reflect real e-ink state):
- Problem: `/api/current-image` used logical current image from source lists, which could change after add/remove without rendering.
- Fix:
	- Store `last_rendered_image_path` in config whenever a render to e-ink succeeds.
	- `GET /api/current-image` now serves this last rendered path (or placeholder if missing).
- Result:
	- Current-image preview now reflects what was actually rendered on e-ink, not just selected/queued state.

Follow-up fix (2026-02-27, next/prev not changing with image_list):
- Root cause:
	- `current_image_index` normalization was directory-oriented and could invalidate image-list navigation state.
- Fixes:
	1. `ConfigManager._sync_indexes()` is now mode-aware:
		- normalizes `active_directory_index` with directories,
		- normalizes `current_image_index` with `selected_images` length in `image_list` mode.
	2. `render_next_image()` and `render_previous_image()` now force render (skip dedupe) because they are explicit user navigation actions.

UI tweak (2026-02-27):
- Busy action badge (e.g. "Loading next image on display...") now appears centered on screen for better visibility.

UI tweak (2026-02-27, settings panel toggle):
- Settings column is now collapsible behind a gear button.
- Default state is collapsed (persisted in browser localStorage).
- When collapsed, main layout redistributes to 2 columns; when expanded, it returns to 3 columns.

## Planned Feature (Next)

Date: 2026-02-27
Status: planned (pending implementation)

Feature: Add third slideshow source mode (`url`) with dynamic UI source selector.

Goal:
- Support three mutually exclusive source modes with clear UX:
	1. `directory`
	2. `image_list`
	3. `url`

UX proposal:
- Add source selector at top of left panel (tabs or segmented control):
	- Directory
	- Image List
	- URL
- Keep center controls unchanged (Prev/Toggle/Next/Cycle/Reshuffle).
- Dynamic left panel content:
	- `directory`: current directory browser workflow.
	- `image_list`: file browser + selected-file preview + selected images list.
	- `url`: URL input + preview + add/remove URL images list.
- Button D behavior:
	- Active only in `directory`.
	- Disabled/ignored in `image_list` and `url`.

Technical direction:
- Extend `slideshow_mode` values to include `url`.
- Add config storage for URL sources (`url_images` list with unique URLs).
- Normalize `current_image_index` by active mode source length.
- For `/api/current-image`, keep using `last_rendered_image_path` to reflect real e-ink state.
- Download/cache URL images locally before rendering (avoid network dependency at render time).

Proposed implementation phases:
1. Backend model/API foundation:
	- Config keys + ImageManager mode handling for `url`.
	- Endpoints for add/remove/clear URL images.
2. URL fetch/cache pipeline:
	- Validate URL + content type/extension.
	- Download to local cache path with deterministic filename.
3. UI dynamic source selector:
	- Add source tabs and contextual panels.
	- URL panel with preview and list management.
4. Runtime behavior hardening:
	- D button restrictions.
	- Empty-source fallback to no-image + slideshow stop.
5. Validation:
	- Manual end-to-end checks for all 3 modes.

Progress update (2026-02-27):
- Phase 1 backend foundation implemented:
	- `slideshow_mode` now supports `url`.
	- New config key: `url_images`.
	- New API endpoints:
		- `POST /api/url-images`
		- `DELETE /api/url-images/<index>`
		- `POST /api/url-images/clear`
	- `POST /api/mode` now accepts `url`.
	- Status payload now includes:
		- `url_images`
		- `url_images_count`
- Current limitation (expected until Phase 2):
	- URL mode does not have dedicated UI controls yet (Phase 3 pending).

Progress update (2026-02-27, Phase 2 done):
- URL fetch/cache pipeline implemented in backend:
	- URL images are downloaded with `urllib` (http/https only).
	- Content type is validated (`image/*` required).
	- Payload size limit enforced (12MB max).
	- Downloaded content is image-verified with Pillow.
	- Files are cached under `~/.cache/inky-image/url-images/` with deterministic hashed names.
- URL mode runtime behavior:
	- `refresh_images()` resolves URL sources to cached local files and can now navigate/render them.
	- If cached file is missing, backend attempts re-download.
	- Removing/clearing URL entries deletes matching cached files.

Progress update (2026-02-27, Phase 3 done):
- Left panel UI is now dynamic by mode:
	- `directory`: shows directory browser + configured directories list.
	- `image_list`: shows browser + selected image preview + selected images list.
	- `url`: shows URL input + URL preview + URL images list.
- Source selector now includes all three modes:
	- `directory`, `image_list`, `url`.
- URL UI actions implemented:
	- Add URL image.
	- Remove URL image (per row).
	- Clear URL image list.
- Runtime controls remain shared; button D stays disabled outside directory mode.

UI polish (2026-02-27):
- Added inline URL validation feedback in URL mode:
	- Neutral, valid, and invalid visual states.
	- `Add URL image` button disabled unless URL is syntactically valid (`http/https`).

UI tweak (2026-02-27):
- Selection preview under file browser is now strictly visible only in `image_list` mode.
- In `directory` mode it is always hidden, regardless of previous selection state.

Pending UI improvement:
- In URL mode, make `Add URL image` and `Clear URL list` buttons stack vertically on small screens for better mobile readability/usability.

UI tweak (2026-02-27):
- Replaced source mode dropdown with 3 mode buttons (`directory`, `image_list`, `url`).
- Active mode now uses highlighted blue border, matching the visual style used for active directory rows.

UI tweak (2026-02-27):
- Added active-row blue highlight for current slideshow item in:
	- selected images list (`image_list` mode),
	- URL images list (`url` mode).

## Session Checkpoint (2026-02-27)

Status summary:
- `directory`, `image_list`, and `url` modes are implemented end-to-end.
- Source mode selector uses 3 buttons (not dropdown), with active blue highlight.
- Current-image preview reflects real e-ink rendered image (`last_rendered_image_path`).
- File-selection preview is shown only in `image_list` mode.
- URL mode supports add/remove/clear + inline URL validation + local cache download pipeline.
- Active item highlight (blue) is available in:
	- directories list (`directory` mode),
	- selected images list (`image_list` mode),
	- URL images list (`url` mode).

Known pending improvements:
- No critical pending improvements tracked in this checkpoint.

Progress update (2026-03-03):
- Pending responsive tweak completed:
	- In URL mode, `Add URL image` and `Clear URL list` now stack vertically on small screens.
- Optional URL preview fallback completed:
	- URL preview now shows a dedicated fallback message when remote images are blocked/unavailable/broken.
- Physical button safety lock completed:
	- New setting `lock_buttons` added to configuration and settings UI.
	- When enabled, hardware buttons A/B/C/D are ignored at backend level.
	- When disabled, hardware buttons work normally.
- Button D behavior updated:
	- Physical D now cycles slideshow mode (`directory` -> `image_list` -> `url` -> `upload`).
	- Center UI control `(D)` now triggers mode cycling (same behavior as physical button).
- Upload mode completed:
	- New slideshow source mode `upload`.
	- Added API endpoints:
		- `POST /api/upload-images` (multipart upload)
		- `DELETE /api/upload-images/<index>`
		- `POST /api/upload-images/clear`
	- Uploaded files are validated as images and saved under local cache.
	- If mode is `upload`, adding an upload triggers immediate render.
- URL and Upload item activation controls completed:
	- URL list rows now include `Activate/Deactivate`, plus `Remove`.
	- Upload list rows now include `Activate/Deactivate`, plus `Remove`.
	- Deactivating active URL/upload item stops slideshow and renders `no-image`.
- List item preview controls completed:
	- `image_list`, `url`, and `upload` rows now include a `Preview` button.
	- Added dedicated list-preview panel in UI to preview an item before activation.
- Preview stability fix completed:
	- Fixed list preview flicker/reload loop caused by periodic status refresh.
	- List preview now refreshes image source only when preview selection changes.
- Configurable render resolution completed:
	- New settings: `render_width` and `render_height` (minimum 64, default 800x480).
	- Resolution is configurable from the Settings panel and persisted in config.
	- Saving resolution triggers re-render of current image.
	- Display pipeline keeps compatibility by adapting configured render size to physical panel size.

Suggested next resume steps:
1. Validate full manual E2E across all 3 modes after a clean service restart.
2. Validate hardware button lock behavior (ON ignores A/B/C/D, OFF restores behavior).
3. Validate manual mode activation UX:
	- Mode buttons should only switch UI context.
	- `Activate selected mode` should apply backend mode and render.
4. Validate row actions in `url` and `upload` lists:
	- `Preview` / `Activate` / `Deactivate` / `Remove` behave consistently.

## Progress update (2026-03-05)

### Backend startup behavior (e-ink performance)
- Service startup no longer forces an immediate render to the e-ink display.
- Change applied in `inky_image/main.py`:
	- Removed startup call to `render_current_image()` from `Application.run()`.
	- Added startup log entry indicating startup render is skipped.
- Result:
	- Restart is much faster (avoids ~30s e-ink repaint on boot).
	- Physical display keeps last already-rendered image after service restart.
	- Rendering still happens on explicit actions (next/prev/mode activate/settings changes/etc.).

### UI modernization rollout completed (Phase 1, 2, 3, 3.1)
- Phase 1 (layout clarity):
	- Added sticky top status bar with system chips (`Active mode`, `Slideshow`, `Buttons`, `UI`).
	- Improved panel hierarchy and primary CTA emphasis (`Activate selected mode`, `Start/Stop`).
- Phase 2 (interaction UX):
	- Added toasts + action status bar for ongoing operations.
	- Simplified per-row action noise using `More` contextual menu in lists.
- Phase 3 (accessibility + theming):
	- Added high-contrast theme with persisted preference (`localStorage`).
	- Added keyboard-friendly focus behavior (`:focus-visible` emphasis).
	- Added outside-click close behavior for row action menus.
- Phase 3.1 (keyboard depth):
	- Command palette supports `ArrowUp/ArrowDown`, `Home/End`, `Enter`, `Esc`.
	- Command rows include visible shortcut badges.
	- Improved high-contrast states for hover/active/disabled controls.

### Final UI cleanup decisions applied
- Removed `Quick actions` button from header (palette remains keyboard-triggered via `Cmd/Ctrl+K`).
- Moved `High contrast` control from header into `Settings` as checkbox (`high-contrast-input`).
- Humanized mode labels in UI status chips/indicators:
	- `directory` -> `Directory`
	- `image_list` -> `Image list`
	- `url` -> `URL`
	- `upload` -> `Upload`
- Removed redundant in-panel mode text (`Selected in UI` and `Active mode`) because top-right chips are clearer.
- Fixed hidden-state regression globally with CSS:
	- Added `[hidden] { display: none !important; }`.
- Repositioned settings gear so it no longer overlaps status chips; aligned to the right of the `UI` chip.

### Current known state
- UI is now stable with modernized styling + keyboard support + accessibility improvements.
- No linter issues were introduced during the above frontend/backend changes.

### Follow-up UI refinements (2026-03-05)
- Source mode selector UX changed to a dual-action card per mode:
	- Left side (`Directory mode`, `Image list mode`, `URL mode`, `Upload mode`) selects UI context only.
	- Right side compact action button activates backend mode directly.
- Removed standalone `Activate selected mode` button.
- Per-mode activation state now shown inline in the source selector:
	- Active mode right-side button uses green style and `On` label.
	- Inactive mode right-side buttons keep blue style and `Set` label.
- Message/feedback copy updated to match new flow (selection no longer references old activate button).
- Settings gear final placement adjusted to the right of top status chips without overlap.
- `Now playing` controls layout improved for readability:
	- Primary row (`Previous`, `Start/Stop`, `Next`) uses 3-column responsive grid.
	- Secondary row (`Cycle mode`, `Reshuffle`) uses 2-column responsive grid.
	- Breakpoints collapse to 2 columns and then 1 column on smaller screens.

## Progress update (2026-03-14)

### Frontend modularization (no bundler)
- Refactor completed to remove large inline script from `templates/index.html`.
- Frontend now loads a single ES module entrypoint:
	- `<script type="module" src="/static/js/main.js"></script>`
- JavaScript split into focused modules under `static/js/`:
	- `main.js` (app bootstrap + event wiring)
	- `api.js` (HTTP helper)
	- `state.js` (UI state + localStorage keys)
	- `modes.js` (mode labels/validation/helpers)
	- `feedback.js` (toasts, busy state, top status, UI disable state)
	- `previews.js` (current/selected/url/list previews)
	- `browser.js` (directory browser/filter/add button state)
	- `palette.js` (command palette state + rendering)

### Behavioral impact
- No intentional UX or API behavior changes; this is a maintainability refactor.
- Existing flows remain intact:
	- Directory/image/url/upload management
	- Slideshow controls and mode activation
	- Preview panels and busy/action feedback
	- Keyboard shortcuts and command palette

### Validation notes
- JS syntax checks passed for all modules with `node --check`.
- Manual runtime check confirmed UI still works after modularization.

## Progress update (2026-03-16)

### Browser keyboard navigation fixes (`image_list` / directory browser)
- Fixed unintended navigation when using keyboard arrows in file browser select (`#browser-directories-select`).
- `ArrowUp/ArrowDown/Home/End/PageUp/PageDown` now only move selection and do not auto-enter directories.
- Added explicit keyboard navigation for folders:
	- `ArrowRight` enters selected directory.
	- `ArrowLeft` goes to parent directory (when available).
	- `Enter` also enters selected directory.
- Added `ondblclick` behavior to enter directory with mouse double click.

### Directory browser stability during auto-refresh
- Fixed list jump/reset caused by periodic `refreshStatus` re-rendering.
- `browser.renderFilteredEntries()` now preserves:
	- previous selected value (when still present),
	- select scroll position (`scrollTop`),
	- `state.browserState.selectedEntry` consistency.
- Result: repeated arrow navigation no longer jumps back to top due to refresh.

### Image list row actions parity with URL/Upload
- `Image list mode` rows now follow same action pattern as URL/Upload:
	- primary button: `Activate` / `Deactivate`,
	- `More` menu: `Preview`, `Remove`.
- Added backend endpoints:
	- `POST /api/images/<int:index>/activate`
	- `POST /api/images/<int:index>/deactivate`
- Added manager methods in `image_manager.py`:
	- `activate_selected_image(index)`
	- `deactivate_selected_image(index)`
- Updated config index normalization for `image_list` to allow `current_image_index = -1` as "no active selected image" (consistent with URL/Upload deactivate behavior).

### Validation notes
- Python syntax check passed after backend changes: `python3 -m compileall inky_image`.
