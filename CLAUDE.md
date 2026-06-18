# Pi Controller - Claude Code Working Memory

## Project Overview

**Goal:** Remote supervisor for 50–250 Raspberry Pi kiosks on isolated LAN (10.10.20.0/24).

**Core function:** Monitor, manage, and execute commands on RPis via SSH from central Ubuntu server.

**Status:** Design phase (locked functional requirements).

---

## Tech Stack (LOCKED)

- **Backend:** Python + FastAPI + Paramiko + PostgreSQL
- **Frontend:** Python + PyRatatui (TUI)
- **Config:** YAML
- **Auth:** None (localhost trust)
- **Deployment:** Ubuntu, systemd service
- **Concurrency v1:** Serial SSH (parallelize v2)

---

## Architecture

```
┌──────────────────────────────────────────┐
│ PyRatatui TUI Client (Python)            │
│ ├─ Home: inventory grid                  │
│ ├─ Select: multi-select Pis              │
│ ├─ Execute: command input                │
│ ├─ Monitor: progress                     │
│ └─ Logs: action history                  │
└────────────────┬─────────────────────────┘
                 │ HTTP REST
                 ▼
┌──────────────────────────────────────────┐
│ FastAPI Backend (Python)                 │
│ ├─ /pi/* (inventory + status)            │
│ ├─ /command/* (execute, logs)            │
│ ├─ /discovery/* (scan subnet)            │
│ ├─ /health (trigger, get stats)          │
│ └─ Paramiko SSH executor (serial)        │
└────────────────┬─────────────────────────┘
                 │
                 ▼
     ┌───────────────────────┐
     │ PostgreSQL            │
     │ ├─ raspberries        │
     │ └─ actions_log        │
     └───────────────────────┘
```

---

## Database Schema (Phase 1)

### Table: `raspberries`

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PRIMARY KEY | Auto, sole unique identifier |
| mac | VARCHAR(17) | xx:xx:xx:xx:xx:xx — NOT unique |
| serial | VARCHAR(255) | RPi /proc/cpuinfo serial, informational |
| hostname | VARCHAR(255) | Linux hostname on device |
| position | VARCHAR(6) UNIQUE | Room-unit slot e.g. "01-003" |
| pi_version | INT | 2/3/4/5 |
| current_ip | INET | Last known IP |
| status | VARCHAR(20) | reachable/unreachable |
| last_seen | TIMESTAMP | Last SSH success |
| tags | TEXT[] | Array of tags (e.g., ["kiosk", "floor1"]) |
| created_at | TIMESTAMP | Discovery time |
| updated_at | TIMESTAMP | Last update |

**Indexes:** (status), (tags GIN), (position)

### Table: `actions_log`

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PRIMARY KEY | Auto |
| timestamp | TIMESTAMP | When action ran |
| user | VARCHAR(255) | Admin (v1: always "admin") |
| pis_selected | TEXT[] | Array of position strings e.g. ["01-003"] |
| action | VARCHAR(50) | kill/restart/execute/health/status |
| command | TEXT | Full command executed |
| exit_code | INT | SSH exit code (null if timeout) |
| stdout | TEXT | Raw command output |
| stderr | TEXT | Error output |
| status | VARCHAR(20) | success/fail/partial_fail |
| retry_count | INT | How many retries (0–3) |
| duration_ms | INT | Execution time |

**Indexes:** (timestamp), (user), (status)

**Constraint:** Append-only (no deletes).

---

## API Endpoints (Phase 1)

### Inventory & Status

- `GET /pi/list` → List all Pis (paginated, filterable)
  - Query: `?status=reachable&tags=floor1&version=4`
  - Response: `[{id, mac, hostname, position, ip, status, last_seen, tags}, ...]`

- `GET /pi/{position}/status` → Get single Pi status by position (e.g. 01-003)
  - Response: `{id, mac, hostname, position, ip, status, last_seen}`

### Health Check

- `POST /health/trigger` → Trigger check on selected Pis
  - Body: `{pis: ["01-003", "02-010"], ...}` or `{all: true}`
  - Response: `{action_id, status: "queued"}`

- `GET /health/{action_id}` → Get health check results
  - Response: `{action_id, status, results: [{position, cpu, mem, disk}, ...], started_at, completed_at}`

### Command Execution

- `POST /command/execute` → Run command on Pis
  - Body: `{pis: ["01-003"], command: "ps aux"}`
  - Response: `{action_id, status: "queued"}`

- `GET /command/{action_id}` → Get execution progress/results
  - Response: `{action_id, status, results: [{position, exit_code, stdout, stderr}, ...], started_at, completed_at}`

### Process/Service Management

- `POST /process/kill` → Kill process by name
  - Body: `{pis: ["01-003"], process_name: "chromium", signal: "SIGTERM|SIGKILL"}`
  - Response: `{action_id, ...}`

- `POST /service/restart` → Restart systemd unit
  - Body: `{pis: ["01-003"], service: "kiosk.service"}`
  - Response: `{action_id, ...}`

### Action Logs

- `GET /logs?pi={position}&user=admin&since=2025-01-01&limit=100` → Query audit log
  - Response: `[{id, timestamp, user, pis, action, command, exit_code, status}, ...]`

### Discovery

- `POST /discovery/scan` → Scan subnet (10.10.20.0/24)
  - Response: `{action_id, status: "running"}`

- `GET /discovery/scan/{action_id}` → Get scan results
  - Response: `{status, discovered: [{ip, mac, hostname, pi_version}, ...], added: N, updated: N}`

### System

- `GET /health` → Backend health check
  - Response: `{status: "ok", db: "ok", uptime_s: 3600}`

---

## Config Schema (YAML)

```yaml
# config.yaml

# Database
database:
  host: localhost
  port: 5432
  user: pi_controller
  password: ${DB_PASSWORD}  # env var
  db_name: pi_controller
  pool_size: 10

# SSH
ssh:
  private_key_path: /home/pi_controller/.ssh/id_rsa
  username: pi
  timeout_s: 30
  retry_count: 3
  retry_delay_s: 1
  parallel_limit: 1  # v1: serial (v2: increase)

# Network
network:
  subnet: 10.10.20.0/24
  scan_interval_s: 86400  # 1x/day

# Server
server:
  host: 0.0.0.0
  port: 8000
  log_level: INFO
  workers: 4
```

---

## Project Structure

```
pi-controller/
├── backend/
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # YAML loader + settings
│   ├── database.py             # SQLAlchemy setup, migrations
│   ├── models.py               # ORM models (Pi, ActionLog)
│   ├── schemas.py              # Pydantic schemas (request/response)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── pi.py               # /pi/* endpoints
│   │   ├── health.py           # /health/* endpoints
│   │   ├── command.py          # /command/* endpoints
│   │   ├── process.py          # /process/* endpoints
│   │   ├── service.py          # /service/* endpoints
│   │   ├── logs.py             # /logs endpoints
│   │   └── discovery.py        # /discovery/* endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ssh_executor.py     # Paramiko wrapper, serial SSH
│   │   ├── discovery.py        # Ping + SSH probe
│   │   ├── health_check.py     # CPU/mem/disk extraction
│   │   └── audit_log.py        # Audit logging
│   └── utils/
│       ├── __init__.py
│       └── helpers.py          # Parsing, filtering
├── frontend/
│   ├── main.py                 # PyRatatui app entry
│   ├── config.py               # Config loader
│   ├── api_client.py           # HTTP requests to backend
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── home.py             # Inventory grid
│   │   ├── select.py           # Multi-select
│   │   ├── execute.py          # Command input
│   │   ├── monitor.py          # Progress
│   │   ├── logs.py             # History
│   │   └── health.py           # Health check
│   └── utils/
│       ├── __init__.py
│       └── formatters.py       # Status colors, formatting
├── config.yaml                 # Main config
├── requirements.txt            # Python deps
├── requirements-dev.txt        # Dev deps (pytest, etc.)
├── .env.example                # Template for env vars
├── README.md
├── DEPLOYMENT.md               # Setup guide
└── tests/
    ├── __init__.py
    ├── test_ssh_executor.py
    ├── test_api_routes.py
    └── test_database.py
```

---

## Locked Decisions

**No rollback/versioning** (git exists but not used for Pi management)
**No deployments** (supervisor only: restart, health, execute)
**Serial SSH v1** (parallelize v2)
**Retry 3x immediate** on fail
**No process health thresholds** (raw stats only)
**Process kill: error if missing** (not silent)
**Service restart: error if missing** (not silent)
**Trust admin** (no shell sanitization)
**Single user (admin)** (multi-user v2)
**Subnet scan every run** (10.10.20.0/24)
**Health check 1x/day cron + manual callable**
**Unreachable Pi: mark unreachable (expected if powered off)**
**IP change (same MAC): update IP, mark reachable**
**Pi identified by position (XX-XXX room-unit), not MAC — MAC not unique**

---

## Key Libraries

- **FastAPI** — REST framework
- **SQLAlchemy** — ORM
- **psycopg2** — PostgreSQL adapter
- **Paramiko** — SSH executor
- **PyRatatui** — TUI framework
- **requests** — HTTP client (frontend)
- **pyyaml** — Config parsing

---

## Next Steps (Phase 1 → 2)

1. Finalize DB schema (above)
2. Finalize API endpoints (above)
3. Finalize config schema (above)
4. Create PostgreSQL database + tables (SQL)
5. Create FastAPI app skeleton + routes
6. Implement SSH executor (Paramiko)
7. Implement audit logging
8. Test backend API
9. Build PyRatatui TUI
10. Integration test
11. Deploy to Ubuntu

---

## Notes

- **VNC access:** Low priority, enabled externally (not controller's job)
- **Alerts:** UI + beep (v2, low priority)
- **SSH key distribution:** Script-based, one-time setup
- **No auth:** Localhost only (change later if exposed)
- **Logs:** DB (immutable, queryable) + file (debug)

---

## References

- Functional Requirements: See conversation history
- Roadmap: 8 weeks serial (1 week design + 2 backend + 2 frontend + 1 integration + 1 testing + 1 deploy)
