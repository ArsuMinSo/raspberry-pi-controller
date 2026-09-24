# Pi Controller

Remote supervisor for Raspberry Pi kiosks on an isolated LAN. Monitor health, execute commands, manage inventory, and deploy SSH keys — all from a terminal UI.

```
┌──────────────────────────────────────────┐
│  Textual TUI (terminal)                  │
└────────────────┬─────────────────────────┘
                 │ HTTP REST
┌────────────────▼─────────────────────────┐
│  FastAPI Backend                         │
│  Paramiko SSH executor (parallel)        │
└────────────────┬─────────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│  PostgreSQL                              │
│  raspberries · actions_log               │
└──────────────────────────────────────────┘
```

---

## Requirements

- Python 3.10+
- PostgreSQL 13+
- An SSH key pair accessible by the controller host
- Pi(s) with SSH enabled and the controller's public key in `~/.ssh/authorized_keys`

---

## Installation

```bash
git clone https://github.com/ArsuMinSo/raspberry-pi-controller.git
cd raspberry-pi-controller

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt    # production
pip install -r requirements-dev.txt  # + dev / test tools
```

### Database

```sql
-- run as postgres superuser
CREATE USER pi_controller WITH PASSWORD 'changeme';
CREATE DATABASE pi_controller OWNER pi_controller;
GRANT ALL ON SCHEMA public TO pi_controller;
```

Then apply the migrations — easiest with `scripts/setup_db.sh` (creates role + DB, then applies pending migrations):

```bash
sudo DB_PASSWORD='…' bash scripts/setup_db.sh
```

Applied migrations are recorded in the `schema_migrations` table, so each runs once. Every migration runs in a single transaction with its record — if it fails, nothing is changed. When migrations are pending on a database that already has tables, a `pg_dump` backup is written to `/var/backups/pi-controller/` first.
 `002_mac_pk.sql` makes MAC the primary key and aborts without changes if any Pi still has the all-zeros placeholder MAC or two Pis share a MAC — fix those rows first.

---

## Configuration

Copy `.env.example` to `.env` and set `DB_PASSWORD`:

```bash
cp .env.example .env
# edit .env → DB_PASSWORD=changeme
```

`config.yaml` is not tracked in git — create it from the template: `cp config.example.yaml config.yaml` (`deploy.sh` does this on first install). Set `PI_CONTROLLER_CONFIG` to use a different path.

Edit `config.yaml` to match your environment:

```yaml
database:
  host: localhost
  port: 5432
  user: pi_controller
  password: ${DB_PASSWORD}   # reads from .env
  db_name: pi_controller
  pool_size: 10

ssh:
  private_key_path: /home/you/.ssh/id_rpi   # RSA, ECDSA, or Ed25519
  username: pi                               # default SSH user on Pis
  timeout_s: 30
  retry_count: 3
  retry_delay_s: 1
  parallel_limit: 50                         # max concurrent SSH sessions

network:
  subnet: 10.10.20.1-10.10.20.254            # CIDR or start-end range
  scan_interval_s: 86400
  probe_ssh: true                            # SSH-probe during discovery
  probe_timeout_s: 5
  probe_username: pi                         # user for probe connections
  probe_auth: key                            # "key" or "password"
  probe_deploy_key: false                    # copy pub key during probe

server:
  host: 0.0.0.0
  port: 8000
  log_level: INFO
  workers: 1

# Optional — commands run on the Pis for fleet actions (defaults shown)
pi_commands:
  reboot: LC_ALL=C nohup sh -c 'sleep 3; systemctl reboot' >/dev/null 2>&1 &   # no sudo: polkit allows logind reboot on Raspberry Pi OS
  throttled: cat /sys/devices/platform/soc/soc:firmware/get_throttled 2>/dev/null || vcgencmd get_throttled
  disk: df -P /
```

`pi_commands` is edited in `config.yaml` only (not via the API/UI), so operators can't change what "reboot" runs.
Reboot is detached (returns at once), so its result is always "ok" — the web page verifies it with a health check
~90 s later (uptime must have reset).

All `network.*` and `ssh.*` settings can be changed live from the TUI Settings screen without restarting the backend.

---

## Running

### Backend

```bash
source .venv/bin/activate
DB_PASSWORD=changeme uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Interactive API docs available at `http://localhost:8000/api/v1/docs`.

**Run exactly one worker.** The task scheduler and runtime settings live inside the process: with more workers every scheduled task runs once per worker, and a Settings change only reaches one of them.

### Users & login

The API requires a login (except `POST /api/v1/auth/login` and `GET /api/v1/health`). Roles: **viewer** (inventory + results; no activity log),
**operator** (+ health check, kill process, restart service, discovery scan), **admin** (everything, incl. running
commands, inventory edits, settings, scheduled tasks, users). Sessions last 12 h. Every action is logged with the
user's name — Pi operations in `actions_log`, everything else (logins, edits, settings, users) in `audit_events`.

Create the first admin on the server (password asked twice, ≥ 12 characters):

```bash
sudo /opt/pi-controller/scripts/manage.sh create-user <name> --role admin
sudo /opt/pi-controller/scripts/manage.sh list-users
sudo /opt/pi-controller/scripts/manage.sh reset-password <name>
```

Design: [`docs/design/web-service.md`](docs/design/web-service.md).

**Try it in the browser:** open `http://<server>/api/v1/docs` → `POST /auth/login` → *Try it out* → copy the
`token` from the response → **Authorize** (top right) → paste the token → every endpoint now runs as you.
Log out with `POST /auth/logout` when done.

### Web page

`http://tv.omnika.home/` (nginx, port 80; or the server's IP) — log in with your account. Ionic + Angular app in `web/`.

- **Inventory:** search, status filter, numeric position sort, CPU/RAM/temp; select Pis → *Health check*
  (operator+) → live progress per Pi.
- **Menu** on the left: pinned open from 768 px wide; drag its right edge to resize (double-click resets); collapse with « (then ☰ opens it), pin again with 📌 — remembered per browser.
- **Fleet** (operator+): selection → *Diagnostics* (throttling / power / disk per Pi) or *Reboot* (confirm; a health
  check ~90 s later shows per Pi whether it really rebooted). Summary strip above the list: counts, stale Pis
  (click to select), hottest Pi, last health check.
- **Users** (admin): create (password twice, *must change at first login* on by default), change role, disable/enable,
  reset password, end sessions. Never deleted — disabled instead; the last active admin is protected.
- **Pi detail**, **Activity log** (operator+; Pi actions + logins/changes), **Account** (change password — entered twice —,
  sessions, logout). Accounts flagged *must change password* go to Account first.
- Session lives in the browser tab (sessionStorage), 12 h max.

**Develop:** `cd web && npm ci && npm start` → `http://localhost:4200`, `/api` proxied to the server
(`web/proxy.conf.json`). Tests: `npm test`. Build: `npm run build` → `web/www`.

**Release** (from a dev machine with `gh` logged in; working tree clean and pushed):

```bash
bash scripts/release_web.sh      # builds web/, publishes GitHub release web-<date>-<sha> (tar.gz + .sha256)
```

The server picks it up on the next `sudo ./scripts/deploy.sh`: it installs the newest `web-*` release whose commit
is part of the deployed code (so the page is never newer than the API), verifies the checksum, switches
`/opt/pi-controller/web-current` atomically and keeps the last 3. Offline / no release → keeps the current page.

### TUI (local break-glass)

The TUI is the backup way in: it runs **on the controller itself, with sudo**, has admin rights, and needs no
account — it reads the key `/opt/pi-controller/.tui-key` (created by `deploy.sh`, mode 600) and talks to the backend
on `127.0.0.1`. Its actions are logged as `local-tui (<your unix user>)`. It works even if every web account is
locked, and it can't be used over the network.

```bash
sudo /opt/pi-controller/scripts/tui.sh
```

Rotate the key with `sudo /opt/pi-controller/scripts/manage.sh rotate-tui-key`.

Run it from the project venv, not the system Python — distro packages can be far older (Ubuntu 25.04 ships Textual 2.1.1; the TUI needs ≥ 8, see `requirements.txt`) and fail with `MarkupError` or `Error in stylesheet`. Create the venv with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (`scripts/run_tests.sh` also creates it).

Press `q` to quit. Ctrl+C is intentionally ignored to prevent accidental exit.

### Server deploy / update

```bash
sudo bash scripts/deploy.sh
```

Installs to `/opt/pi-controller` as a systemd service; re-run it to update. **Settings persist across updates:**

- `.env` (`DB_PASSWORD`) is gitignored and never overwritten — it's only created on first install. The password is asked **3 times** and all entries must match; it may not contain a single quote (`'`).
- `config.yaml` (edited by the Settings screen) is gitignored too. It is backed up to `config.yaml.bak-<timestamp>` (newest 10 kept) before `git pull`, then rebuilt from `config.example.yaml` + the backup: your existing values win, and any new options added by the update get their defaults. On first install it is copied from `config.example.yaml` — review the SSH key path, username and subnet.

**nginx:** `deploy.sh` installs nginx and serves everything on **port 80**: the web page at `/` (from
`/opt/pi-controller/web-current`, a placeholder until the first web release) and the API at `/api/` (proxied to
uvicorn, which listens on `127.0.0.1:8000` only). nginx rate-limits logins per IP, adds security headers, overwrites
`X-Forwarded-For` (so the backend sees the real client IP) and strips the TUI key header. Config:
`deploy/nginx/`. If `nginx -t` fails, the site is disabled and uvicorn stays reachable on `0.0.0.0:8000`.

**Database updates:** only new migrations run, after a `pg_dump` backup to `/var/backups/pi-controller/` (newest 10 kept). If one fails, it is rolled back, the code in `/opt/pi-controller` is reset to the previous version, and the service is not restarted — it keeps running the old version on the unchanged database.

---

## TUI Tutorial

### Home — Inventory Grid

The main screen. Lists all Pis with position, hostname, IP, MAC, status, Pi version, CPU/RAM/temp, Pi time, uptime, tags, and last-seen time. Pi time and uptime are populated by a health check (`h`) and blank until one has run.

| Key | Action |
|-----|--------|
| `r` | Refresh inventory |
| `Space` | Toggle selection on current row |
| `a` | Select all |
| `A` | Deselect all |
| `n` | Add new Pi (opens form) |
| `e` | Edit Pi under cursor |
| `d` | Delete selected Pi(s) — shows confirmation dialog |
| `x` | Execute command on selected Pi(s) |
| `h` | Health check on selected Pi(s) |
| `l` | View action logs |
| `D` | Open Discovery screen |
| `k` | Deploy SSH key to selected Pi(s) |
| `s` | Settings |

**Sorting:** Click any column header to sort ascending. Click again to sort descending. The active column shows ▲ or ▼. IP column sorts numerically (so `.9` comes before `.10`).

**Selection:** Selected Pis are marked ✓. Commands (`x`, `h`, `k`, `d`) operate on the selection. If nothing is selected, they act on the row under the cursor.

**Deletion safety:** Pressing `d` always shows a confirmation dialog listing the targets (up to 10, then "… and N more"). Enter confirms, Esc cancels.

---

### Discovery — Scan & Add Pis

Scans a subnet for live hosts, SSH-probes each one for hostname / Pi version / MAC, and lets you add results to the database.

**Open:** Press `D` from Home.

| Key | Action |
|-----|--------|
| `s` | Start scan |
| `Space` | Toggle selection on current row |
| `a` | Bulk-add selected rows (or single-add row under cursor) |
| `Esc` | Back |

Click any column header to sort results (selections survive the sort).

#### Scan range

Enter **From** and **To** IPs (e.g. `10.10.30.1` → `10.10.30.254`). Press **Save** to persist the range, or **Scan** to save-and-scan in one step. Accepts a CIDR block in `config.yaml` or a start–end range in the UI.

#### Probe settings

Visible when *SSH probe* is checked:

| Field | Description |
|-------|-------------|
| User | SSH username for probe connections |
| Key / Password | Auth method for probing. Key uses `config.yaml` key path. Password is entered here and never saved to disk. |
| Deploy key | Only shown for Password auth. Copies the controller's public key to `~/.ssh/authorized_keys` on each Pi during the probe — one-pass setup for key auth. |

#### Adding discovered Pis

- **Single add** (`a` with no selection): Opens the Add Pi form pre-filled with IP, hostname, Pi version, and MAC. Position defaults to the next free `00-NNN` uncategorised slot.
- **Bulk add** (`a` with rows selected): Assigns sequential `00-NNN` positions automatically. Skips Pis whose MAC is already registered in the database and reports skip reasons. Pis with no MAC (e.g. scanned without SSH probe) are skipped with a warning — MAC is required.

After a scan, already-registered Pis with matching IPs have their hostname, MAC, Pi version, and serial refreshed automatically. Pis that did not respond are marked `unreachable`.

---

### Execute — Run Commands

Runs a shell command on selected Pis in parallel via SSH.

**Open:** Select Pis on Home → press `x`.

Type a command and press **Enter**. Results appear in a table showing exit code, stdout preview, and stderr preview per Pi.

| Field | Description |
|-------|--------------|
| Sudo | Runs the command as root. Enter a password to have it piped to `sudo -S` non-interactively; leave blank to run bare `sudo <command>` (only works if the Pi user has passwordless sudo). |
| Detach | Backgrounds the command (`nohup … & disown`) so the SSH call returns immediately instead of waiting for it to finish. Needed for `reboot`, `shutdown`, or anything long-running. |

Max concurrent SSH sessions is read from **Settings** (`s` on Home → Parallel) — same `ssh.parallel_limit` used by health checks and discovery.

| Key | Action |
|-----|--------|
| `v` / `Enter` | View full stdout/stderr for row under cursor |
| `Esc` | Back |

Results are shown once all Pis respond. Failed Pis show the error reason (auth failure, timeout, etc.).

---

### Health Check

Collects CPU load %, RAM%, temperature, and the Pi's clock/uptime (both parsed from a single `uptime` SSH call) via SSH. Also updates each Pi's hostname, MAC, Pi version, and serial in the database from live values. Pi Time and Uptime are also shown as columns on the Home grid once a health check has run.

**Open:** Select Pis on Home → press `h`.

| Key | Action |
|-----|--------|
| `t` | Trigger check on all Pis |
| `Esc` | Back |

If Pis were selected on Home the check runs immediately on those. Press `t` to check every reachable Pi instead.

Health checks run in parallel. After completion:
- Reachable → status set to `reachable`, `last_seen` refreshed, hardware fields (hostname, MAC, Pi version, serial) updated from live data
- Unreachable → status set to `unreachable`

---

### Deploy Key

Installs the controller's SSH public key on one or more Pis using password authentication — equivalent to `ssh-copy-id`. Use this during initial setup before switching to key auth.

**Open:** Select Pi(s) on Home → press `k`.

Enter the SSH password for the target Pi(s) and press **Deploy Key**. Results show per-Pi success or failure with the error reason.

---

### Logs

Append-only audit log of every action — commands, health checks, discoveries, key deployments. Nothing is ever deleted.

**Open:** Press `l` from Home. If Pi(s) are selected on Home, Logs opens pre-filtered to those Pi(s).

| Key | Action |
|-----|--------|
| `v` / `Enter` | View full stdout/stderr for selected row |
| `f` | Toggle the selected-Pi(s) filter on/off |
| `m` | Load more entries (fetch limit +300, capped at 1000) |
| `r` | Refresh |
| `Esc` | Back |

---

### Settings

Live-edit SSH and network config without restarting the backend. Changes are saved to `config.yaml` and take effect immediately. They are kept when the server is updated with `deploy.sh`.

**Open:** Press `s` from Home.

| Field | Description |
|-------|-------------|
| SSH key path | Path to private key on the controller host |
| SSH username | Default user for command/health SSH sessions |
| SSH timeout | Per-connection timeout in seconds |
| Retry count | SSH retry attempts on failure |
| Retry delay | Seconds between retries |
| Parallel | Max concurrent SSH sessions — applies to health checks, discovery, and Execute (`ssh.parallel_limit`) |

Use **Test connection** to verify SSH access to a specific IP before saving.

---

## Position Format

Every Pi has a **position**, either:

- a plain number, 1–10 digits (e.g. `42`), or
- the legacy room-unit slot `XX-YYY` (e.g. `01-003` = room 1, unit 3; `00` = uncategorised)

Positions are unique and renameable (edit the Pi). They identify Pis in the UI and API paths.

The **MAC address** is the database primary key: it is required, must be unique, and cannot be the all-zeros placeholder. A health check updates a Pi's MAC from the live device unless another Pi already holds that MAC (logged as a warning and skipped).

Newly discovered Pis that haven't been assigned a room yet get an auto-assigned `00-NNN` slot.

---

## SSH Key Setup

Generate a dedicated key pair:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_rpi -C "pi-controller"
```

Then distribute it to Pis using one of these methods:

**Option A — Manual:**
```bash
ssh-copy-id -i ~/.ssh/id_rpi.pub pi@10.10.20.x
```

**Option B — Deploy Key screen:** Add the Pi to inventory with its IP, select it on Home, press `k`, enter the Pi's password.

**Option C — Discovery + Deploy key:** In the Discovery screen, set probe auth to *Password*, enter the Pi password, enable *Deploy key*, run a scan. The controller probes each host and deploys the key in a single pass.

---

## Running Tests

```bash
bash scripts/run_tests.sh          # all tests
bash scripts/run_tests.sh -k mac   # extra args go to pytest
```

Run it on any machine with a local PostgreSQL server, including the production server: it only uses the separate `pi_test` role and `pi_controller_test` database, never `pi_controller`. On first run it creates the role `pi_test` and database `pi_controller_test` (uses `sudo -u postgres`) and a `.venv` with dev dependencies. SSH is mocked, so no live Pis are needed.

The fixture drops and recreates tables from `migrations/*.sql`, so the script refuses any `TEST_DATABASE_URL` whose database isn't `pi_controller_test`. The tests also skip the task scheduler at app startup (`PI_CONTROLLER_DISABLE_SCHEDULER=1`, set in `tests/conftest.py`), and the script unsets `DB_PASSWORD`, so nothing in a test run can reach the real `pi_controller` database.

---

## Project Structure

```
pi-controller/
├── backend/
│   ├── main.py              FastAPI app, route registration
│   ├── config.py            YAML loader, runtime overrides (persist to disk)
│   ├── database.py          SQLAlchemy engine, session factory
│   ├── models.py            Pi, ActionLog ORM models
│   ├── schemas.py           Pydantic request/response schemas
│   ├── routes/
│   │   ├── pi.py            /pi/* — CRUD, bulk add, deploy-key
│   │   ├── health.py        /health/* — trigger + results
│   │   ├── command.py       /command/* — execute + results
│   │   ├── process.py       /process/kill
│   │   ├── service.py       /service/restart
│   │   ├── logs.py          /logs — audit log query
│   │   ├── discovery.py     /discovery/scan
│   │   └── settings.py      /settings — live config PATCH + SSH test
│   └── services/
│       ├── ssh_executor.py  Paramiko wrapper, parallel execution
│       ├── discovery.py     Ping sweep + parallel SSH probe
│       ├── health_check.py  CPU/mem/disk collection + DB update
│       └── audit_log.py     Append-only action log helpers
├── frontend/
│   ├── main.py              Textual App, screen routing
│   ├── api_client.py        HTTP client for all backend endpoints
│   ├── config.py            Backend URL
│   └── screens/
│       ├── home.py          Inventory grid, sortable columns
│       ├── discovery.py     Subnet scan, probe settings, bulk add
│       ├── execute.py       Command input + parallel results table
│       ├── health.py        Health check results
│       ├── logs.py          Audit log viewer
│       ├── manage_pi.py     Add / edit Pi form (modal)
│       ├── deploy_key.py    SSH key deployment (modal)
│       ├── settings.py      SSH/network settings (modal)
│       ├── confirm.py       Yes/no confirmation dialog (modal)
│       └── detail.py        Full stdout/stderr viewer (modal)
├── tests/
│   ├── conftest.py
│   ├── test_api_routes.py
│   ├── test_database.py
│   └── test_ssh_executor.py
├── config.example.yaml      Config template (copy to config.yaml — gitignored, edited by Settings screen)
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## API Reference

Everything is under **`/api/v1`**. Full interactive docs at `http://localhost:8000/api/v1/docs`.
All endpoints need `Authorization: Bearer <token>` from `POST /api/v1/auth/login`, except login and `GET /health`.
Minimum role in the last column.

**Long operations run in the background** (health check, execute, kill, restart, discovery): the `POST` returns
`{action_id, status: "queued"}` at once; poll `GET /actions/{action_id}` (~1 s) — per-Pi results appear as each Pi
finishes (`done`/`total`), `finished: true` at the end. Jobs cut off by a backend restart are marked `interrupted`.

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `POST` | `/auth/login` | Username + password → 12 h session token | public |
| `POST` | `/auth/logout` | End this session | any |
| `GET` | `/auth/me` | Current user | any |
| `POST` | `/auth/me/password` | Change own password (current + new twice) | any |
| `GET`/`DELETE` | `/auth/me/sessions[/{id}]` | List / end own sessions | any |
| `GET`/`POST` | `/users` | List / create users | admin |
| `PATCH` | `/users/{id}` | Change role, enable/disable (disable ends sessions) | admin |
| `POST` | `/users/{id}/password` | Reset password (ends sessions) | admin |
| `POST` | `/users/{id}/revoke-sessions` | Log a user out everywhere | admin |
| `GET` | `/health` | Backend + DB liveness | public |
| `GET` | `/actions/{action_id}` | Progress + per-Pi results of any background action | viewer |
| `POST` | `/pi/reboot` | Reboot selected Pis (background; see `pi_commands.reboot`) | operator |
| `POST` | `/diagnostics` | Throttling/under-voltage flags + root disk usage per Pi (background) | operator |
| `GET` | `/fleet/summary?stale_hours=24` | Counts, stale / never-seen Pis, top 5 by temp / CPU / RAM (DB only) | viewer |
| `GET` | `/pi/list` | List Pis (status/tags/version filter, paginated) | viewer |
| `GET` | `/pi/{position}/status` | Single Pi detail | viewer |
| `POST` | `/pi` | Create Pi | admin |
| `PATCH` | `/pi/{position}` | Update Pi fields | admin |
| `DELETE` | `/pi/{position}` | Delete Pi | admin |
| `POST` | `/pi/bulk` | Bulk create with MAC deduplication | admin |
| `POST` | `/pi/deploy-key` | Deploy SSH public key via password auth | admin |
| `POST` | `/command/execute` | Run shell command on Pis | admin |
| `GET` | `/command/{action_id}` | Get command results | viewer |
| `POST` | `/process/kill` | Kill process by name (SIGTERM or SIGKILL) | operator |
| `POST` | `/service/restart` | Restart systemd unit | operator |
| `POST` | `/health/trigger` | Trigger health check (selected or all) | operator |
| `GET` | `/health/{action_id}` | Get health check results | viewer |
| `POST` | `/discovery/scan` | Scan subnet, probe Pis, update DB (background → `action_id`) | operator |
| `GET` | `/discovery/scan/{action_id}` | Discovery result | viewer |
| `GET` | `/logs` | Pi operations log (actions_log) | operator |
| `GET` | `/logs/events` | Logins, edits, settings, user changes (audit_events) | operator |
| `GET` | `/tasks` | Scheduled tasks | operator |
| `POST`/`PATCH`/`DELETE` | `/tasks[/{id}]` | Manage scheduled tasks | admin |
| `GET` | `/settings` | Get current SSH + network config | admin |
| `PATCH` | `/settings` | Update config (persisted to config.yaml) | admin |
| `POST` | `/settings/test` | Test SSH connection to IP | admin |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2 |
| Database | PostgreSQL (psycopg2-binary) |
| SSH | Paramiko (parallel via ThreadPoolExecutor) |
| TUI | Textual |
| HTTP client | requests |
| Config | PyYAML + python-dotenv |
| Tests | pytest + httpx |
