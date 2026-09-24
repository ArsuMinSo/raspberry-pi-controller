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

# Runs as root on a repo owned by $SERVICE_USER — tell git that's fine
# (otherwise: "detected dubious ownership"). Root's global config, because
# older git (e.g. Ubuntu 22.04) ignores safe.directory passed via -c.
if ! git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$INSTALL_DIR"; then
    git config --global --add safe.directory "$INSTALL_DIR"
fi

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
# Settings survive updates: .env is gitignored (never touched), and config.yaml
# (tracked, but rewritten by the Settings screen) is backed up here and merged
# back over the new defaults after the pull.
CONFIG_FILE="$INSTALL_DIR/config.yaml"
CONFIG_BACKUP=""
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing install at $INSTALL_DIR …"
    if [ -f "$CONFIG_FILE" ]; then
        CONFIG_BACKUP="$INSTALL_DIR/config.yaml.bak-$(date +%Y%m%d-%H%M%S)"
        cp -p "$CONFIG_FILE" "$CONFIG_BACKUP"
        git -C "$INSTALL_DIR" checkout -- config.yaml  # let pull fast-forward
        echo "Backed up settings to $CONFIG_BACKUP"
    fi
    if ! git -C "$INSTALL_DIR" pull --ff-only; then
        [ -n "$CONFIG_BACKUP" ] && cp -p "$CONFIG_BACKUP" "$CONFIG_FILE"
        echo "git pull failed — settings left unchanged"
        exit 1
    fi
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

# ── Restore settings ──────────────────────────────────────────────────────────
# New config.yaml supplies defaults for any new keys; every old value wins.
if [ -n "$CONFIG_BACKUP" ]; then
    "$VENV/bin/python" - "$CONFIG_FILE" "$CONFIG_BACKUP" <<'PY'
import sys
import yaml

new_path, old_path = sys.argv[1], sys.argv[2]

def merge(new, old):
    if isinstance(new, dict) and isinstance(old, dict):
        out = dict(new)
        for k, v in old.items():
            out[k] = merge(new[k], v) if k in new else v
        return out
    return old

with open(new_path) as f:
    new = yaml.safe_load(f) or {}
with open(old_path) as f:
    old = yaml.safe_load(f) or {}
with open(new_path, "w") as f:
    yaml.dump(merge(new, old), f, default_flow_style=False, allow_unicode=True)
PY
    chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_FILE"
    echo "Restored previous settings into $CONFIG_FILE"
fi

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

# Single worker: scheduler and runtime settings live in-process — more workers
# would run every scheduled task N times and split settings between processes.
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
ExecStart=${VENV}/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
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
