# Pi Controller

Remote supervisor for 50–250 Raspberry Pi kiosks on an isolated LAN. Monitor status, run commands, restart services, and check health — all from a terminal UI.

## Architecture

```
Textual TUI  ──HTTP──▶  FastAPI backend  ──SSH──▶  Raspberry Pis
                              │
                         PostgreSQL
```

## Requirements

- Python 3.11+
- PostgreSQL 15+
- SSH key pre-distributed to all Pis

## Setup

### 1. Clone and create virtualenv

```bash
git clone https://github.com/ArsuMinSo/raspberry-pi-controller
cd raspberry-pi-controller
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. PostgreSQL

```bash
sudo -u postgres psql -c "CREATE USER pi_controller WITH PASSWORD 'yourpassword';"
sudo -u postgres psql -c "CREATE DATABASE pi_controller OWNER pi_controller;"
sudo -u postgres psql -d pi_controller -c "GRANT ALL ON SCHEMA public TO pi_controller;"
psql postgresql://pi_controller:yourpassword@localhost/pi_controller -f migrations/001_init.sql
```

### 3. Config

```bash
cp .env.example .env
# edit .env — set DB_PASSWORD
```

`config.yaml` controls SSH key path, subnet, server port, etc. Defaults work for most setups.

### 4. SSH key

The backend SSHes into Pis as the `pi` user using a key at `~/.ssh/id_rsa` (configurable in `config.yaml`). Distribute the public key to all Pis before use.

## Running

**Terminal 1 — backend:**
```bash
DB_PASSWORD=yourpassword .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — TUI:**
```bash
.venv/bin/python frontend/main.py
```

Or as a systemd service — see `systemd/pi-controller.service`.

## TUI Keys

| Key | Action |
|-----|--------|
| `Space` | Select / deselect Pi |
| `a` | Select all |
| `A` | Deselect all |
| `x` | Execute command on selected Pis |
| `h` | Health check screen |
| `l` | Logs screen |
| `r` | Refresh current screen |
| `Esc` | Back |
| `q` | Quit |

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/pi/list` | List all Pis (filterable) |
| `GET` | `/pi/{position}/status` | Single Pi status |
| `POST` | `/command/execute` | Run SSH command |
| `GET` | `/command/{id}` | Get command results |
| `POST` | `/process/kill` | Kill process by name |
| `POST` | `/service/restart` | Restart systemd unit |
| `POST` | `/health/trigger` | Trigger health check |
| `GET` | `/health/{id}` | Get health results |
| `GET` | `/logs` | Query audit log |
| `POST` | `/discovery/scan` | Scan subnet for new Pis |
| `GET` | `/health` | Backend health check |

Interactive docs: `http://localhost:8000/docs`

## Development

```bash
pip install -r requirements-dev.txt

# run tests (requires PostgreSQL test DB)
sudo -u postgres psql -c "CREATE DATABASE pi_controller_test OWNER pi_controller;"
sudo -u postgres psql -d pi_controller_test -c "GRANT ALL ON SCHEMA public TO pi_controller;"
DB_PASSWORD=yourpassword python -m pytest tests/ -v
```

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy, Paramiko, PostgreSQL
- **Frontend:** Textual (TUI)
- **SSH:** serial execution v1 (parallel in v2)
