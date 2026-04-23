export function createCommandPalette() {
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

	return {
		setCommands,
		renderCommandPaletteList,
		setCommandPaletteActiveIndex,
		openCommandPalette,
		closeCommandPalette,
		isOpen,
		getActiveIndex,
		getFilteredLength,
	};
}
