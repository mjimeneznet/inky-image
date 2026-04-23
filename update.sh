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

if [[ "${SOURCE_DIR}" != "${TARGET_DIR}" ]]; then
	echo "Syncing project files to ${TARGET_DIR}..."
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
fi

echo "[3/5] Updating Python dependencies if needed..."
if [[ "${changed_files}" == *"requirements.txt"* ]]; then
	sudo -u "${TARGET_USER}" "${VENV_DIR}/bin/pip" install -r "${TARGET_DIR}/requirements.txt"
else
	echo "requirements.txt unchanged."
fi

echo "[4/5] Updating systemd unit if needed..."
if [[ "${changed_files}" == *"inky-image.service"* || ! -e "${SERVICE_PATH}" ]]; then
	cp "${SERVICE_TEMPLATE}" "${SERVICE_PATH}"
	sed -i "s|__INKY_USER__|${TARGET_USER}|g" "${SERVICE_PATH}"
	sed -i "s|__INKY_HOME__|${TARGET_HOME}|g" "${SERVICE_PATH}"
	sed -i "s|__INKY_TARGET_DIR__|${TARGET_DIR}|g" "${SERVICE_PATH}"
	systemctl daemon-reload
else
	echo "inky-image.service unchanged."
fi

echo "[5/5] Restarting service..."
systemctl restart inky-image.service

echo
echo "Update complete."
echo "Current revision: ${after_revision}"
systemctl status --no-pager inky-image.service || true
