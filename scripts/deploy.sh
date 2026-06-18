#!/bin/bash
# Deploy Pi Controller to Ubuntu server.
# Run as root (or with sudo) on the target server.
# Usage:
#   curl -fsSL <raw-url>/scripts/deploy.sh | sudo bash
#   -- or --
#   sudo bash scripts/deploy.sh
set -euo pipefail

REPO_URL="https://github.com/ArsuMinSo/raspberry-pi-controller.git"
INSTALL_DIR="/opt/pi-controller"
SERVICE_USER="pi_controller"
SERVICE_FILE="/etc/systemd/system/pi-controller.service"
PYTHON="python3"

echo "=== Pi Controller Deploy ==="

# ── Prerequisites ─────────────────────────────────────────────────────────────
for cmd in git python3 pip3 psql; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Missing: $cmd — install it first"
        exit 1
    fi
done

# ── System user ───────────────────────────────────────────────────────────────
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "Created user: $SERVICE_USER"
fi

# ── Code ──────────────────────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing install at $INSTALL_DIR …"
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "Cloning to $INSTALL_DIR …"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── Virtualenv + dependencies ─────────────────────────────────────────────────
VENV="$INSTALL_DIR/.venv"
if [ ! -d "$VENV" ]; then
    $PYTHON -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
echo "Dependencies installed."

# ── .env file ─────────────────────────────────────────────────────────────────
ENV_FILE="$INSTALL_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    read -rsp "Enter DB_PASSWORD for pi_controller user: " DB_PASSWORD
    echo
    cat > "$ENV_FILE" <<EOF
DB_PASSWORD=${DB_PASSWORD}
EOF
    chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "Created $ENV_FILE"
fi

# Load password for DB setup
# shellcheck disable=SC1090
source "$ENV_FILE"
export DB_PASSWORD

# ── Database ──────────────────────────────────────────────────────────────────
echo "Setting up database …"
bash "$INSTALL_DIR/scripts/setup_db.sh"

# ── systemd service ───────────────────────────────────────────────────────────
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Pi Controller API
After=network.target postgresql.service

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV}/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pi-controller
systemctl restart pi-controller

echo ""
echo "=== Done ==="
systemctl status pi-controller --no-pager
