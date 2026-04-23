export const MODE_LABELS = {
	directory: "Directory",
	image_list: "Image list",
	url: "URL",
	upload: "Upload",
};

export const VALID_MODES = ["directory", "image_list", "url", "upload"];

export function formatModeLabel(mode) {
	return MODE_LABELS[String(mode || "").trim()] || "Directory";
}

export function setModeButtons(mode, state) {
	const normalized = VALID_MODES.includes(mode) ? mode : "directory";
	state.uiMode = normalized;
	document.querySelectorAll(".mode-button").forEach((button) => {
		const active = button.dataset.mode === normalized;
		button.classList.toggle("active", active);
		button.setAttribute("aria-pressed", active ? "true" : "false");
	});
}

export function getActiveMode(state) {
	return state.uiMode || (state.latestStatus && state.latestStatus.mode) || "directory";
}
