#!/usr/bin/env bash
set -euo pipefail

printUsage() {
	echo "Usage: sudo ./update.sh [--user <linux-user>] [--target-dir <absolute-path>]"
	echo
	echo "Examples:"
	echo "  sudo ./update.sh"
	echo "  sudo ./update.sh --user pi"
	echo "  sudo ./update.sh --user pi --target-dir /home/pi/inky-image"
}

# Inside a sed replacement, \ & and the | delimiter must be escaped or a path
# containing one of them silently corrupts the rendered unit file.
sed_escape() {
	printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'
}

fail() {
	echo "$1" >&2
	exit 1
}

# Refuse anything rsync --delete could ruin: system directories, the target
# user's home itself, an ancestor of the checkout, or a non-empty directory
# that is not already an inky-image install.
validate_target_dir() {
	case "${TARGET_DIR}" in
		/|/home|/root|/usr|/usr/local|/etc|/var|/opt|/srv|/bin|/boot|/lib|/tmp)
			fail "Refusing to install into unsafe target directory: ${TARGET_DIR}"
			;;
	esac
	if [[ "${TARGET_DIR}" == "${TARGET_HOME}" ]]; then
		fail "Refusing to install into unsafe target directory: ${TARGET_DIR}"
	fi
	if [[ "${TARGET_DIR}" != "${SOURCE_DIR}" && "${SOURCE_DIR}/" == "${TARGET_DIR}/"* ]]; then
		fail "Refusing to install into unsafe target directory: ${TARGET_DIR}"
	fi
	if [[ -e "${TARGET_DIR}" && ! -d "${TARGET_DIR}" ]]; then
		fail "Refusing to install into unsafe target directory: ${TARGET_DIR}"
	fi
	if [[ -d "${TARGET_DIR}" && -n "$(ls -A "${TARGET_DIR}" 2>/dev/null)" \
		&& ! -e "${TARGET_DIR}/inky_image/main.py" ]]; then
		fail "Refusing to overwrite a directory that is not an inky-image install: ${TARGET_DIR}"
	fi
}

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${TARGET_USER:-${SUDO_USER:-}}"
TARGET_DIR=""

for arg in "$@"; do
	if [[ "${arg}" == "-h" || "${arg}" == "--help" ]]; then
		printUsage
		exit 0
	fi
done

if [[ "${EUID}" -ne 0 ]]; then
	echo "Run this updater as root (sudo)." >&2
	exit 1
fi

while [[ $# -gt 0 ]]; do
	case "$1" in
		--user)
			shift
			TARGET_USER="${1:-}"
			;;
		--target-dir)
			shift
			TARGET_DIR="${1:-}"
			;;
		-h|--help)
			printUsage
			exit 0
			;;
		*)
			echo "Unknown argument: $1" >&2
			printUsage
			exit 1
			;;
	esac
	shift
done

if [[ -z "${TARGET_USER}" || "${TARGET_USER}" == "root" ]]; then
	echo "Could not determine non-root target user." >&2
	echo "Run with sudo from the target user, or pass --user explicitly." >&2
	echo "Example: sudo ./update.sh --user pi" >&2
	exit 1
fi

TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
if [[ -z "${TARGET_HOME}" || ! -d "${TARGET_HOME}" ]]; then
	echo "Could not resolve home directory for user ${TARGET_USER}." >&2
	exit 1
fi

if [[ -z "${TARGET_DIR}" ]]; then
	TARGET_DIR="${SOURCE_DIR}"
fi
if [[ "${TARGET_DIR:0:1}" != "/" ]]; then
	echo "--target-dir must be an absolute path." >&2
	exit 1
fi
TARGET_DIR="${TARGET_DIR%/}"
if [[ -z "${TARGET_DIR}" ]]; then
	echo "--target-dir must be an absolute path." >&2
	exit 1
fi
validate_target_dir

trap 'echo "Update failed. The running service may not match the code on disk; re-run ./update.sh once the error above is fixed." >&2' ERR

if [[ ! -d "${SOURCE_DIR}/.git" ]]; then
	echo "Updater must be run from a git checkout: ${SOURCE_DIR}" >&2
	exit 1
fi

VENV_DIR="${TARGET_DIR}/venv"
SERVICE_TEMPLATE="${SOURCE_DIR}/inky-image.service"
SERVICE_PATH="/etc/systemd/system/inky-image.service"

echo "[1/5] Validating project structure..."
for requiredPath in "inky_image" "templates" "static" "requirements.txt" "inky-image.service"; do
	if [[ ! -e "${SOURCE_DIR}/${requiredPath}" ]]; then
		echo "Missing required path: ${SOURCE_DIR}/${requiredPath}" >&2
		exit 1
	fi
done
if [[ ! -x "${VENV_DIR}/bin/python" || ! -x "${VENV_DIR}/bin/pip" ]]; then
	echo "Virtual environment is missing. Run install.sh first." >&2
	exit 1
fi

echo "[2/5] Pulling latest code..."
if [[ -n "$(sudo -u "${TARGET_USER}" git -C "${SOURCE_DIR}" status --porcelain)" ]]; then
	echo "Local checkout has uncommitted changes. Commit or discard them before updating." >&2
	exit 1
fi
before_revision="$(sudo -u "${TARGET_USER}" git -C "${SOURCE_DIR}" rev-parse HEAD)"
sudo -u "${TARGET_USER}" git -C "${SOURCE_DIR}" pull --ff-only
after_revision="$(sudo -u "${TARGET_USER}" git -C "${SOURCE_DIR}" rev-parse HEAD)"

if [[ "${before_revision}" == "${after_revision}" ]]; then
	echo "Already up to date."
	changed_files=""
else
	changed_files="$(sudo -u "${TARGET_USER}" git -C "${SOURCE_DIR}" diff --name-only "${before_revision}" "${after_revision}")"
fi

# Dependencies install before the target tree is replaced so a failed pip
# install cannot leave new code on disk next to the dependencies the running
# process already loaded.
echo "[3/5] Updating Python dependencies if needed..."
if [[ "${changed_files}" == *"requirements.txt"* ]]; then
	sudo -u "${TARGET_USER}" "${VENV_DIR}/bin/pip" install -r "${SOURCE_DIR}/requirements.txt"
else
	echo "requirements.txt unchanged."
fi

echo "[4/5] Syncing project files if needed..."
if [[ "${SOURCE_DIR}" != "${TARGET_DIR}" ]]; then
	mkdir -p "${TARGET_DIR}"
	rsync -a --delete \
		--exclude ".git/" \
		--exclude ".github/" \
		--exclude "__pycache__/" \
		--exclude "*.pyc" \
		--exclude ".DS_Store" \
		--exclude "venv/" \
		--exclude ".venv/" \
		"${SOURCE_DIR}/" "${TARGET_DIR}/"
	chown -R "${TARGET_USER}:${TARGET_USER}" "${TARGET_DIR}"
else
	echo "Checkout is the target directory; nothing to sync."
fi

echo "[5/5] Updating systemd unit if needed and restarting service..."
if [[ "${changed_files}" == *"inky-image.service"* || ! -e "${SERVICE_PATH}" ]]; then
	cp "${SERVICE_TEMPLATE}" "${SERVICE_PATH}"
	sed -i "s|__INKY_USER__|$(sed_escape "${TARGET_USER}")|g" "${SERVICE_PATH}"
	sed -i "s|__INKY_HOME__|$(sed_escape "${TARGET_HOME}")|g" "${SERVICE_PATH}"
	sed -i "s|__INKY_TARGET_DIR__|$(sed_escape "${TARGET_DIR}")|g" "${SERVICE_PATH}"
	systemctl daemon-reload
else
	echo "inky-image.service unchanged."
fi

systemctl restart inky-image.service

echo
echo "Update complete."
echo "Current revision: ${after_revision}"
systemctl status --no-pager inky-image.service || true
