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
	showToast: feedback.showToast,
});

const palette = createCommandPalette();

async function runUiAction(actionFn, options = {}) {
	if (state.uiActionInProgress) {
		feedback.showToast("Display busy: action ignored", "warning");
		return null;
	}
	const startMessage = options.startMessage || "Display is refreshing...";
	state.uiActionInProgress = true;
	feedback.setUiButtonsDisabled(true);
	feedback.setActionStatus(startMessage, true);
	try {
		return await actionFn();
	} catch (error) {
		feedback.showToast(error.message, "warning");
		return null;
	} finally {
		state.uiActionInProgress = false;
		feedback.setUiButtonsDisabled(false);
		feedback.setActionStatus("Ready", false);
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
			feedback.showToast(`Mode activated: ${formatModeLabel(normalized)}`, "success");
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
		actions.className = "row";

		const activate = document.createElement("button");
		activate.textContent = item.isActive ? "Deactivate" : "Activate";
		activate.onclick = item.isActive ? item.onDeactivate : item.onActivate;
		actions.appendChild(activate);

		const menu = document.createElement("details");
		menu.className = "row-actions-menu";
		const menuSummary = document.createElement("summary");
		menuSummary.textContent = "More";
		const menuBody = document.createElement("div");
		menuBody.className = "row actions-popover";
		if (item.onPreview) {
			const preview = document.createElement("button");
			preview.textContent = "Preview";
			preview.onclick = item.onPreview;
			menuBody.appendChild(preview);
		}
		const remove = document.createElement("button");
		remove.textContent = "Remove";
		remove.onclick = item.onRemove;
		menuBody.appendChild(remove);
		menu.appendChild(menuSummary);
		menu.appendChild(menuBody);
		actions.appendChild(menu);

		li.appendChild(actions);
		list.appendChild(li);
	});
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
		document.getElementById("interval-input").value = status.slideshow_interval;
		document.getElementById("saturation-input").value = status.saturation;
		document.getElementById("scale-to-fit-input").checked = Boolean(status.scale_to_fit);
		document.getElementById("lock-buttons-input").checked = Boolean(status.lock_buttons);
		document.getElementById("high-contrast-input").checked = document.body.classList.contains("high-contrast");
		document.getElementById("render-width-input").value = Number(status.render_width || 800);
		document.getElementById("render-height-input").value = Number(status.render_height || 480);
		if (!state.uiModeInitialized) {
			setModeButtons(status.mode || "directory", state);
			state.uiModeInitialized = true;
		}
		document.getElementById("toggle-button").textContent = status.slideshow_running
			? "Stop slideshow (A)"
			: "Start slideshow (A)";
		feedback.updateTopStatus(status);
		applyModeUiState(status);
		previews.refreshPreviewImage();
		if (status.scan_error) {
			feedback.showToast(status.scan_error, "warning");
		}
	} catch (error) {
		feedback.showToast(error.message, "warning");
	}
}

function bindEvents() {
	let browserSelectionByNavigationKey = false;

	document.getElementById("add-directory-button").onclick = async () => {
		await runUiAction(async () => {
			const mode = getActiveMode(state);
			if (mode === "directory") {
				const folderPath = String(state.browserState.currentPath || "").trim();
				if (!folderPath) {
					feedback.showToast("No current folder selected.", "warning");
					return;
				}
				await api("/api/directories", {
					method: "POST",
					body: JSON.stringify({ path: folderPath }),
				});
				feedback.showToast("Directory added", "success");
				
				await refreshStatus();
				return;
			}
			const entry = state.browserState.selectedEntry;
			if (!entry || entry.type !== "image") {
				feedback.showToast("Select an image entry first.", "warning");
				return;
			}
			await api("/api/images", {
				method: "POST",
				body: JSON.stringify({ path: entry.path }),
			});
			feedback.showToast("Image added", "success");
			
			await refreshStatus();
		}, { startMessage: "Adding selected entry..." });
	};

	document.getElementById("add-url-image-button").onclick = async () => {
		await runUiAction(async () => {
			const rawUrl = String(document.getElementById("url-image-input").value || "").trim();
			if (!rawUrl) {
				feedback.showToast("Enter an image URL first.", "warning");
				return;
			}
			await api("/api/url-images", {
				method: "POST",
				body: JSON.stringify({ url: rawUrl }),
			});
			feedback.showToast("URL image added", "success");
			
			await refreshStatus();
		}, { startMessage: "Adding URL image..." });
	};

	document.getElementById("clear-url-images-button").onclick = async () => {
		await runUiAction(async () => {
			await api("/api/url-images/clear", { method: "POST" });
			state.urlPreviewPath = "";
			previews.refreshUrlPreviewImage();
			feedback.showToast("URL image list cleared", "success");
			await refreshStatus();
		}, { startMessage: "Clearing URL image list..." });
	};

	document.getElementById("add-upload-image-button").onclick = async () => {
		await runUiAction(async () => {
			const input = document.getElementById("upload-image-input");
			const file = input.files && input.files[0];
			if (!file) {
				feedback.showToast("Select an image file first.", "warning");
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
			feedback.showToast("Uploaded image added", "success");
			await refreshStatus();
		}, { startMessage: "Uploading image..." });
	};

	document.getElementById("clear-upload-images-button").onclick = async () => {
		await runUiAction(async () => {
			await api("/api/upload-images/clear", { method: "POST" });
			document.getElementById("upload-image-input").value = "";
			feedback.showToast("Uploaded image list cleared", "success");
			await refreshStatus();
		}, { startMessage: "Clearing uploaded images..." });
	};

	document.getElementById("url-image-input").oninput = () => {
		const value = String(document.getElementById("url-image-input").value || "").trim();
		if (!value) {
			state.urlPreviewPath = "";
			previews.setUrlValidationState("neutral", "Enter a valid http/https image URL.");
			previews.refreshUrlPreviewImage();
			return;
		}
		try {
			const parsed = new URL(value);
			if (!["http:", "https:"].includes(parsed.protocol)) {
				state.urlPreviewPath = "";
				previews.setUrlValidationState("invalid", "Only http/https URLs are allowed.");
				previews.refreshUrlPreviewImage();
				return;
			}
			state.urlPreviewPath = value;
			previews.setUrlValidationState("valid", "URL looks valid. You can add it.");
			previews.refreshUrlPreviewImage();
		} catch (_error) {
			state.urlPreviewPath = "";
			previews.setUrlValidationState("invalid", "Invalid URL format.");
			previews.refreshUrlPreviewImage();
		}
	};

	document.getElementById("url-image-preview").onload = () => {
		document.getElementById("url-image-preview").hidden = false;
		document.getElementById("url-preview-fallback").hidden = true;
	};

	document.getElementById("url-image-preview").onerror = () => {
		document.getElementById("url-image-preview").hidden = true;
		document.getElementById("url-preview-fallback").hidden = false;
	};

	document.getElementById("list-preview-image").onload = () => {
		document.getElementById("list-preview-image").hidden = false;
		document.getElementById("list-preview-fallback").hidden = true;
	};

	document.getElementById("list-preview-image").onerror = () => {
		document.getElementById("list-preview-image").hidden = true;
		document.getElementById("list-preview-fallback").hidden = false;
	};

	document.getElementById("clear-images-button").onclick = async () => {
		await runUiAction(async () => {
			await api("/api/images/clear", { method: "POST" });
			state.selectedPreviewPath = null;
			previews.refreshSelectedPreviewImage();
			feedback.showToast("Image list cleared", "success");
			await refreshStatus();
		}, { startMessage: "Clearing selected image list..." });
	};

	const browserSelect = document.getElementById("browser-directories-select");

	browserSelect.onkeydown = async (event) => {
		if (["ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"].includes(event.key)) {
			browserSelectionByNavigationKey = true;
			return;
		}
		if (event.key === "ArrowRight") {
			const selectedPath = browserSelect.value;
			if (!selectedPath) {
				return;
			}
			const entry = (state.browserState.filteredEntries || []).find((item) => item.path === selectedPath);
			if (!entry || entry.type !== "directory") {
				return;
			}
			event.preventDefault();
			browserSelectionByNavigationKey = false;
			await browser.loadDirectoryBrowser(entry.path);
			return;
		}
		if (event.key === "ArrowLeft") {
			const parentPath = String(state.browserState.parentPath || "").trim();
			if (!parentPath) {
				return;
			}
			event.preventDefault();
			browserSelectionByNavigationKey = false;
			await browser.loadDirectoryBrowser(parentPath);
			return;
		}
		if (event.key !== "Enter") {
			return;
		}
		const selectedPath = browserSelect.value;
		if (!selectedPath) {
			return;
		}
		const entry = (state.browserState.filteredEntries || []).find((item) => item.path === selectedPath);
		if (!entry || entry.type !== "directory") {
			return;
		}
		event.preventDefault();
		await browser.loadDirectoryBrowser(entry.path);
	};

	browserSelect.ondblclick = async () => {
		const selectedPath = browserSelect.value;
		if (!selectedPath) {
			return;
		}
		const entry = (state.browserState.filteredEntries || []).find((item) => item.path === selectedPath);
		if (!entry || entry.type !== "directory") {
			return;
		}
		await browser.loadDirectoryBrowser(entry.path);
	};

	browserSelect.onchange = async () => {
		const select = document.getElementById("browser-directories-select");
		const selectedPath = select.value;
		if (!selectedPath) {
			browserSelectionByNavigationKey = false;
			return;
		}
		const entry = (state.browserState.filteredEntries || []).find((item) => item.path === selectedPath);
		if (!entry) {
			browserSelectionByNavigationKey = false;
			return;
		}
		state.browserState.selectedEntry = entry;
		browser.updateAddButtonState();
		if (entry.type === "image") {
			browserSelectionByNavigationKey = false;
			state.selectedPreviewPath = entry.path;
			previews.refreshSelectedPreviewImage();
			return;
		}
		if (browserSelectionByNavigationKey) {
			browserSelectionByNavigationKey = false;
			state.selectedPreviewPath = null;
			previews.refreshSelectedPreviewImage();
			return;
		}
		browserSelectionByNavigationKey = false;
		state.selectedPreviewPath = null;
		previews.refreshSelectedPreviewImage();
		await browser.loadDirectoryBrowser(entry.path);
	};

	document.getElementById("browser-filter-input").oninput = () => {
		const value = document.getElementById("browser-filter-input").value;
		if (state.browserState.filterTimer) {
			clearTimeout(state.browserState.filterTimer);
		}
		state.browserState.filterTimer = setTimeout(() => {
			browser.applyDirectoryFilter(value);
		}, 120);
	};

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
			feedback.showToast(`Mode selected: ${formatModeLabel(mode)}`, "info");
		};
	});

	document.querySelectorAll(".mode-activate-button").forEach((button) => {
		button.onclick = async () => {
			const mode = button.dataset.mode || "directory";
			await activateMode(mode);
		};
	});

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
				feedback.showToast("Display busy: next ignored", "warning");
			}
			await refreshStatus();
		}, { startMessage: "Loading next image on display..." });
	};

	document.getElementById("prev-button").onclick = async () => {
		await runUiAction(async () => {
			const result = await api("/api/slideshow/prev", { method: "POST" });
			if (result.ok === false) {
				feedback.showToast("Display busy: previous ignored", "warning");
			}
			await refreshStatus();
		}, { startMessage: "Loading previous image on display..." });
	};

	document.getElementById("cycle-button").onclick = async () => {
		await runUiAction(async () => {
			const result = await api("/api/folder/cycle", { method: "POST" });
			if (result.ok === false) {
				feedback.showToast("Display busy: mode change ignored", "warning");
			} else {
				const mode = String(result.mode || "");
				if (mode) {
					feedback.showToast(`Mode changed: ${mode}`, "success");
				}
			}
			await refreshStatus();
		}, { startMessage: "Changing mode and refreshing display..." });
	};

	document.getElementById("reshuffle-button").onclick = async () => {
		await runUiAction(async () => {
			const result = await api("/api/slideshow/reshuffle", { method: "POST" });
			if (result.ok === false) {
				feedback.showToast("Display busy: reshuffle ignored", "warning");
			} else {
				feedback.showToast("Slideshow reshuffled", "success");
			}
			await refreshStatus();
		}, { startMessage: "Reshuffling slideshow and refreshing display..." });
	};

	document.getElementById("save-settings-button").onclick = async () => {
		await runUiAction(async () => {
			const interval = Math.max(30, Number(document.getElementById("interval-input").value));
			const saturation = Number(document.getElementById("saturation-input").value);
			const scaleToFit = document.getElementById("scale-to-fit-input").checked;
			const lockButtons = document.getElementById("lock-buttons-input").checked;
			const renderWidth = Math.max(64, Number(document.getElementById("render-width-input").value));
			const renderHeight = Math.max(64, Number(document.getElementById("render-height-input").value));
			await api("/api/settings", {
				method: "POST",
				body: JSON.stringify({
					slideshow_interval: interval,
					saturation,
					scale_to_fit: scaleToFit,
					lock_buttons: lockButtons,
					render_width: renderWidth,
					render_height: renderHeight,
				}),
			});
			feedback.showToast("Settings saved", "success");
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

	document.getElementById("command-palette-close").onclick = () => palette.closeCommandPalette();
	document.getElementById("command-palette-input").oninput = (event) => {
		palette.renderCommandPaletteList(event.target.value || "");
	};
	document.getElementById("command-palette-list").onmousemove = (event) => {
		const row = event.target.closest(".command-item:not(.empty)");
		if (!row) {
			return;
		}
		const idx = Number(row.dataset.index);
		if (Number.isInteger(idx)) {
			palette.setCommandPaletteActiveIndex(idx);
		}
	};
	document.getElementById("command-palette-overlay").onclick = (event) => {
		if (event.target.id === "command-palette-overlay") {
			palette.closeCommandPalette();
		}
	};

	document.addEventListener("click", (event) => {
		if (event.target.closest(".row-actions-menu")) {
			return;
		}
		document.querySelectorAll(".row-actions-menu[open]").forEach((menu) => {
			menu.removeAttribute("open");
		});
	});

	document.addEventListener("keydown", (event) => {
		const isPaletteShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
		if (isPaletteShortcut) {
			event.preventDefault();
			if (palette.isOpen()) {
				palette.closeCommandPalette();
			} else {
				palette.openCommandPalette();
			}
			return;
		}
		const isContrastShortcut = event.altKey && event.key.toLowerCase() === "h";
		if (isContrastShortcut) {
			event.preventDefault();
			feedback.setContrastEnabled(!document.body.classList.contains("high-contrast"));
			return;
		}
		if (event.key === "Escape" && palette.isOpen()) {
			event.preventDefault();
			palette.closeCommandPalette();
			return;
		}
		if (palette.isOpen() && event.key === "ArrowDown") {
			event.preventDefault();
			palette.setCommandPaletteActiveIndex(palette.getActiveIndex() + 1);
			return;
		}
		if (palette.isOpen() && event.key === "ArrowUp") {
			event.preventDefault();
			palette.setCommandPaletteActiveIndex(palette.getActiveIndex() - 1);
			return;
		}
		if (palette.isOpen() && event.key === "Home") {
			event.preventDefault();
			palette.setCommandPaletteActiveIndex(0);
			return;
		}
		if (palette.isOpen() && event.key === "End") {
			event.preventDefault();
			palette.setCommandPaletteActiveIndex(palette.getFilteredLength() - 1);
			return;
		}
		if (palette.isOpen() && event.key === "Enter") {
			event.preventDefault();
			const active = document.querySelector(
				`#command-palette-list .command-item[data-index="${palette.getActiveIndex()}"]:not(.empty)`
			);
			if (active) {
				active.click();
			}
		}
	});
}

function buildCommandPaletteCommands() {
	const selectUiMode = (mode) => {
		setModeButtons(mode, state);
		state.selectedPreviewPath = null;
		previews.refreshSelectedPreviewImage();
		applyModeUiState(state.latestStatus || {});
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
