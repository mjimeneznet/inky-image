export function createFeedback({ formatModeLabel, contrastStorageKey }) {
	function showMessage(message) {
		document.getElementById("status-output").textContent = String(message || "");
	}

	function showToast(message, type = "info", timeoutMs = 2500) {
		const container = document.getElementById("toast-container");
		if (!container) {
			return;
		}
		const toast = document.createElement("div");
		toast.className = `toast ${type}`;
		toast.textContent = String(message || "");
		container.appendChild(toast);
		requestAnimationFrame(() => {
			toast.classList.add("visible");
		});
		window.setTimeout(() => {
			toast.classList.remove("visible");
			window.setTimeout(() => {
				toast.remove();
			}, 220);
		}, timeoutMs);
	}

	function setActionStatus(message, visible) {
		const bar = document.getElementById("action-status-bar");
		const text = document.getElementById("action-status-text");
		if (!bar || !text) {
			return;
		}
		text.textContent = String(message || "Working...");
		bar.hidden = !visible;
	}

	function setTopUiState(stateText) {
		const uiState = document.getElementById("top-ui-state");
		if (uiState) {
			uiState.textContent = String(stateText || "ready");
		}
	}

	function updateTopStatus(status) {
		const activeMode = formatModeLabel((status && status.mode) || "directory");
		const slideshowRunning = Boolean(status && status.slideshow_running);
		const lockButtons = Boolean(status && status.lock_buttons);
		const activeModeNode = document.getElementById("top-active-mode");
		const slideshowNode = document.getElementById("top-slideshow-state");
		const lockNode = document.getElementById("top-lock-state");
		if (activeModeNode) {
			activeModeNode.textContent = activeMode;
		}
		if (slideshowNode) {
			slideshowNode.textContent = slideshowRunning ? "running" : "stopped";
		}
		if (lockNode) {
			lockNode.textContent = lockButtons ? "locked" : "unlocked";
		}
	}

	function applySettingsPanelState() {
		const collapsed = document.body.classList.contains("settings-collapsed");
		const toggle = document.getElementById("settings-toggle");
		toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
		toggle.title = collapsed ? "Show settings" : "Hide settings";
	}

	function applyContrastModeState() {
		const enabled = document.body.classList.contains("high-contrast");
		const input = document.getElementById("high-contrast-input");
		if (!input) {
			return;
		}
		input.checked = enabled;
	}

	function setContrastEnabled(enabled) {
		document.body.classList.toggle("high-contrast", Boolean(enabled));
		localStorage.setItem(contrastStorageKey, enabled ? "1" : "0");
		applyContrastModeState();
		showToast(enabled ? "High contrast enabled" : "Standard contrast enabled", "info");
	}

	function showBadge(message, type = "info", timeoutMs = 2200) {
		showToast(message, type, timeoutMs);
	}

	function showBusyBadge(message = "Display is refreshing...") {
		const badge = document.getElementById("ui-badge");
		if (!badge) {
			return;
		}
		badge.textContent = String(message || "Display is refreshing...");
		badge.className = "ui-badge visible busy";
	}

	function hideBusyBadge() {
		const badge = document.getElementById("ui-badge");
		if (!badge) {
			return;
		}
		badge.className = "ui-badge";
	}

	function setUiButtonsDisabled(disabled) {
		const ids = [
			"add-directory-button",
			"clear-images-button",
			"add-url-image-button",
			"clear-url-images-button",
			"add-upload-image-button",
			"clear-upload-images-button",
			"upload-image-input",
			"url-image-input",
			"toggle-button",
			"next-button",
			"prev-button",
			"cycle-button",
			"reshuffle-button",
			"save-settings-button",
			"lock-buttons-input",
			"high-contrast-input",
			"render-width-input",
			"render-height-input",
		];
		for (const id of ids) {
			const element = document.getElementById(id);
			if (element) {
				element.disabled = disabled;
			}
		}
		document
			.querySelectorAll("#directories-list button, #selected-images-list button, #url-images-list button, #upload-images-list button")
			.forEach((button) => {
				button.disabled = disabled;
			});
		document.querySelectorAll(".mode-button").forEach((button) => {
			button.disabled = disabled;
		});
		document.querySelectorAll(".mode-activate-button").forEach((button) => {
			button.disabled = disabled;
		});
	}

	return {
		showMessage,
		showToast,
		setActionStatus,
		setTopUiState,
		updateTopStatus,
		applySettingsPanelState,
		applyContrastModeState,
		setContrastEnabled,
		showBadge,
		showBusyBadge,
		hideBusyBadge,
		setUiButtonsDisabled,
	};
}
