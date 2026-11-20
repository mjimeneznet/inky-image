#!/usr/bin/env bash
set -euo pipefail

printUsage() {
	echo "Usage: sudo ./install.sh [--user <linux-user>] [--target-dir <absolute-path>]"
	echo
	echo "Examples:"
	echo "  sudo ./install.sh"
	echo "  sudo ./install.sh --user pi"
	echo "  sudo ./install.sh --user pi --target-dir /home/pi/inky-image"
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

if [[ "${EUID}" -ne 0 ]]; then
	echo "Run this installer as root (sudo)." >&2
	exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${TARGET_USER:-${SUDO_USER:-}}"
TARGET_DIR=""

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
	echo "Example: sudo ./install.sh --user pi" >&2
	exit 1
fi

TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
if [[ -z "${TARGET_HOME}" || ! -d "${TARGET_HOME}" ]]; then
	echo "Could not resolve home directory for user ${TARGET_USER}." >&2
	exit 1
fi

if [[ -z "${TARGET_DIR}" ]]; then
	TARGET_DIR="${TARGET_HOME}/inky-image"
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

trap 'echo "Install failed. Re-run ./install.sh after fixing the error above; the service may still be running the previous code." >&2' ERR

VENV_DIR="${TARGET_DIR}/venv"
SERVICE_TEMPLATE="${SOURCE_DIR}/inky-image.service"
SERVICE_PATH="/etc/systemd/system/inky-image.service"

echo "[1/8] Validating project structure..."
for requiredPath in "inky_image" "templates" "static" "requirements.txt" "inky-image.service" "update.sh"; do
	if [[ ! -e "${SOURCE_DIR}/${requiredPath}" ]]; then
		echo "Missing required path: ${SOURCE_DIR}/${requiredPath}" >&2
		echo "Run install.sh from a complete project checkout." >&2
		exit 1
	fi
done

echo "[2/8] Installing system packages..."
apt-get update
apt-get install -y python3 python3-venv python3-pip python3-dev libgpiod-dev rsync

# Dependencies install before the project tree is replaced so a failed pip
# install cannot leave new code on disk next to the dependencies the running
# process already loaded.
echo "[3/8] Creating virtual environment..."
mkdir -p "${TARGET_DIR}"
install -m 644 "${SOURCE_DIR}/requirements.txt" "${TARGET_DIR}/requirements.txt"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
	python3 -m venv "${VENV_DIR}"
fi
chown -R "${TARGET_USER}:${TARGET_USER}" "${VENV_DIR}"

echo "[4/8] Installing Python dependencies..."
sudo -u "${TARGET_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip
sudo -u "${TARGET_USER}" "${VENV_DIR}/bin/pip" install -r "${TARGET_DIR}/requirements.txt"

echo "[5/8] Syncing project files to ${TARGET_DIR}..."
if [[ "${SOURCE_DIR}" == "${TARGET_DIR}" ]]; then
	echo "Target directory is this checkout; skipping file sync."
else
	rsync -a --delete \
		--exclude ".git/" \
		--exclude ".github/" \
		--exclude "__pycache__/" \
		--exclude "*.pyc" \
		--exclude ".DS_Store" \
		--exclude "venv/" \
		--exclude ".venv/" \
		"${SOURCE_DIR}/" "${TARGET_DIR}/"
fi
chown -R "${TARGET_USER}:${TARGET_USER}" "${TARGET_DIR}"

echo "[6/8] Installing systemd unit..."
cp "${SERVICE_TEMPLATE}" "${SERVICE_PATH}"
sed -i "s|__INKY_USER__|$(sed_escape "${TARGET_USER}")|g" "${SERVICE_PATH}"
sed -i "s|__INKY_HOME__|$(sed_escape "${TARGET_HOME}")|g" "${SERVICE_PATH}"
sed -i "s|__INKY_TARGET_DIR__|$(sed_escape "${TARGET_DIR}")|g" "${SERVICE_PATH}"

echo "[7/8] Ensuring config directory exists..."
mkdir -p "${TARGET_HOME}/.config/inky-image"
chown -R "${TARGET_USER}:${TARGET_USER}" "${TARGET_HOME}/.config/inky-image"

echo "[8/8] Enabling and restarting service..."
systemctl daemon-reload
systemctl enable inky-image.service
systemctl restart inky-image.service

echo
echo "Installation complete."
echo "Web UI: http://<raspberry-pi-ip>"
echo "Service status:"
systemctl status --no-pager inky-image.service || true
