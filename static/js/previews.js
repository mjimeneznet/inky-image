export function createPreviews({ state, getActiveMode }) {
	function refreshPreviewImage() {
		const image = document.getElementById("current-image-preview");
		image.src = `/api/current-image?ts=${Date.now()}`;
	}

	function refreshSelectedPreviewImage() {
		const mode = getActiveMode();
		const wrapper = document.getElementById("selection-preview-wrapper");
		const image = document.getElementById("selected-image-preview");
		if (mode !== "image_list") {
			image.removeAttribute("src");
			wrapper.hidden = true;
			return;
		}
		if (!state.selectedPreviewPath) {
			image.removeAttribute("src");
			wrapper.hidden = true;
			return;
		}
		wrapper.hidden = false;
		image.src = `/api/preview-file?path=${encodeURIComponent(state.selectedPreviewPath)}&ts=${Date.now()}`;
	}

	function refreshUrlPreviewImage() {
		const wrapper = document.getElementById("url-preview-wrapper");
		const image = document.getElementById("url-image-preview");
		const fallback = document.getElementById("url-preview-fallback");
		const value = String(state.urlPreviewPath || "").trim();
		if (!value) {
			image.removeAttribute("src");
			image.hidden = true;
			fallback.hidden = true;
			wrapper.hidden = true;
			return;
		}
		wrapper.hidden = false;
		image.hidden = true;
		fallback.hidden = true;
		image.src = value;
	}

	function clearListPreview() {
		state.listPreviewMode = "";
		state.listPreviewType = "";
		state.listPreviewValue = "";
		state.listPreviewRenderToken = "";
		const wrapper = document.getElementById("list-preview-wrapper");
		const image = document.getElementById("list-preview-image");
		const fallback = document.getElementById("list-preview-fallback");
		const message = document.getElementById("list-preview-message");
		image.removeAttribute("src");
		image.hidden = true;
		fallback.hidden = true;
		message.textContent = "Preview unavailable.";
		wrapper.hidden = true;
	}

	function setListPreview(mode, sourceType, value) {
		state.listPreviewMode = String(mode || "");
		state.listPreviewType = String(sourceType || "");
		state.listPreviewValue = String(value || "").trim();
		state.listPreviewRenderToken = "";
		refreshListPreviewImage();
	}

	function refreshListPreviewImage() {
		const wrapper = document.getElementById("list-preview-wrapper");
		const image = document.getElementById("list-preview-image");
		const fallback = document.getElementById("list-preview-fallback");
		const message = document.getElementById("list-preview-message");
		const mode = getActiveMode();
		if (!["image_list", "url", "upload"].includes(mode)) {
			clearListPreview();
			return;
		}
		if (!state.listPreviewValue || state.listPreviewMode !== mode) {
			image.removeAttribute("src");
			image.hidden = true;
			fallback.hidden = true;
			wrapper.hidden = true;
			state.listPreviewRenderToken = "";
			return;
		}
		wrapper.hidden = false;
		image.hidden = true;
		fallback.hidden = true;
		const nextToken = `${state.listPreviewMode}|${state.listPreviewType}|${state.listPreviewValue}`;
		if (state.listPreviewRenderToken === nextToken) {
			return;
		}
		if (state.listPreviewType === "local") {
			message.textContent = "Preview unavailable for selected file.";
			image.src = `/api/preview-file?path=${encodeURIComponent(state.listPreviewValue)}`;
			state.listPreviewRenderToken = nextToken;
			return;
		}
		message.textContent = "Preview unavailable. Remote URL may block browser loading.";
		image.src = state.listPreviewValue;
		state.listPreviewRenderToken = nextToken;
	}

	function setUrlValidationState(nextState, message) {
		const msg = document.getElementById("url-validation-message");
		const addButton = document.getElementById("add-url-image-button");
		msg.className = `url-validation ${nextState}`;
		msg.textContent = message;
		addButton.disabled = nextState !== "valid";
	}

	return {
		refreshPreviewImage,
		refreshSelectedPreviewImage,
		refreshUrlPreviewImage,
		clearListPreview,
		setListPreview,
		refreshListPreviewImage,
		setUrlValidationState,
	};
}
