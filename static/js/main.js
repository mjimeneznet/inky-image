import { api } from "./api.js";
import { createBrowser } from "./browser.js";
import { createFeedback } from "./feedback.js";
import { formatModeLabel, getActiveMode, setModeButtons, VALID_MODES } from "./modes.js";
import { createCommandPalette } from "./palette.js";
import { createPreviews } from "./previews.js";
import { CONTRAST_STORAGE_KEY, createState, SETTINGS_STORAGE_KEY } from "./state.js";

const state = createState();

const feedback = createFeedback({
	formatModeLabel,
	contrastStorageKey: CONTRAST_STORAGE_KEY,
});

const previews = createPreviews({
	state,
	getActiveMode: () => getActiveMode(state),
});

const browser = createBrowser({
	state,
	api,
	getActiveMode: () => getActiveMode(state),
	previews,
	showMessage: feedback.showMessage,
});

const palette = createCommandPalette({
	setContrastEnabled: feedback.setContrastEnabled,
});

async function runUiAction(actionFn, options = {}) {
	if (state.uiActionInProgress) {
		feedback.showMessage("Display is refreshing. Wait until current action finishes.");
		feedback.showBadge("Display busy: action ignored", "warning");
		return null;
	}
	const startMessage = options.startMessage || "Display is refreshing...";
	state.uiActionInProgress = true;
	feedback.setUiButtonsDisabled(true);
	feedback.setTopUiState("busy");
	feedback.showMessage(startMessage);
	feedback.showBusyBadge(startMessage);
	try {
		return await actionFn();
	} catch (error) {
		feedback.showMessage(error.message);
		feedback.showBadge(error.message, "warning");
		return null;
	} finally {
		state.uiActionInProgress = false;
		const stillRendering = state.latestStatus && state.latestStatus.render_in_progress;
		if (!stillRendering) {
			feedback.setUiButtonsDisabled(false);
			feedback.hideBusyBadge();
		}
		feedback.setTopUiState("ready");
		applyModeUiState(state.latestStatus || {});
		browser.updateAddButtonState();
	}
}

async function activateMode(mode) {
	const normalized = VALID_MODES.includes(mode) ? mode : "directory";
	await runUiAction(
		async () => {
			await api("/api/mode", {
				method: "POST",
				body: JSON.stringify({ mode: normalized }),
			});
			feedback.showBadge(`Mode activated: ${formatModeLabel(normalized)}`, "success");
			await refreshStatus();
		},
		{ startMessage: `Activating ${formatModeLabel(normalized)} mode and refreshing display...` }
	);
}

function renderListItems(list, items) {
	list.innerHTML = "";
	items.forEach((item) => {
		const li = document.createElement("li");
		li.className = "dir-item";
		if (item.isActive) {
			li.classList.add("active");
		}

		const name = document.createElement("span");
		name.textContent = item.label;
		li.appendChild(name);

		const actions = document.createElement("div");
		actions.className = "actions-group";

		const toggleBtn = document.createElement("button");
		toggleBtn.className = "icon-btn";
		toggleBtn.title = item.isActive ? "Deactivate" : "Activate";
		toggleBtn.innerHTML = "<i data-lucide='" + (item.isActive ? "power-off" : "power") + "'></i>";
		toggleBtn.onclick = item.isActive ? item.onDeactivate : item.onActivate;
		actions.appendChild(toggleBtn);

		if (item.onPreview) {
			const previewBtn = document.createElement("button");
			previewBtn.className = "icon-btn";
			previewBtn.title = "Preview";
			previewBtn.innerHTML = "<i data-lucide='eye'></i>";
			previewBtn.onclick = item.onPreview;
			actions.appendChild(previewBtn);
		}

		if (item.onMoveUp) {
			const upBtn = document.createElement("button");
			upBtn.className = "icon-btn";
			upBtn.title = "Move up";
			upBtn.innerHTML = "<i data-lucide='arrow-up'></i>";
			upBtn.onclick = item.onMoveUp;
			actions.appendChild(upBtn);
		}

		if (item.onMoveDown) {
			const downBtn = document.createElement("button");
			downBtn.className = "icon-btn";
			downBtn.title = "Move down";
			downBtn.innerHTML = "<i data-lucide='arrow-down'></i>";
			downBtn.onclick = item.onMoveDown;
			actions.appendChild(downBtn);
		}

		const removeBtn = document.createElement("button");
		removeBtn.className = "icon-btn";
		removeBtn.title = "Remove";
		removeBtn.innerHTML = "<i data-lucide='trash'></i>";
		removeBtn.onclick = item.onRemove;
		actions.appendChild(removeBtn);

		li.appendChild(actions);
		list.appendChild(li);
	});
	lucide.createIcons();
}

function renderDirectories(status) {
	const items = (status.directories || []).map((path, index) => {
		const isActive = index === status.active_directory_index;
		return {
			label: path,
			isActive,
			onActivate: async () => {
				await runUiAction(
					async () => {
						await api(`/api/directories/${index}/activate`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Activating directory and refreshing display..." }
				);
			},
			onDeactivate: async () => {
				await runUiAction(
					async () => {
						await api(`/api/directories/${index}/deactivate`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Deactivating directory and showing no-image..." }
				);
			},
			onRemove: async () => {
				await runUiAction(
					async () => {
						await api(`/api/directories/${index}`, { method: "DELETE" });
						await refreshStatus();
					},
					{ startMessage: "Removing directory..." }
				);
			},
		};
	});
	renderListItems(document.getElementById("directories-list"), items);
}

function renderSelectedImages(status) {
	const list = document.getElementById("selected-images-list");
	const hasActiveImage = status.mode === "image_list" && Number(status.current_image_index ?? -1) >= 0;
	const items = (status.selected_images || []).map((path, index) => {
		const isActive = hasActiveImage && index === Number(status.current_image_index ?? -1);
		return {
			label: path,
			isActive,
			onPreview: () => {
				previews.setListPreview("image_list", "local", path);
			},
			onActivate: async () => {
				await runUiAction(
					async () => {
						await api(`/api/images/${index}/activate`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Activating selected image and refreshing display..." }
				);
			},
			onDeactivate: async () => {
				await runUiAction(
					async () => {
						await api(`/api/images/${index}/deactivate`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Deactivating selected image and showing no-image..." }
				);
			},
			onMoveUp: async () => {
				await runUiAction(
					async () => {
						await api(`/api/images/${index}/move-up`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Moving image up..." }
				);
			},
			onMoveDown: async () => {
				await runUiAction(
					async () => {
						await api(`/api/images/${index}/move-down`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Moving image down..." }
				);
			},
			onRemove: async () => {
				await runUiAction(
					async () => {
						await api(`/api/images/${index}`, { method: "DELETE" });
						await refreshStatus();
					},
					{ startMessage: "Removing selected image..." }
				);
			},
		};
	});
	renderListItems(list, items);
}

function renderUrlImages(status) {
	const list = document.getElementById("url-images-list");
	const hasActiveImage = status.mode === "url" && Number(status.url_active_index || -1) >= 0;
	const items = (status.url_images || []).map((url, index) => {
		const isActive = hasActiveImage && index === Number(status.url_active_index || -1);
		return {
			label: url,
			isActive,
			onPreview: () => {
				previews.setListPreview("url", "remote", url);
			},
			onActivate: async () => {
				await runUiAction(
					async () => {
						await api(`/api/url-images/${index}/activate`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Activating URL image and refreshing display..." }
				);
			},
			onDeactivate: async () => {
				await runUiAction(
					async () => {
						await api(`/api/url-images/${index}/deactivate`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Deactivating URL image and showing no-image..." }
				);
			},
			onRemove: async () => {
				await runUiAction(
					async () => {
						await api(`/api/url-images/${index}`, { method: "DELETE" });
						await refreshStatus();
					},
					{ startMessage: "Removing URL image..." }
				);
			},
		};
	});
	renderListItems(list, items);
}

function renderUploadImages(status) {
	const list = document.getElementById("upload-images-list");
	const hasActiveImage = status.mode === "upload" && Number(status.upload_active_index || -1) >= 0;
	const items = (status.uploaded_images || []).map((path, index) => {
		const isActive = hasActiveImage && index === Number(status.upload_active_index || -1);
		return {
			label: path,
			isActive,
			onPreview: () => {
				previews.setListPreview("upload", "local", path);
			},
			onActivate: async () => {
				await runUiAction(
					async () => {
						await api(`/api/upload-images/${index}/activate`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Activating uploaded image and refreshing display..." }
				);
			},
			onDeactivate: async () => {
				await runUiAction(
					async () => {
						await api(`/api/upload-images/${index}/deactivate`, { method: "POST" });
						await refreshStatus();
					},
					{ startMessage: "Deactivating uploaded image and showing no-image..." }
				);
			},
			onRemove: async () => {
				await runUiAction(
					async () => {
						await api(`/api/upload-images/${index}`, { method: "DELETE" });
						await refreshStatus();
					},
					{ startMessage: "Removing uploaded image..." }
				);
			},
		};
	});
	renderListItems(list, items);
}

function applyModeUiState(status) {
	const mode = getActiveMode(state);
	const activeMode = String(status.mode || "directory");
	const isDirectoryMode = mode === "directory";
	const isImageListMode = mode === "image_list";
	const isUrlMode = mode === "url";
	const isUploadMode = mode === "upload";
	const cycleButton = document.getElementById("cycle-button");
	const selectionPreview = document.getElementById("selection-preview-wrapper");
	const browserPanel = document.getElementById("browser-mode-panel");
	const directoriesSection = document.getElementById("directories-section");
	const selectedImagesSection = document.getElementById("selected-images-section");
	const urlPanel = document.getElementById("url-mode-panel");
	const uploadPanel = document.getElementById("upload-mode-panel");

	cycleButton.disabled = state.uiActionInProgress;
	cycleButton.title = "Cycle slideshow mode (directory -> image_list -> url -> upload)";
	document.querySelectorAll(".mode-activate-button").forEach((button) => {
		const isActiveMode = button.dataset.mode === activeMode;
		button.classList.toggle("active-mode", isActiveMode);
		button.textContent = isActiveMode ? "On" : "Set";
		button.title = isActiveMode
			? `${formatModeLabel(activeMode)} mode is active`
			: `Activate ${formatModeLabel(button.dataset.mode || "directory")} mode`;
	});

	browserPanel.hidden = isUrlMode || isUploadMode;
	directoriesSection.hidden = !isDirectoryMode;
	selectedImagesSection.hidden = !isImageListMode;
	urlPanel.hidden = !isUrlMode;
	uploadPanel.hidden = !isUploadMode;

	if (!isImageListMode) {
		state.selectedPreviewPath = null;
		previews.refreshSelectedPreviewImage();
		selectionPreview.hidden = true;
	}
	if (!isUrlMode) {
		document.getElementById("url-image-input").value = "";
		state.urlPreviewPath = "";
		previews.setUrlValidationState("neutral", "Enter a valid http/https image URL.");
		previews.refreshUrlPreviewImage();
	}
	if (!isUploadMode) {
		document.getElementById("upload-image-input").value = "";
	}
	if (state.listPreviewMode && state.listPreviewMode !== mode) {
		previews.clearListPreview();
	}
	previews.refreshListPreviewImage();
	if (isUrlMode && !String(document.getElementById("url-image-input").value || "").trim()) {
		previews.setUrlValidationState("neutral", "Enter a valid http/https image URL.");
	}
	browser.renderFilteredEntries();
	browser.updateAddButtonState();
	lucide.createIcons();
}

// The 5s poll must never overwrite a field the user is editing: a partially
// typed interval would silently revert mid-entry.
function syncField(id, value, prop) {
	const element = document.getElementById(id);
	if (
		!element ||
		element === document.activeElement ||
		state.dirtySettings.has(id)
	) {
		return;
	}
	if (prop === "checked") {
		element.checked = Boolean(value);
		return;
	}
	const next = String(value);
	if (element.value !== next) {
		element.value = next;
	}
}

// A setting input that is empty or half typed must never be saved: Number("") is 0,
// which would store saturation 0 and render a washed out image, and an empty
// size field would store 64 and upscale a thumbnail to the panel.
function numberField(id, min, max) {
	const element = document.getElementById(id);
	if (!element) {
		return null;
	}
	const raw = String(element.value || "").trim();
	if (!raw) {
		return null;
	}
	const value = Number(raw);
	if (!Number.isFinite(value)) {
		return null;
	}
	return Math.min(max, Math.max(min, value));
}

async function refreshStatus() {
	try {
		const status = await api("/api/status");
		state.latestStatus = status;
		renderDirectories(status);
		renderSelectedImages(status);
		renderUrlImages(status);
		renderUploadImages(status);
		document.getElementById("current-image-name").textContent = status.current_image_name || "No image available";
		syncField("interval-input", status.slideshow_interval);
		syncField("saturation-input", status.saturation);
		syncField("brightness-input", status.brightness);
		syncField("contrast-input", status.contrast);
		syncField("render-mode-input", status.render_mode || "default");
		syncField("panel-palette-input", status.panel_palette || "driver");
		syncField("panel-palette-custom-input", status.panel_palette_custom || "");
		applyRenderModeDependencies();
		syncField("scale-to-fit-input", status.scale_to_fit, "checked");
		syncField("lock-buttons-input", status.lock_buttons, "checked");
		syncField("high-contrast-input", document.body.classList.contains("high-contrast"), "checked");
		syncField("render-width-input", Number(status.render_width || 800));
		syncField("render-height-input", Number(status.render_height || 480));
		if (!state.uiModeInitialized) {
			setModeButtons(status.mode || "directory", state);
			state.uiModeInitialized = true;
		}
		document.getElementById("status-output").textContent = JSON.stringify(status, null, 2);
		const toggleBtn = document.getElementById("toggle-button");
		if (toggleBtn) {
			const isRunning = Boolean(status.slideshow_running);
			toggleBtn.title = isRunning ? "Stop slideshow (A)" : "Start slideshow (A)";
			toggleBtn.innerHTML = "<i data-lucide='" + (isRunning ? "pause" : "play") + "'></i>";
		}
		lucide.createIcons();
		if (status.last_action && status.last_action.ts !== state.lastActionTs) {
			state.lastActionTs = status.last_action.ts;
			const labels = { A: "Slideshow toggled", B: "Next image", C: "Previous image", D: "Mode cycled" };
			feedback.showToast(labels[status.last_action.action] || "Button " + status.last_action.action, "info", 3000);
		}
		if (status.render_in_progress) {
			feedback.showBusyBadge("Display is refreshing...");
			if (!state.uiActionInProgress) {
				feedback.setUiButtonsDisabled(true);
			}
		} else {
			feedback.hideBusyBadge();
			if (!state.uiActionInProgress) {
				feedback.setUiButtonsDisabled(false);
			}
		}
		feedback.updateTopStatus(status);
		applyModeUiState(status);
		previews.refreshPreviewImage();
		if (status.scan_error) {
			feedback.showMessage(status.scan_error);
		}
	} catch (error) {
		feedback.showMessage(error.message);
	}
}

function bindSourceActions() {
	document.getElementById("add-directory-button").onclick = async () => {
		await runUiAction(async () => {
			const mode = getActiveMode(state);
			if (mode === "directory") {
				const folderPath = String(state.browserState.currentPath || "").trim();
				if (!folderPath) {
					feedback.showMessage("No current folder selected.");
					return;
				}
				await api("/api/directories", {
					method: "POST",
					body: JSON.stringify({ path: folderPath }),
				});
				feedback.showMessage("Directory added successfully.");
				feedback.showBadge("Directory added", "success");
				await refreshStatus();
				return;
			}
			const entry = state.browserState.selectedEntry;
			if (!entry || entry.type !== "image") {
				feedback.showMessage("Select an image entry first.");
				return;
			}
			await api("/api/images", {
				method: "POST",
				body: JSON.stringify({ path: entry.path }),
			});
			feedback.showMessage("Image added successfully.");
			feedback.showBadge("Image added", "success");
			await refreshStatus();
		}, { startMessage: "Adding selected entry..." });
	};

	document.getElementById("add-url-image-button").onclick = async () => {
		await runUiAction(async () => {
			const rawUrl = String(document.getElementById("url-image-input").value || "").trim();
			if (!rawUrl) {
				feedback.showMessage("Enter an image URL first.");
				return;
			}
			await api("/api/url-images", {
				method: "POST",
				body: JSON.stringify({ url: rawUrl }),
			});
			feedback.showMessage("URL image added successfully.");
			feedback.showBadge("URL image added", "success");
			await refreshStatus();
		}, { startMessage: "Adding URL image..." });
	};

	document.getElementById("clear-url-images-button").onclick = async () => {
		await runUiAction(async () => {
			await api("/api/url-images/clear", { method: "POST" });
			state.urlPreviewPath = "";
			previews.refreshUrlPreviewImage();
			feedback.showBadge("URL image list cleared", "success");
			await refreshStatus();
		}, { startMessage: "Clearing URL image list..." });
	};

	document.getElementById("add-upload-image-button").onclick = async () => {
		await runUiAction(async () => {
			const input = document.getElementById("upload-image-input");
			const file = input.files && input.files[0];
			if (!file) {
				feedback.showMessage("Select an image file first.");
				return;
			}
			const formData = new FormData();
			formData.append("image", file);
			const response = await fetch("/api/upload-images", {
				method: "POST",
				body: formData,
			});
			if (!response.ok) {
				const error = await response.json().catch(() => ({ error: "Upload failed" }));
				throw new Error(error.error || "Upload failed");
			}
			input.value = "";
			feedback.showBadge("Uploaded image added", "success");
			await refreshStatus();
		}, { startMessage: "Uploading image..." });
	};

	document.getElementById("clear-upload-images-button").onclick = async () => {
		await runUiAction(async () => {
			await api("/api/upload-images/clear", { method: "POST" });
			document.getElementById("upload-image-input").value = "";
			feedback.showBadge("Uploaded image list cleared", "success");
			await refreshStatus();
		}, { startMessage: "Clearing uploaded images..." });
	};

	document.getElementById("clear-images-button").onclick = async () => {
		await runUiAction(async () => {
			await api("/api/images/clear", { method: "POST" });
			state.selectedPreviewPath = null;
			previews.refreshSelectedPreviewImage();
			feedback.showBadge("Image list cleared", "success");
			await refreshStatus();
		}, { startMessage: "Clearing selected image list..." });
	};
}

function bindModeButtons() {
	document.querySelectorAll(".mode-button").forEach((button) => {
		button.onclick = () => {
			const mode = button.dataset.mode || "directory";
			if (mode === getActiveMode(state)) {
				return;
			}
			setModeButtons(mode, state);
			state.selectedPreviewPath = null;
			previews.refreshSelectedPreviewImage();
			applyModeUiState(state.latestStatus || {});
			feedback.showMessage(`UI mode selected: ${formatModeLabel(mode)}.`);
			feedback.showBadge(`Mode selected: ${formatModeLabel(mode)}`, "info");
		};
	});

	document.querySelectorAll(".mode-activate-button").forEach((button) => {
		button.onclick = async () => {
			const mode = button.dataset.mode || "directory";
			await activateMode(mode);
		};
	});
}

function bindDisplayControls() {
	document.getElementById("toggle-button").onclick = async () => {
		await runUiAction(async () => {
			await api("/api/slideshow/toggle", { method: "POST" });
			await refreshStatus();
		}, { startMessage: "Updating slideshow state..." });
	};

	document.getElementById("next-button").onclick = async () => {
		await runUiAction(async () => {
			const result = await api("/api/slideshow/next", { method: "POST" });
			if (result.ok === false) {
				feedback.showMessage("Display is busy, next action ignored.");
				feedback.showBadge("Display busy: next ignored", "warning");
			}
			await refreshStatus();
		}, { startMessage: "Loading next image on display..." });
	};

	document.getElementById("prev-button").onclick = async () => {
		await runUiAction(async () => {
			const result = await api("/api/slideshow/prev", { method: "POST" });
			if (result.ok === false) {
				feedback.showMessage("Display is busy, previous action ignored.");
				feedback.showBadge("Display busy: previous ignored", "warning");
			}
			await refreshStatus();
		}, { startMessage: "Loading previous image on display..." });
	};

	document.getElementById("cycle-button").onclick = async () => {
		await runUiAction(async () => {
			const result = await api("/api/folder/cycle", { method: "POST" });
			if (result.ok === false) {
				feedback.showMessage("Display is busy, mode change ignored.");
				feedback.showBadge("Display busy: mode change ignored", "warning");
			} else {
				const mode = String(result.mode || "");
				if (mode) {
					feedback.showMessage(`Mode changed to ${mode}.`);
					feedback.showBadge(`Mode changed: ${mode}`, "success");
				}
			}
			await refreshStatus();
		}, { startMessage: "Changing mode and refreshing display..." });
	};

	document.getElementById("reshuffle-button").onclick = async () => {
		await runUiAction(async () => {
			const result = await api("/api/slideshow/reshuffle", { method: "POST" });
			if (result.ok === false) {
				feedback.showMessage("Display is busy, reshuffle ignored.");
				feedback.showBadge("Display busy: reshuffle ignored", "warning");
			} else {
				feedback.showMessage("Slideshow order reshuffled.");
				feedback.showBadge("Slideshow reshuffled", "success");
			}
			await refreshStatus();
		}, { startMessage: "Reshuffling slideshow and refreshing display..." });
	};
}

// The three controls form a chain: the strategy decides who dithers, the
// palette only matters to the custom strategies, and the hex list only to the
// Custom palette. Saturation belongs to Default, which is the driver's blend.
function markSettingsDirty(event) {
	const id = event && event.target && event.target.id;
	if (id) {
		state.dirtySettings.add(id);
	}
}

function applyRenderModeDependencies() {
	const modeSelect = document.getElementById("render-mode-input");
	const paletteSelect = document.getElementById("panel-palette-input");
	const customInput = document.getElementById("panel-palette-custom-input");
	const saturationInput = document.getElementById("saturation-input");
	if (!modeSelect || !paletteSelect || !customInput || !saturationInput) {
		return;
	}
	const customStrategy = modeSelect.value !== "default";
	paletteSelect.disabled = !customStrategy;
	customInput.disabled = !customStrategy || paletteSelect.value !== "custom";
	saturationInput.disabled = customStrategy;
	saturationInput.title = customStrategy
		? "Only used by Default, which blends the driver palettes. The custom strategies match the palette above."
		: "";
}

function readSettingsForm() {
	const settings = {
		scale_to_fit: document.getElementById("scale-to-fit-input").checked,
		lock_buttons: document.getElementById("lock-buttons-input").checked,
		render_mode: document.getElementById("render-mode-input").value || "default",
		panel_palette: document.getElementById("panel-palette-input").value || "driver",
	};
	const customPalette = String(
		document.getElementById("panel-palette-custom-input").value || ""
	).trim();
	if (customPalette) {
		settings.panel_palette_custom = customPalette;
	}
	const interval = numberField("interval-input", 30, 86400);
	const saturation = numberField("saturation-input", 0, 1);
	const brightness = numberField("brightness-input", 0.25, 2);
	const contrast = numberField("contrast-input", 0.25, 2);
	const renderWidth = numberField("render-width-input", 64, 10000);
	const renderHeight = numberField("render-height-input", 64, 10000);
	if (interval !== null) {
		settings.slideshow_interval = interval;
	}
	if (saturation !== null) {
		settings.saturation = saturation;
	}
	if (brightness !== null) {
		settings.brightness = brightness;
	}
	if (contrast !== null) {
		settings.contrast = contrast;
	}
	if (renderWidth !== null) {
		settings.render_width = renderWidth;
	}
	if (renderHeight !== null) {
		settings.render_height = renderHeight;
	}
	return settings;
}

async function refreshPanelPreview() {
	const image = document.getElementById("panel-preview");
	if (!image) {
		return;
	}
	const status = document.getElementById("panel-preview-status");
	// Preview the values in the form, saved or not, so you can tune before saving.
	const settings = readSettingsForm();
	const params = new URLSearchParams();
	for (const key of ["saturation", "brightness", "contrast", "render_width", "render_height"]) {
		if (settings[key] !== undefined) {
			params.set(key, settings[key]);
		}
	}
	params.set("scale_to_fit", settings.scale_to_fit ? "1" : "0");
	params.set("render_mode", settings.render_mode);
	params.set("panel_palette", settings.panel_palette);
	if (settings.panel_palette_custom) {
		params.set("panel_palette_custom", settings.panel_palette_custom);
	}
	params.set("t", Date.now());

	if (status) {
		status.textContent = "";
	}
	feedback.showBusyBadge("Building panel preview...");
	try {
		const response = await fetch(`/api/debug/rendered-preview?${params.toString()}`, { cache: "no-store" });
		if (!response.ok) {
			const body = await response.json().catch(() => ({}));
			const message = body.error || `Preview unavailable (${response.status}).`;
			if (status) {
				status.textContent = message;
			}
			feedback.showMessage(message);
			return;
		}
		const blob = await response.blob();
		if (image.dataset.objectUrl) {
			URL.revokeObjectURL(image.dataset.objectUrl);
		}
		const url = URL.createObjectURL(blob);
		image.dataset.objectUrl = url;
		image.src = url;
	} catch (error) {
		if (status) {
			status.textContent = "Preview request failed.";
		}
		feedback.showMessage("Preview request failed.");
	} finally {
		feedback.hideBusyBadge();
	}
}

function bindSettingsForm() {
	const settingsPanel = document.getElementById("settings-panel");
	if (settingsPanel) {
		settingsPanel.addEventListener("input", markSettingsDirty);
		settingsPanel.addEventListener("change", markSettingsDirty);
	}
	document.getElementById("refresh-preview-button").onclick = () => {
		refreshPanelPreview();
	};
	document.getElementById("render-mode-input").onchange = () => {
		applyRenderModeDependencies();
	};
	document.getElementById("panel-palette-input").onchange = () => {
		applyRenderModeDependencies();
	};
	applyRenderModeDependencies();
	document.getElementById("save-settings-button").onclick = async () => {
		await runUiAction(async () => {
			const settings = readSettingsForm();
			const result = await api("/api/settings", {
				method: "POST",
				body: JSON.stringify(settings),
			});
			if (result && result.render_error) {
				feedback.showMessage(`Settings saved, but the display did not refresh: ${result.render_error}`);
				feedback.showBadge("Settings saved; display not refreshed", "warning");
			} else {
				feedback.showBadge("Settings saved", "success");
			}
			// The server now holds exactly what the form showed, so the poll can
			// take over again without undoing anything.
			state.dirtySettings.clear();
			applyRenderModeDependencies();
			refreshPanelPreview();
			await refreshStatus();
		}, { startMessage: "Saving settings..." });
	};

	document.getElementById("settings-toggle").onclick = () => {
		document.body.classList.toggle("settings-collapsed");
		const collapsed = document.body.classList.contains("settings-collapsed");
		localStorage.setItem(SETTINGS_STORAGE_KEY, collapsed ? "1" : "0");
		feedback.applySettingsPanelState();
	};

	document.getElementById("high-contrast-input").onchange = (event) => {
		feedback.setContrastEnabled(Boolean(event.target.checked));
	};
}

function bindEvents() {
	browser.bindDomEvents();
	previews.bindDomEvents();
	palette.bindDomEvents();

	bindSourceActions();
	bindModeButtons();
	bindDisplayControls();
	bindSettingsForm();
}

function buildCommandPaletteCommands() {
	const selectUiMode = (mode) => {
		setModeButtons(mode, state);
		state.selectedPreviewPath = null;
		previews.refreshSelectedPreviewImage();
		applyModeUiState(state.latestStatus || {});
		feedback.showMessage(`UI mode selected: ${formatModeLabel(mode)}.`);
		feedback.showToast(`Mode selected: ${formatModeLabel(mode)}`, "info");
	};

	palette.setCommands([
		{
			label: "Toggle slideshow",
			shortcut: "A",
			keywords: "start stop play pause",
			run: () => document.getElementById("toggle-button").click(),
		},
		{
			label: "Next image",
			shortcut: "B",
			keywords: "next forward",
			run: () => document.getElementById("next-button").click(),
		},
		{
			label: "Previous image",
			shortcut: "C",
			keywords: "prev previous back",
			run: () => document.getElementById("prev-button").click(),
		},
		{
			label: "Reshuffle slideshow",
			shortcut: "R",
			keywords: "shuffle reshuffle",
			run: () => document.getElementById("reshuffle-button").click(),
		},
		{
			label: "Cycle mode",
			shortcut: "D",
			keywords: "cycle mode d button",
			run: () => document.getElementById("cycle-button").click(),
		},
		{
			label: "Activate selected mode",
			shortcut: "Enter",
			keywords: "activate selected mode apply",
			run: () => activateMode(getActiveMode(state)),
		},
		{
			label: "Switch UI mode: directory",
			shortcut: "1",
			keywords: "mode directory",
			run: () => selectUiMode("directory"),
		},
		{
			label: "Switch UI mode: image list",
			shortcut: "2",
			keywords: "mode image_list image list",
			run: () => selectUiMode("image_list"),
		},
		{
			label: "Switch UI mode: url",
			shortcut: "3",
			keywords: "mode url",
			run: () => selectUiMode("url"),
		},
		{
			label: "Switch UI mode: upload",
			shortcut: "4",
			keywords: "mode upload",
			run: () => selectUiMode("upload"),
		},
		{
			label: "Save settings",
			shortcut: "S",
			keywords: "settings save",
			run: () => document.getElementById("save-settings-button").click(),
		},
		{
			label: "Refresh status",
			shortcut: "F5",
			keywords: "refresh reload",
			run: () => refreshStatus(),
		},
	]);
}

function initPersistentUiState() {
	const persistedSettingsCollapsed = localStorage.getItem(SETTINGS_STORAGE_KEY);
	if (persistedSettingsCollapsed === null || persistedSettingsCollapsed === "1") {
		document.body.classList.add("settings-collapsed");
	}
	const persistedHighContrast = localStorage.getItem(CONTRAST_STORAGE_KEY);
	if (persistedHighContrast === "1") {
		document.body.classList.add("high-contrast");
	}
	feedback.applySettingsPanelState();
	feedback.applyContrastModeState();
}

function start() {
	initPersistentUiState();
	bindEvents();
	buildCommandPaletteCommands();
	browser.loadDirectoryBrowser();
	refreshStatus();
	setInterval(refreshStatus, 5000);
}

start();
