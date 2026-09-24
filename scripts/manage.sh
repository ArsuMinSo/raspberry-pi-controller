#!/bin/bash
# Run backend.manage on the server as the service user, with DB_PASSWORD from .env.
#   sudo /opt/pi-controller/scripts/manage.sh create-user alice --role admin
#   sudo /opt/pi-controller/scripts/manage.sh reset-password alice
#   sudo /opt/pi-controller/scripts/manage.sh list-users
#   sudo /opt/pi-controller/scripts/manage.sh rotate-tui-key
set -euo pipefail
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="pi_controller"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0 $*" >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source "$INSTALL_DIR/.env"
set +a
cd "$INSTALL_DIR"
exec sudo -u "$SERVICE_USER" --preserve-env=DB_PASSWORD,SUDO_USER "$INSTALL_DIR/.venv/bin/python" -m backend.manage "$@"
