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

Tables are created automatically on first backend start.

---

## Configuration

Copy `.env.example` to `.env` and set `DB_PASSWORD`:

```bash
cp .env.example .env
# edit .env → DB_PASSWORD=changeme
```

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
  workers: 4
```

All `network.*` and `ssh.*` settings can be changed live from the TUI Settings screen without restarting the backend.

---

## Running

### Backend

```bash
source .venv/bin/activate
DB_PASSWORD=changeme uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Interactive API docs available at `http://localhost:8000/docs`.

### TUI

```bash
source .venv/bin/activate
python -m frontend.main
```

Press `q` to quit. Ctrl+C is intentionally ignored to prevent accidental exit.

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
- **Bulk add** (`a` with rows selected): Assigns sequential `00-NNN` positions automatically. Skips Pis whose MAC is already registered in the database and reports skip reasons.

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
| Parallel | Max concurrent SSH sessions for this run (default 10, capped at 100). Independent of the backend's `ssh.parallel_limit` — this controls how many Pis the TUI dispatches to at once for this command. |

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

Live-edit SSH and network config without restarting the backend. Changes are saved to `config.yaml` and take effect immediately.

**Open:** Press `s` from Home.

| Field | Description |
|-------|-------------|
| SSH key path | Path to private key on the controller host |
| SSH username | Default user for command/health SSH sessions |
| SSH timeout | Per-connection timeout in seconds |

Use **Test connection** to verify SSH access to a specific IP before saving.

---

## Position Format

Every Pi has a **position** — a 6-character slot `XX-YYY`:

| Part | Meaning |
|------|---------|
| `XX` | Room / zone (01–99, or 00 for uncategorised) |
| `YYY` | Unit number within that zone (001–999) |

Example: `01-003` = room 1, unit 3.

Positions are unique. MACs are not (Pi models share prefixes, or a device may be re-imaged). The position is the primary identifier for all operations.

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
source .venv/bin/activate
pytest tests/ -v
```

Tests use an in-memory SQLite database and mocked SSH. No live Pis or running PostgreSQL required.

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
├── config.yaml              Main configuration (edited by Settings screen)
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## API Reference

Full interactive docs at `http://localhost:8000/docs`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Backend + DB liveness |
| `GET` | `/pi/list` | List Pis (status/tags/version filter, paginated) |
| `GET` | `/pi/{position}/status` | Single Pi detail |
| `POST` | `/pi` | Create Pi |
| `PATCH` | `/pi/{position}` | Update Pi fields |
| `DELETE` | `/pi/{position}` | Delete Pi |
| `POST` | `/pi/bulk` | Bulk create with MAC deduplication |
| `POST` | `/pi/deploy-key` | Deploy SSH public key via password auth |
| `POST` | `/command/execute` | Run shell command on Pis |
| `GET` | `/command/{action_id}` | Get command results |
| `POST` | `/process/kill` | Kill process by name (SIGTERM or SIGKILL) |
| `POST` | `/service/restart` | Restart systemd unit |
| `POST` | `/health/trigger` | Trigger health check (selected or all) |
| `GET` | `/health/{action_id}` | Get health check results |
| `POST` | `/discovery/scan` | Scan subnet, probe Pis, update DB |
| `GET` | `/logs` | Query audit log |
| `GET` | `/settings` | Get current SSH + network config |
| `PATCH` | `/settings` | Update config (persisted to config.yaml) |
| `POST` | `/settings/test` | Test SSH connection to IP |

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
