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

	function bindDomEvents() {
		document.getElementById("url-image-input").oninput = () => {
			const value = String(document.getElementById("url-image-input").value || "").trim();
			if (!value) {
				state.urlPreviewPath = "";
				setUrlValidationState("neutral", "Enter a valid http/https image URL.");
				refreshUrlPreviewImage();
				return;
			}
			try {
				const parsed = new URL(value);
				if (!["http:", "https:"].includes(parsed.protocol)) {
					state.urlPreviewPath = "";
					setUrlValidationState("invalid", "Only http/https URLs are allowed.");
					refreshUrlPreviewImage();
					return;
				}
				state.urlPreviewPath = value;
				setUrlValidationState("valid", "URL looks valid. You can add it.");
				refreshUrlPreviewImage();
			} catch (_error) {
				state.urlPreviewPath = "";
				setUrlValidationState("invalid", "Invalid URL format.");
				refreshUrlPreviewImage();
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
	}

	return {
		refreshPreviewImage,
		refreshSelectedPreviewImage,
		refreshUrlPreviewImage,
		clearListPreview,
		setListPreview,
		refreshListPreviewImage,
		setUrlValidationState,
		bindDomEvents,
	};
}
