export function createBrowser({ state, api, getActiveMode, previews, showMessage }) {
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

	return {
		updateAddButtonState,
		renderFilteredEntries,
		applyDirectoryFilter,
		loadDirectoryBrowser,
	};
}
