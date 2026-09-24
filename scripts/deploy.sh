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
# Settings survive updates: .env and config.yaml are gitignored. config.yaml is
# still backed up before the pull and rebuilt afterwards from
# config.example.yaml (new defaults) + the backup (old values win). This also
# covers the update that stopped tracking config.yaml, where the pull deletes it.
CONFIG_FILE="$INSTALL_DIR/config.yaml"
CONFIG_EXAMPLE="$INSTALL_DIR/config.example.yaml"
CONFIG_BACKUP=""
PREV_HEAD=""  # commit to roll back to if migrations fail
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing install at $INSTALL_DIR …"
    PREV_HEAD="$(git -C "$INSTALL_DIR" rev-parse HEAD)"
    if [ -f "$CONFIG_FILE" ]; then
        CONFIG_BACKUP="$INSTALL_DIR/config.yaml.bak-$(date +%Y%m%d-%H%M%S)"
        cp -p "$CONFIG_FILE" "$CONFIG_BACKUP"
        # Older installs track config.yaml — reset it so the pull can fast-forward
        if git -C "$INSTALL_DIR" ls-files --error-unmatch config.yaml &>/dev/null; then
            git -C "$INSTALL_DIR" checkout -- config.yaml
        fi
        echo "Backed up settings to $CONFIG_BACKUP"
        # keep the newest 10 settings backups
        ls -1 "$INSTALL_DIR"/config.yaml.bak-* | head -n -10 | xargs -r rm -f --
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
    base="$CONFIG_EXAMPLE"
    [ -f "$base" ] || base="$CONFIG_FILE"  # fallback: code without an example file
    "$VENV/bin/python" - "$base" "$CONFIG_BACKUP" "$CONFIG_FILE" <<'PY'
import sys
import yaml

base_path, old_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

def merge(new, old):
    if isinstance(new, dict) and isinstance(old, dict):
        out = dict(new)
        for k, v in old.items():
            out[k] = merge(new[k], v) if k in new else v
        return out
    return old

with open(base_path) as f:
    new = yaml.safe_load(f) or {}
with open(old_path) as f:
    old = yaml.safe_load(f) or {}
with open(out_path, "w") as f:
    yaml.dump(merge(new, old), f, default_flow_style=False, allow_unicode=True)
PY
    echo "Restored previous settings into $CONFIG_FILE"
elif [ ! -f "$CONFIG_FILE" ]; then
    cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
    echo "Created $CONFIG_FILE from config.example.yaml — review SSH key path, username and subnet"
fi
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_FILE"

# ── .env file ─────────────────────────────────────────────────────────────────
ENV_FILE="$INSTALL_DIR/.env"

# Ask 3 times; all entries must match. Reads from the terminal, so it also
# works when the script itself arrives on stdin (curl … | sudo bash).
prompt_new_password() {
    local label="$1" p1 p2 p3
    while true; do
        read -rsp "Enter $label: " p1 </dev/tty; echo >/dev/tty
        read -rsp "Enter $label again (2/3): " p2 </dev/tty; echo >/dev/tty
        read -rsp "Enter $label again (3/3): " p3 </dev/tty; echo >/dev/tty
        if [ -z "$p1" ]; then
            echo "Password must not be empty." >/dev/tty
        elif [ "$p1" != "$p2" ] || [ "$p1" != "$p3" ]; then
            echo "Entries do not match — try again." >/dev/tty
        elif [[ "$p1" == *"'"* ]]; then
            # .env stores it single-quoted (read literally by bash and systemd)
            echo "Password must not contain a single quote (')." >/dev/tty
        else
            REPLY="$p1"
            return
        fi
    done
}

if [ ! -f "$ENV_FILE" ]; then
    prompt_new_password "DB_PASSWORD for pi_controller user"
    DB_PASSWORD="$REPLY"
    ( umask 077; printf "DB_PASSWORD='%s'\n" "$DB_PASSWORD" > "$ENV_FILE" )
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
if ! bash "$INSTALL_DIR/scripts/setup_db.sh"; then
    echo ""
    echo "!!! Database setup failed — the failed migration was rolled back, DB unchanged."
    if [ -n "$PREV_HEAD" ]; then
        git -C "$INSTALL_DIR" reset --hard --quiet "$PREV_HEAD"
        [ -n "$CONFIG_BACKUP" ] && cp -p "$CONFIG_BACKUP" "$CONFIG_FILE"
        chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
        echo "!!! Code rolled back to $(git -C "$INSTALL_DIR" rev-parse --short HEAD); service not restarted (still running the old version)."
    fi
    exit 1
fi

# ── Accounts ──────────────────────────────────────────────────────────────────
# Commands run as the service user from the install dir (config.yaml, .tui-key live there)
manage() {
    ( cd "$INSTALL_DIR" && sudo -u "$SERVICE_USER" --preserve-env=DB_PASSWORD "$VENV/bin/python" -m backend.manage "$@" )
}
manage ensure-tui-key   # break-glass key for the local TUI (/opt/pi-controller/.tui-key, mode 600)
echo "Web users:"
manage list-users | sed 's/^/  /'

# ── Web page release ──────────────────────────────────────────────────────────
# Installs the newest GitHub release "web-*" (made by scripts/release_web.sh) whose
# commit is contained in the deployed code, so the page is never newer than the API.
# Any problem (offline, no release, bad checksum) keeps the current page.
WEB_CURRENT="$INSTALL_DIR/web-current"
WEB_RELEASES="$INSTALL_DIR/web-releases"
WEB_REPO="ArsuMinSo/raspberry-pi-controller"
WEB_KEEP=3  # newest real releases kept (the placeholder is never deleted)

# stdin: GitHub releases JSON → "tag sha tar_url sha256_url" per usable web release, newest first
PICK_WEB_RELEASE_PY=$(cat <<'PY'
import json, re, sys
out = []
for r in json.load(sys.stdin):
    tag, sha = r.get("tag_name") or "", r.get("target_commitish") or ""
    # release_web.sh always targets a full commit SHA; a branch name can't be checked for ancestry
    if r.get("draft") or not tag.startswith("web-") or not re.fullmatch(r"[0-9a-f]{40}", sha):
        continue
    assets = {a["name"]: a["browser_download_url"] for a in r.get("assets", [])}
    tar = next((n for n in sorted(assets) if n.endswith(".tar.gz")), None)
    if tar and tar + ".sha256" in assets:
        out.append((r.get("published_at") or "", tag, sha, assets[tar], assets[tar + ".sha256"]))
for _, tag, sha, tar_url, sum_url in sorted(out, reverse=True):
    print(tag, sha, tar_url, sum_url)
PY
)

install_web_release() {
    local releases candidates tag sha tar_url sum_url chosen="" tmp expected actual current
    if ! releases="$(curl -fsSL --max-time 20 -H 'Accept: application/vnd.github+json' \
            "https://api.github.com/repos/$WEB_REPO/releases?per_page=100")"; then
        echo "Web page: GitHub unreachable — keeping the current page."
        return 0
    fi
    if ! candidates="$(printf '%s' "$releases" | "$VENV/bin/python" -c "$PICK_WEB_RELEASE_PY")"; then
        echo "Web page: couldn't read the release list — keeping the current page."
        return 0
    fi
    while read -r tag sha tar_url sum_url; do
        [ -n "$tag" ] || continue
        if git -C "$INSTALL_DIR" merge-base --is-ancestor "$sha" HEAD 2>/dev/null; then
            chosen="$tag"
            break
        fi
    done <<< "$candidates"
    if [ -z "$chosen" ]; then
        echo "Web page: no web release for this code yet — keeping the current page."
        return 0
    fi

    current="$(basename "$(readlink -f "$WEB_CURRENT" 2>/dev/null || true)")"
    if [ "$current" = "$chosen" ] && [ -f "$WEB_RELEASES/$chosen/index.html" ]; then
        echo "Web page: $chosen already installed."
        return 0
    fi

    tmp="$(mktemp -d)"
    if ! curl -fsSL --max-time 120 -o "$tmp/web.tar.gz" "$tar_url" \
            || ! curl -fsSL --max-time 20 -o "$tmp/web.tar.gz.sha256" "$sum_url"; then
        echo "Web page: download of $chosen failed — keeping the current page."
        rm -rf "$tmp"
        return 0
    fi
    expected="$(awk '{print $1}' "$tmp/web.tar.gz.sha256")"
    actual="$(sha256sum "$tmp/web.tar.gz" | awk '{print $1}')"
    if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
        echo "Web page: checksum mismatch for $chosen — keeping the current page."
        rm -rf "$tmp"
        return 0
    fi
    mkdir -p "$tmp/www"
    if ! tar -xzf "$tmp/web.tar.gz" -C "$tmp/www" --no-same-owner || [ ! -f "$tmp/www/index.html" ]; then
        echo "Web page: $chosen archive is broken — keeping the current page."
        rm -rf "$tmp"
        return 0
    fi

    mkdir -p "$WEB_RELEASES"
    rm -rf "${WEB_RELEASES:?}/$chosen"
    mv "$tmp/www" "$WEB_RELEASES/$chosen"
    touch "$WEB_RELEASES/$chosen"  # install time (tar restored the build time) — pruning goes by this
    rm -rf "$tmp"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$WEB_RELEASES/$chosen"
    # Atomic switch: nginx never sees a half-updated page
    ln -sfn "$WEB_RELEASES/$chosen" "$WEB_CURRENT.new"
    chown -h "$SERVICE_USER:$SERVICE_USER" "$WEB_CURRENT.new"
    mv -T "$WEB_CURRENT.new" "$WEB_CURRENT"
    echo "Web page: installed $chosen."

    # Keep the newest $WEB_KEEP releases (never the current one or the placeholder)
    { ls -1dt "$WEB_RELEASES"/web-* 2>/dev/null || true; } | tail -n +$((WEB_KEEP + 1)) | while read -r old; do
        [ "$(basename "$old")" = "$chosen" ] || rm -rf "$old"
    done
}
install_web_release

# ── Web root + nginx ──────────────────────────────────────────────────────────
# nginx serves web-current/ (a web release, or a placeholder until the first one)
# and proxies /api/ to uvicorn, which then listens on 127.0.0.1 only.
if [ ! -e "$WEB_CURRENT" ]; then
    mkdir -p "$WEB_RELEASES/placeholder"
    cp "$INSTALL_DIR/deploy/web-placeholder/index.html" "$WEB_RELEASES/placeholder/"
    ln -sfn "$WEB_RELEASES/placeholder" "$WEB_CURRENT"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$WEB_RELEASES"
    chown -h "$SERVICE_USER:$SERVICE_USER" "$WEB_CURRENT"
fi

UVICORN_HOST="0.0.0.0"  # fallback if nginx can't be set up
if ! command -v nginx &>/dev/null; then
    echo "Installing nginx …"
    apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx
fi
if command -v nginx &>/dev/null; then
    install -m 644 "$INSTALL_DIR/deploy/nginx/pi-controller-proxy.conf" /etc/nginx/snippets/pi-controller-proxy.conf
    install -m 644 "$INSTALL_DIR/deploy/nginx/pi-controller.conf" /etc/nginx/sites-available/pi-controller
    ln -sfn /etc/nginx/sites-available/pi-controller /etc/nginx/sites-enabled/pi-controller
    rm -f /etc/nginx/sites-enabled/default  # its "Welcome to nginx" page also claims port 80
    if nginx -t 2>&1; then
        systemctl enable --quiet nginx
        systemctl reload nginx 2>/dev/null || systemctl restart nginx
        UVICORN_HOST="127.0.0.1"
        echo "nginx serving the web page on port 80."
    else
        rm -f /etc/nginx/sites-enabled/pi-controller
        echo "!!! nginx config test failed — site disabled; API stays on 0.0.0.0:8000 directly."
    fi
else
    echo "!!! nginx not available — API stays on 0.0.0.0:8000 directly."
fi

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
ExecStart=${VENV}/bin/uvicorn backend.main:app --host ${UVICORN_HOST} --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
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
echo ""
LAN_IP="$(hostname -I | awk '{print $1}')"
echo "Web page:   http://$LAN_IP/   (API docs: http://$LAN_IP/api/v1/docs)"
echo "Users:      sudo $INSTALL_DIR/scripts/manage.sh create-user <name> --role admin   (password asked twice)"
echo "Local TUI:  sudo $INSTALL_DIR/scripts/tui.sh"
