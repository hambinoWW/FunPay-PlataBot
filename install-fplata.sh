#!/usr/bin/env bash
set -Eeuo pipefail

# One-command Ubuntu installer for PLATA.
REPO_URL="${PLATA_REPO_URL:-https://github.com/hambinoWW/FunPay-PlataBot.git}"
INSTALL_DIR="${PLATA_DIR:-$HOME/PLATA}"
VENV_DIR="${PLATA_VENV:-$HOME/pyvenv}"
RUN_AFTER_INSTALL=1
INSTALL_SERVICE=0

usage() {
    cat <<'EOF'
Usage: install-fplata.sh [--no-run] [--service]

  --no-run   install/update only; do not start the first-run wizard
  --service  install and enable the PLATA@.service for the current user
EOF
}

for arg in "$@"; do
    case "$arg" in
        --no-run) RUN_AFTER_INSTALL=0 ;;
        --service) INSTALL_SERVICE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This installer supports Linux only (Ubuntu 22.04+ recommended)." >&2
    exit 1
fi

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Run this installer as a regular user with sudo access, not as root." >&2
    exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required to install system packages." >&2
    exit 1
fi

echo "==> Installing system dependencies"
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip

if [[ -e "$INSTALL_DIR/.git" ]]; then
    echo "==> Updating $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only
elif [[ -e "$INSTALL_DIR" ]]; then
    echo "Installation directory exists but is not a git checkout: $INSTALL_DIR" >&2
    exit 1
else
    echo "==> Cloning PLATA into $INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

echo "==> Preparing Python environment"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"

if [[ "$INSTALL_SERVICE" -eq 1 ]]; then
    echo "==> Installing systemd service"
    sudo install -m 0644 "$INSTALL_DIR/PLATA@.service" /etc/systemd/system/PLATA@.service
    sudo systemctl daemon-reload
    sudo systemctl enable "PLATA@${USER}.service"
    echo "Service enabled. Start it after completing setup with:"
    echo "  sudo systemctl start PLATA@${USER}.service"
fi

if [[ "$RUN_AFTER_INSTALL" -eq 1 ]]; then
    echo "==> Starting PLATA (Ctrl+C stops the process)"
    cd "$INSTALL_DIR"
    exec "$VENV_DIR/bin/python" main.py
else
    echo "Installation complete. Start PLATA with:"
    echo "  cd '$INSTALL_DIR' && '$VENV_DIR/bin/python' main.py"
fi
