export const SETTINGS_STORAGE_KEY = "inkyImageSettingsCollapsed";
export const CONTRAST_STORAGE_KEY = "inkyImageHighContrast";

export function createState() {
	return {
		browserState: {
			currentPath: null,
			parentPath: null,
			entries: [],
			filteredEntries: [],
			filterText: "",
			filterTimer: null,
			selectedEntry: null,
		},
		uiActionInProgress: false,
		latestStatus: null,
		uiMode: "directory",
		uiModeInitialized: false,
		selectedPreviewPath: null,
		urlPreviewPath: "",
		listPreviewMode: "",
		listPreviewType: "",
		listPreviewValue: "",
		listPreviewRenderToken: "",
	};
}
