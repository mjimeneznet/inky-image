export function createCommandPalette({ setContrastEnabled }) {
	let commandPaletteOpen = false;
	let commandPaletteCommands = [];
	let commandPaletteFilteredCommands = [];
	let commandPaletteActiveIndex = 0;

	function setCommands(commands) {
		commandPaletteCommands = Array.isArray(commands) ? commands : [];
	}

	function renderCommandPaletteList(filterText = "") {
		const list = document.getElementById("command-palette-list");
		if (!list) {
			return;
		}
		const needle = String(filterText || "").trim().toLowerCase();
		const commands = !needle
			? commandPaletteCommands
			: commandPaletteCommands.filter((cmd) => `${cmd.label} ${cmd.keywords}`.toLowerCase().includes(needle));
		commandPaletteFilteredCommands = commands;
		commandPaletteActiveIndex = commands.length > 0 ? 0 : -1;
		list.innerHTML = "";
		commands.forEach((cmd, index) => {
			const row = document.createElement("li");
			row.className = "command-item";
			row.setAttribute("role", "option");
			row.setAttribute("aria-selected", index === commandPaletteActiveIndex ? "true" : "false");
			row.dataset.index = String(index);
			const label = document.createElement("span");
			label.className = "command-item-label";
			label.textContent = cmd.label;
			row.appendChild(label);
			if (cmd.shortcut) {
				const shortcut = document.createElement("kbd");
				shortcut.className = "command-item-shortcut";
				shortcut.textContent = cmd.shortcut;
				row.appendChild(shortcut);
			}
			row.onclick = () => {
				closeCommandPalette();
				cmd.run();
			};
			if (index === commandPaletteActiveIndex) {
				row.classList.add("active");
			}
			list.appendChild(row);
		});
		if (commands.length === 0) {
			const row = document.createElement("li");
			row.className = "command-item empty";
			row.textContent = "No commands found";
			list.appendChild(row);
		}
	}

	function setCommandPaletteActiveIndex(nextIndex) {
		const list = document.getElementById("command-palette-list");
		if (!list || commandPaletteFilteredCommands.length === 0) {
			commandPaletteActiveIndex = -1;
			return;
		}
		const maxIndex = commandPaletteFilteredCommands.length - 1;
		const boundedIndex = Math.max(0, Math.min(maxIndex, nextIndex));
		commandPaletteActiveIndex = boundedIndex;
		Array.from(list.querySelectorAll(".command-item:not(.empty)")).forEach((row, index) => {
			const active = index === commandPaletteActiveIndex;
			row.classList.toggle("active", active);
			row.setAttribute("aria-selected", active ? "true" : "false");
			if (active) {
				row.scrollIntoView({ block: "nearest" });
			}
		});
	}

	function openCommandPalette() {
		const overlay = document.getElementById("command-palette-overlay");
		const input = document.getElementById("command-palette-input");
		if (!overlay || !input) {
			return;
		}
		commandPaletteOpen = true;
		overlay.hidden = false;
		input.value = "";
		renderCommandPaletteList("");
		setCommandPaletteActiveIndex(0);
		input.focus();
	}

	function closeCommandPalette() {
		const overlay = document.getElementById("command-palette-overlay");
		if (!overlay) {
			return;
		}
		commandPaletteOpen = false;
		overlay.hidden = true;
		if (document.activeElement && typeof document.activeElement.blur === "function") {
			document.activeElement.blur();
		}
	}

	function isOpen() {
		return commandPaletteOpen;
	}

	function getActiveIndex() {
		return commandPaletteActiveIndex;
	}

	function getFilteredLength() {
		return commandPaletteFilteredCommands.length;
	}

	function bindDomEvents() {
		document.getElementById("command-palette-close").onclick = () => closeCommandPalette();
		document.getElementById("command-palette-input").oninput = (event) => {
			renderCommandPaletteList(event.target.value || "");
		};
		document.getElementById("command-palette-list").onmousemove = (event) => {
			const row = event.target.closest(".command-item:not(.empty)");
			if (!row) {
				return;
			}
			const idx = Number(row.dataset.index);
			if (Number.isInteger(idx)) {
				setCommandPaletteActiveIndex(idx);
			}
		};
		document.getElementById("command-palette-overlay").onclick = (event) => {
			if (event.target.id === "command-palette-overlay") {
				closeCommandPalette();
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
				if (isOpen()) {
					closeCommandPalette();
				} else {
					openCommandPalette();
				}
				return;
			}
			const isContrastShortcut = event.altKey && event.key.toLowerCase() === "h";
			if (isContrastShortcut) {
				event.preventDefault();
				setContrastEnabled(!document.body.classList.contains("high-contrast"));
				return;
			}
			if (event.key === "Escape" && isOpen()) {
				event.preventDefault();
				closeCommandPalette();
				return;
			}
			if (isOpen() && event.key === "ArrowDown") {
				event.preventDefault();
				setCommandPaletteActiveIndex(getActiveIndex() + 1);
				return;
			}
			if (isOpen() && event.key === "ArrowUp") {
				event.preventDefault();
				setCommandPaletteActiveIndex(getActiveIndex() - 1);
				return;
			}
			if (isOpen() && event.key === "Home") {
				event.preventDefault();
				setCommandPaletteActiveIndex(0);
				return;
			}
			if (isOpen() && event.key === "End") {
				event.preventDefault();
				setCommandPaletteActiveIndex(getFilteredLength() - 1);
				return;
			}
			if (isOpen() && event.key === "Enter") {
				event.preventDefault();
				const active = document.querySelector(
					`#command-palette-list .command-item[data-index="${getActiveIndex()}"]:not(.empty)`
				);
				if (active) {
					active.click();
				}
			}
		});
	}

	return {
		setCommands,
		renderCommandPaletteList,
		setCommandPaletteActiveIndex,
		openCommandPalette,
		closeCommandPalette,
		isOpen,
		getActiveIndex,
		getFilteredLength,
		bindDomEvents,
	};
}
