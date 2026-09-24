#!/bin/bash
# Local break-glass TUI — run on the controller itself:
#   sudo /opt/pi-controller/scripts/tui.sh
# Uses the install's venv (correct Textual version) and reads the key file as root.
set -euo pipefail
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0" >&2
    exit 1
fi
cd "$INSTALL_DIR"
export PI_CONTROLLER_TUI_KEY_FILE="$INSTALL_DIR/.tui-key"
exec "$INSTALL_DIR/.venv/bin/python" -m frontend.main "$@"
