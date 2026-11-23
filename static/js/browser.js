// Inside this factory the object main.js keeps is not called `browser`;
// call the local helpers directly or the handler throws a ReferenceError.
export function createBrowser({ state, api, getActiveMode, previews, showMessage }) {
	let browserSelectionByNavigationKey = false;

	function updateAddButtonState() {
		const button = document.getElementById("add-directory-button");
		const mode = getActiveMode();
		if (mode === "directory") {
			button.textContent = "Add current folder";
			button.disabled = !state.browserState.currentPath;
			return;
		}
		if (mode === "image_list") {
			button.textContent = "Add selected image";
			const entry = state.browserState.selectedEntry;
			button.disabled = !(entry && entry.type === "image");
			return;
		}
		button.disabled = true;
	}

	function renderFilteredEntries() {
		const select = document.getElementById("browser-directories-select");
		const previousValue = String(
			select.value || (state.browserState.selectedEntry && state.browserState.selectedEntry.path) || ""
		);
		const previousScrollTop = select.scrollTop;
		select.innerHTML = "";
		const mode = getActiveMode();
		let rows = state.browserState.filteredEntries || [];
		if (mode === "directory") {
			rows = rows.filter((entry) => entry.type === "directory");
		}
		for (const entry of rows) {
			const option = document.createElement("option");
			option.value = entry.path;
			option.textContent = entry.label;
			select.appendChild(option);
		}
		if (select.options.length === 0) {
			const option = document.createElement("option");
			option.value = "";
			option.textContent = "No matches";
			select.appendChild(option);
		}
		select.disabled = select.options.length === 0;
		if (previousValue) {
			select.value = previousValue;
		}
		if (select.value === previousValue && previousValue) {
			const selectedEntry = rows.find((entry) => entry.path === previousValue) || null;
			state.browserState.selectedEntry = selectedEntry;
		} else {
			select.selectedIndex = -1;
			state.browserState.selectedEntry = null;
		}
		select.scrollTop = previousScrollTop;
		document.getElementById("current-path-display").textContent = state.browserState.currentPath || "/";
		updateAddButtonState();
	}

	function applyDirectoryFilter(filterText) {
		const normalized = String(filterText || "").trim().toLowerCase();
		state.browserState.filterText = normalized;
		if (!normalized) {
			state.browserState.filteredEntries = [...state.browserState.entries];
		} else {
			state.browserState.filteredEntries = state.browserState.entries.filter((entry) =>
				String(entry.path || "").toLowerCase().includes(normalized)
			);
		}
		renderFilteredEntries();
	}

	async function loadDirectoryBrowser(path = "") {
		try {
			const query = path ? `?path=${encodeURIComponent(path)}` : "";
			const result = await api(`/api/directories/browse${query}`);
			state.browserState.currentPath = result.path;
			state.browserState.parentPath = result.parent_path || null;
			state.browserState.selectedEntry = null;
			state.selectedPreviewPath = null;
			const entries = [];
			if (state.browserState.parentPath) {
				entries.push({
					type: "directory",
					path: state.browserState.parentPath,
					label: ".. (parent directory)",
				});
			} else {
				for (const rootPath of result.root_paths || []) {
					if (rootPath === result.path) {
						continue;
					}
					entries.push({
						type: "directory",
						path: rootPath,
						label: `.. ${rootPath}`,
					});
				}
			}
			for (const entry of result.entries || []) {
				entries.push({
					type: entry.type,
					path: entry.path,
					label: entry.type === "image" ? `[img] ${entry.name}` : `${entry.name}/`,
				});
			}
			state.browserState.entries = entries;
			applyDirectoryFilter(state.browserState.filterText);
			previews.refreshPreviewImage();
			previews.refreshSelectedPreviewImage();
		} catch (error) {
			showMessage(error.message);
		}
	}

	function bindDomEvents() {
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
				await loadDirectoryBrowser(entry.path);
				return;
			}
			if (event.key === "ArrowLeft") {
				const parentPath = String(state.browserState.parentPath || "").trim();
				if (!parentPath) {
					return;
				}
				event.preventDefault();
				browserSelectionByNavigationKey = false;
				await loadDirectoryBrowser(parentPath);
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
			await loadDirectoryBrowser(entry.path);
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
			await loadDirectoryBrowser(entry.path);
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
			updateAddButtonState();
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
			await loadDirectoryBrowser(entry.path);
		};

		document.getElementById("browser-filter-input").oninput = () => {
			const value = document.getElementById("browser-filter-input").value;
			if (state.browserState.filterTimer) {
				clearTimeout(state.browserState.filterTimer);
			}
			state.browserState.filterTimer = setTimeout(() => {
				applyDirectoryFilter(value);
			}, 120);
		};
	}

	return {
		updateAddButtonState,
		renderFilteredEntries,
		applyDirectoryFilter,
		loadDirectoryBrowser,
		bindDomEvents,
	};
}
