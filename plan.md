# Pi Controller — Backend Implementation Plan

> Scope: DB + ORM + Pydantic DTOs + FastAPI API + Services + Tests  
> Excluded: TUI (PyRatatui frontend)  
> Stack: Python 3.11, FastAPI, SQLAlchemy 2.x, psycopg2, Paramiko, PostgreSQL 15

---

## Table of Contents

1. [Directory Skeleton](#1-directory-skeleton)
2. [Dependencies](#2-dependencies)
3. [Configuration Layer](#3-configuration-layer)
4. [Database Layer](#4-database-layer)
5. [ORM Models](#5-orm-models)
6. [Pydantic DTOs / Schemas](#6-pydantic-dtos--schemas)
7. [Services Layer](#7-services-layer)
8. [API Routes](#8-api-routes)
9. [FastAPI App Assembly](#9-fastapi-app-assembly)
10. [Error Handling](#10-error-handling)
11. [Tests](#11-tests)
12. [Deployment Artifacts](#12-deployment-artifacts)
13. [Implementation Order](#13-implementation-order)

---

## 1. Directory Skeleton

```
pi-controller/
├── backend/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app + lifespan
│   ├── config.py                  # YAML + env loader → Settings dataclass
│   ├── database.py                # Engine, SessionLocal, Base, get_db()
│   ├── models.py                  # SQLAlchemy ORM: Pi, ActionLog
│   ├── schemas.py                 # All Pydantic DTOs (requests + responses)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── pi.py                  # GET /pi/list, GET /pi/{mac}/status
│   │   ├── health.py              # POST /health/trigger, GET /health/{action_id}
│   │   ├── command.py             # POST /command/execute, GET /command/{action_id}
│   │   ├── process.py             # POST /process/kill
│   │   ├── service.py             # POST /service/restart
│   │   ├── logs.py                # GET /logs
│   │   └── discovery.py           # POST /discovery/scan, GET /discovery/scan/{action_id}
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ssh_executor.py        # Paramiko wrapper, serial execution, retry logic
│   │   ├── discovery.py           # Subnet ping + SSH probe + upsert inventory
│   │   ├── health_check.py        # Remote CPU/mem/disk extraction via SSH
│   │   └── audit_log.py           # Write + query actions_log
│   └── utils/
│       ├── __init__.py
│       └── helpers.py             # MAC normaliser, IP validator, pagination
├── migrations/
│   └── 001_init.sql               # DDL: create tables, indexes, constraints
├── config.yaml
├── .env.example
├── requirements.txt
├── requirements-dev.txt
└── tests/
    ├── __init__.py
    ├── conftest.py                 # pytest fixtures: test DB, mock SSH
    ├── test_ssh_executor.py
    ├── test_api_routes.py
    └── test_database.py
```

---

## 2. Dependencies

### `requirements.txt`

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
paramiko==3.4.1
pyyaml==6.0.2
pydantic==2.9.2
pydantic-settings==2.5.2
python-dotenv==1.0.1
```

### `requirements-dev.txt`

```
pytest==8.3.3
pytest-asyncio==0.24.0
httpx==0.27.2          # TestClient for FastAPI
pytest-postgresql==6.1.1
factory-boy==3.3.1
respx==0.21.1
```

---

## 3. Configuration Layer

### `backend/config.py`

**Goal:** Load `config.yaml`, interpolate `${ENV_VAR}` references, expose typed `Settings` object. Singleton — loaded once at startup.

**Implementation steps:**
1. Read `config.yaml` with PyYAML
2. Walk the loaded dict, replace `${VAR}` strings with `os.environ[VAR]` (raise on missing)
3. Define `Settings` as a plain Python dataclass (not pydantic-settings — config is YAML-first)
4. Expose `get_settings() -> Settings` cached with `functools.lru_cache`

**Settings fields (typed):**

```python
@dataclass
class DatabaseSettings:
    host: str
    port: int
    user: str
    password: str
    db_name: str
    pool_size: int

@dataclass
class SSHSettings:
    private_key_path: str
    username: str
    timeout_s: int
    retry_count: int          # 0–3
    retry_delay_s: int
    parallel_limit: int       # v1: always 1

@dataclass
class NetworkSettings:
    subnet: str               # CIDR e.g. 10.10.20.0/24
    scan_interval_s: int

@dataclass
class ServerSettings:
    host: str
    port: int
    log_level: str
    workers: int

@dataclass
class Settings:
    database: DatabaseSettings
    ssh: SSHSettings
    network: NetworkSettings
    server: ServerSettings
```

### `config.yaml`

```yaml
database:
  host: localhost
  port: 5432
  user: pi_controller
  password: ${DB_PASSWORD}
  db_name: pi_controller
  pool_size: 10

ssh:
  private_key_path: /home/pi_controller/.ssh/id_rsa
  username: pi
  timeout_s: 30
  retry_count: 3
  retry_delay_s: 1
  parallel_limit: 1

network:
  subnet: 10.10.20.0/24
  scan_interval_s: 86400

server:
  host: 0.0.0.0
  port: 8000
  log_level: INFO
  workers: 4
```

### `.env.example`

```
DB_PASSWORD=changeme
```

---

## 4. Database Layer

### `migrations/001_init.sql`

Raw SQL — run once on fresh PostgreSQL. No Alembic (overkill for v1 with locked schema).

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── raspberries ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raspberries (
    id          SERIAL PRIMARY KEY,
    mac         VARCHAR(17)  NOT NULL,           -- xx:xx:xx:xx:xx:xx (lowercase, not unique)
    serial      VARCHAR(255),                    -- /proc/cpuinfo Serial, informational
    hostname    VARCHAR(255),                    -- Linux hostname on the Pi
    position    VARCHAR(6)   NOT NULL UNIQUE,    -- room-unit slot, e.g. "01-003"
    pi_version  SMALLINT,                        -- 2/3/4/5
    current_ip  INET,
    status      VARCHAR(20)  NOT NULL DEFAULT 'unreachable'
                    CHECK (status IN ('reachable', 'unreachable')),
    last_seen   TIMESTAMP,
    tags        TEXT[]       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raspberries_status   ON raspberries (status);
CREATE INDEX IF NOT EXISTS idx_raspberries_tags     ON raspberries USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_raspberries_position ON raspberries (position);

-- ─── actions_log ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS actions_log (
    id            SERIAL PRIMARY KEY,
    timestamp     TIMESTAMP    NOT NULL DEFAULT NOW(),
    "user"        VARCHAR(255) NOT NULL DEFAULT 'admin',
    pis_selected  TEXT[]       NOT NULL,            -- array of position strings (e.g. ["01-003","02-010"])
    action        VARCHAR(50)  NOT NULL
                      CHECK (action IN ('kill','restart','execute','health','status','discovery')),
    command       TEXT,
    exit_code     INT,                               -- NULL if timeout/not applicable
    stdout        TEXT,
    stderr        TEXT,
    status        VARCHAR(20)  NOT NULL
                      CHECK (status IN ('success','fail','partial_fail','running','queued')),
    retry_count   SMALLINT     NOT NULL DEFAULT 0,
    duration_ms   INT
);

CREATE INDEX IF NOT EXISTS idx_actions_log_timestamp ON actions_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_actions_log_user      ON actions_log ("user");
CREATE INDEX IF NOT EXISTS idx_actions_log_status    ON actions_log (status);

-- Prevent deletes (append-only enforcement via rule)
CREATE OR REPLACE RULE no_delete_actions_log AS
    ON DELETE TO actions_log DO INSTEAD NOTHING;
```

### `backend/database.py`

**Goal:** SQLAlchemy async-ready session factory + `get_db()` FastAPI dependency.

**Implementation:**
1. Build `DATABASE_URL` from `Settings`
2. Create `engine` with `pool_size`, `max_overflow=0`, `pool_pre_ping=True`
3. `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)`
4. `Base = declarative_base()`
5. `get_db()` generator: yields session, always closes in finally

```python
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## 5. ORM Models

### `backend/models.py`

#### `Pi` model (maps to `raspberries`)

```python
class Pi(Base):
    __tablename__ = "raspberries"

    id          = Column(Integer, primary_key=True)
    mac         = Column(String(17), nullable=False)          # not unique
    serial      = Column(String(255))                         # /proc/cpuinfo Serial
    hostname    = Column(String(255))                         # Linux hostname
    position    = Column(String(6), nullable=False, unique=True)  # "XX-XXX" room-unit
    pi_version  = Column(SmallInteger)
    current_ip  = Column(INET)
    status      = Column(String(20), nullable=False, default="unreachable")
    last_seen   = Column(DateTime)
    tags        = Column(ARRAY(Text), nullable=False, default=list)
    created_at  = Column(DateTime, nullable=False, default=func.now())
    updated_at  = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
```

**Note:** Use `sqlalchemy.dialects.postgresql.ARRAY` and `INET` — PostgreSQL-specific types are fine since stack is locked.

#### `ActionLog` model (maps to `actions_log`)

```python
class ActionLog(Base):
    __tablename__ = "actions_log"

    id            = Column(Integer, primary_key=True)
    timestamp     = Column(DateTime, nullable=False, default=func.now())
    user          = Column(String(255), nullable=False, default="admin")
    pis_selected  = Column(ARRAY(Text), nullable=False)
    action        = Column(String(50), nullable=False)
    command       = Column(Text)
    exit_code     = Column(Integer)
    stdout        = Column(Text)
    stderr        = Column(Text)
    status        = Column(String(20), nullable=False)
    retry_count   = Column(SmallInteger, nullable=False, default=0)
    duration_ms   = Column(Integer)
```

---

## 6. Pydantic DTOs / Schemas

### `backend/schemas.py`

All request/response models live here. Grouped by domain.

---

#### Common

```python
class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=500)

class ActionQueued(BaseModel):
    action_id: int
    status: Literal["queued"]
```

---

#### Pi / Inventory

```python
# ── Responses ──────────────────────────────────────────────────────────────────

class PiSummary(BaseModel):
    id: int
    mac: str
    hostname: str | None
    position: str               # "XX-XXX" room-unit slot
    ip: str | None              # INET serialised as str
    status: Literal["reachable", "unreachable"]
    last_seen: datetime | None
    tags: list[str]

    model_config = ConfigDict(from_attributes=True)

class PiDetail(PiSummary):
    serial: str | None          # /proc/cpuinfo hardware serial
    pi_version: int | None
    created_at: datetime
    updated_at: datetime

# ── Query filters ──────────────────────────────────────────────────────────────

class PiListFilters(BaseModel):
    status: Literal["reachable", "unreachable"] | None = None
    tags: list[str] | None = None
    version: int | None = None
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=500)
```

---

#### Health Check

```python
# ── Requests ───────────────────────────────────────────────────────────────────

class HealthTriggerRequest(BaseModel):
    pis: list[str] | None = None    # list of MACs; mutually exclusive with all
    all: bool = False

    @model_validator(mode="after")
    def exactly_one(self) -> "HealthTriggerRequest":
        if self.all and self.pis:
            raise ValueError("provide either 'pis' or 'all', not both")
        if not self.all and not self.pis:
            raise ValueError("provide either 'pis' or 'all'")
        return self

# ── Responses ──────────────────────────────────────────────────────────────────

class PiHealthResult(BaseModel):
    mac: str
    cpu_percent: float | None
    mem_used_mb: int | None
    mem_total_mb: int | None
    disk_used_gb: float | None
    disk_total_gb: float | None
    error: str | None               # populated on SSH failure

class HealthCheckResult(BaseModel):
    action_id: int
    status: Literal["queued", "running", "success", "fail", "partial_fail"]
    results: list[PiHealthResult]
    started_at: datetime | None
    completed_at: datetime | None
```

---

#### Command Execution

```python
# ── Requests ───────────────────────────────────────────────────────────────────

class CommandExecuteRequest(BaseModel):
    pis: list[str]                  # list of MACs, min 1
    command: str                    # arbitrary shell command (admin-trusted)

# ── Responses ──────────────────────────────────────────────────────────────────

class PiCommandResult(BaseModel):
    mac: str
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    error: str | None               # SSH-level error (timeout, auth fail)

class CommandExecutionResult(BaseModel):
    action_id: int
    status: Literal["queued", "running", "success", "fail", "partial_fail"]
    results: list[PiCommandResult]
    started_at: datetime | None
    completed_at: datetime | None
```

---

#### Process / Service

```python
# ── Requests ───────────────────────────────────────────────────────────────────

class ProcessKillRequest(BaseModel):
    pis: list[str]
    process_name: str
    signal: Literal["SIGTERM", "SIGKILL"] = "SIGTERM"

class ServiceRestartRequest(BaseModel):
    pis: list[str]
    service: str                    # e.g. "kiosk.service"
```

---

#### Audit Logs

```python
# ── Query params ───────────────────────────────────────────────────────────────

class LogQueryParams(BaseModel):
    pi: str | None = None           # MAC filter
    user: str | None = None
    since: datetime | None = None
    limit: int = Field(100, ge=1, le=1000)

# ── Response ───────────────────────────────────────────────────────────────────

class LogEntry(BaseModel):
    id: int
    timestamp: datetime
    user: str
    pis_selected: list[str]
    action: str
    command: str | None
    exit_code: int | None
    status: str

    model_config = ConfigDict(from_attributes=True)
```

---

#### Discovery

```python
# ── Response ───────────────────────────────────────────────────────────────────

class DiscoveredPi(BaseModel):
    ip: str
    mac: str
    hostname: str | None
    pi_version: int | None

class DiscoveryScanResult(BaseModel):
    action_id: int
    status: Literal["running", "success", "fail"]
    discovered: list[DiscoveredPi]
    added: int
    updated: int
    started_at: datetime | None
    completed_at: datetime | None
```

---

## 7. Services Layer

### `backend/services/ssh_executor.py`

**Responsibilities:**
- Open SSH connection via Paramiko (key auth, no password)
- Execute one command, capture stdout/stderr/exit_code
- Retry up to `retry_count` times on exception (not on non-zero exit)
- Record `duration_ms`
- Return structured `SSHResult` dataclass

**Implementation details:**

```python
@dataclass
class SSHResult:
    mac: str
    exit_code: int | None   # None = timed out or connection error
    stdout: str
    stderr: str
    error: str | None       # SSH-level error description
    duration_ms: int
    retry_count: int
```

**`execute(ip, command, settings) -> SSHResult`:**
1. Load `RSAKey` from `settings.ssh.private_key_path`
2. `SSHClient.connect(ip, username=..., pkey=..., timeout=settings.ssh.timeout_s)`
3. `exec_command(command, timeout=settings.ssh.timeout_s)`
4. Read stdout/stderr fully, close channel, get `exit_status`
5. On `socket.timeout` or `NoValidConnectionsError`: retry (up to `retry_count`), then return error result
6. Always `client.close()` in finally
7. `duration_ms = int((time.monotonic() - start) * 1000)`

**`execute_many(pis: list[tuple[str,str]], command, settings) -> list[SSHResult]`:**
- v1: simple `for` loop over `execute()` — serial
- Returns results in same order as input

---

### `backend/services/discovery.py`

**Responsibilities:**
- Scan CIDR subnet: probe each IP in 10.10.20.0/24 (254 hosts)
- For each live host: SSH connect → read `/proc/cpuinfo` serial + model → extract `pi_version`
- Upsert into `inventory`: insert new, update IP/hostname for known MAC
- Write discovery result to `actions_log`

**Implementation details:**

**`ping_host(ip: str, timeout: float = 0.5) -> bool`:**
- Use `subprocess.run(["ping", "-c1", "-W1", ip], capture_output=True)`
- Returns True if returncode == 0

**`probe_pi(ip: str, settings: SSHSettings) -> DiscoveredPi | None`:**
1. SSH connect (single attempt, short timeout 5s)
2. Run `cat /proc/cpuinfo | grep -E "Serial|Model|Hardware"`
3. Parse Serial line → MAC fallback if ARP available
4. Parse Model line → extract version (e.g. "Raspberry Pi 4" → 4)
5. Run `hostname` command for hostname
6. Get MAC from ARP: `ip neigh show {ip}` on the **controller** (not SSH) — fastest

**`get_mac_from_arp(ip: str) -> str | None`:**
- `subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True)`
- Parse output: `"10.10.20.5 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"`
- Normalise MAC to lowercase `xx:xx:xx:xx:xx:xx`

**`scan_subnet(subnet: str, db: Session, settings: Settings) -> DiscoveryScanResult`:**
1. Generate all IPs from CIDR with `ipaddress.ip_network(subnet).hosts()`
2. Ping each sequentially (v1 — serial; note: 254 hosts × 0.5s = ~2 min max)
3. For live hosts: `get_mac_from_arp` first (fast), then `probe_pi` via SSH
4. Upsert each discovered Pi into `inventory`:
   - If MAC exists: update `current_ip`, `status='reachable'`, `last_seen=NOW()`
   - If MAC new: insert full row
5. Mark MACs not seen in this scan as `status='unreachable'` (if they were `reachable`)
6. Write `actions_log` entry
7. Return `DiscoveryScanResult`

---

### `backend/services/health_check.py`

**Responsibilities:**
- SSH to Pi, collect CPU/mem/disk stats via shell commands
- Parse raw text output into typed numbers
- Does NOT evaluate thresholds — returns raw stats only

**Commands:**
```bash
# CPU usage (1-second sample)
top -bn1 | grep "Cpu(s)" | awk '{print $2 + $4}'

# Memory
free -m | awk '/^Mem:/{print $2, $3}'   # total_mb used_mb

# Disk
df -m / | awk 'NR==2{print $2, $3}'    # total_mb used_mb
```

**`check_health(ip: str, mac: str, settings: SSHSettings) -> PiHealthResult`:**
1. Single SSH session (reuse connection for all 3 commands via `exec_command` × 3)
2. Parse each output
3. On parse error or SSH failure: set numeric fields to None, populate `error`
4. Return `PiHealthResult`

**`run_health_check(pis: list[Pi], db: Session, settings: Settings) -> int`** (returns action_id):
1. Create `actions_log` entry with `status='running'`
2. Loop over Pis serially, call `check_health` for each
3. Aggregate results — determine overall status:
   - all success → `success`
   - all fail → `fail`
   - mixed → `partial_fail`
4. Update `actions_log` entry with final status, duration, stdout (JSON-serialised results)
5. Return action_id

---

### `backend/services/audit_log.py`

**Responsibilities:**
- Create new `ActionLog` rows
- Query with filters
- Never delete (enforced at DB level too)

```python
def create_action(
    db: Session,
    pis_selected: list[str],
    action: str,
    command: str | None = None,
    status: str = "queued",
) -> ActionLog

def update_action(
    db: Session,
    action_id: int,
    status: str,
    exit_code: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    retry_count: int = 0,
    duration_ms: int | None = None,
) -> ActionLog

def get_action(db: Session, action_id: int) -> ActionLog | None

def query_actions(
    db: Session,
    pi_mac: str | None,
    user: str | None,
    since: datetime | None,
    limit: int,
) -> list[ActionLog]
```

---

## 8. API Routes

All routes return JSON. All error responses use standard `HTTPException`. Action endpoints execute synchronously (v1 — no background task queue), respond after completion.

### `backend/routes/pi.py`

```
GET  /pi/list
     Query: status, tags (multi), version, page, limit
     → list[PiSummary]

GET  /pi/{mac}/status
     → PiDetail
     404 if not found
```

**Implementation:**
- `GET /pi/list`: Build SQLAlchemy query on `Pi` model, apply filters:
  - `status` filter: `Pi.status == status`
  - `tags` filter: `Pi.tags.contains(tags)` (PostgreSQL array overlap: `@>`)
  - `version` filter: `Pi.pi_version == version`
  - Paginate: `.offset((page-1)*limit).limit(limit)`
- `GET /pi/{mac}/status`: Normalise MAC, query by `Pi.mac == mac`, 404 if None

---

### `backend/routes/health.py`

```
POST /health/trigger
     Body: HealthTriggerRequest
     → ActionQueued

GET  /health/{action_id}
     → HealthCheckResult
     404 if not found
```

**`POST /health/trigger` implementation:**
1. If `all=true`: fetch all `reachable` Pis from DB
2. Else: fetch Pis by MAC list (validate all exist — 422 if any missing)
3. Call `health_check.run_health_check(pis, db, settings)` — synchronous
4. Return `ActionQueued(action_id=..., status="queued")` immediately
   - **Note:** v1 is synchronous; return action_id, client polls `GET /health/{action_id}`
   - Actually for v1 simplicity: run fully synchronous, return final action_id with `status="success"`

**`GET /health/{action_id}` implementation:**
1. Fetch `ActionLog` by id
2. Parse `stdout` field (stored as JSON string) into `list[PiHealthResult]`
3. Return `HealthCheckResult`

---

### `backend/routes/command.py`

```
POST /command/execute
     Body: CommandExecuteRequest
     → ActionQueued (action_id for polling)

GET  /command/{action_id}
     → CommandExecutionResult
```

**`POST /command/execute` implementation:**
1. Validate all MACs exist in DB (422 if not)
2. Fetch `current_ip` for each MAC
3. Skip `unreachable` Pis (include in results with `error="unreachable"`)
4. Create `actions_log` entry (`status="running"`)
5. Call `ssh_executor.execute_many([(ip, mac), ...], command, settings)` — serial
6. Map `SSHResult` list → `list[PiCommandResult]`
7. Determine overall status: all exit_code==0 → `success`; any SSH error → `partial_fail`; all error → `fail`
8. Update `actions_log` entry
9. Return `ActionQueued` (client polls for results)

---

### `backend/routes/process.py`

```
POST /process/kill
     Body: ProcessKillRequest
     → ActionQueued
```

**Implementation:**
1. Build command: `pkill -{signal} {process_name} || (echo "process not found" && exit 1)`
   - Exit 1 if process not found → treated as error
2. Delegate to `ssh_executor.execute_many`
3. If exit_code == 1 and stdout contains "process not found": raise meaningful error in result
4. Log to `actions_log` with `action="kill"`

---

### `backend/routes/service.py`

```
POST /service/restart
     Body: ServiceRestartRequest
     → ActionQueued
```

**Implementation:**
1. Build command: `systemctl restart {service}` (returns non-zero if unit not found)
2. Check `exit_code != 0` → mark as fail with stderr
3. Log to `actions_log` with `action="restart"`

---

### `backend/routes/logs.py`

```
GET  /logs
     Query: pi (MAC), user, since (ISO datetime), limit
     → list[LogEntry]
```

**Implementation:**
- Parse query params into `LogQueryParams`
- Call `audit_log.query_actions(db, ...)`
- Return serialised list

---

### `backend/routes/discovery.py`

```
POST /discovery/scan
     → ActionQueued

GET  /discovery/scan/{action_id}
     → DiscoveryScanResult
```

**`POST /discovery/scan` implementation:**
1. Create `actions_log` entry (`action="discovery"`, `status="running"`)
2. Call `discovery.scan_subnet(settings.network.subnet, db, settings)` — synchronous (slow: ~2 min for /24)
3. Update `actions_log` on completion
4. Return action_id

**`GET /discovery/scan/{action_id}` implementation:**
1. Fetch `ActionLog` by id, verify `action="discovery"`
2. Parse `stdout` (JSON) → `list[DiscoveredPi]`
3. Return `DiscoveryScanResult`

---

## 9. FastAPI App Assembly

### `backend/main.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from backend.database import engine, Base
from backend.routes import pi, health, command, process, service, logs, discovery
from backend.config import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: verify DB connection
    settings = get_settings()
    # optionally: Base.metadata.create_all(engine) for dev
    yield
    # shutdown: nothing needed

app = FastAPI(
    title="Pi Controller API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(pi.router,        prefix="/pi",        tags=["inventory"])
app.include_router(health.router,    prefix="/health",    tags=["health"])
app.include_router(command.router,   prefix="/command",   tags=["command"])
app.include_router(process.router,   prefix="/process",   tags=["process"])
app.include_router(service.router,   prefix="/service",   tags=["service"])
app.include_router(logs.router,      prefix="/logs",      tags=["logs"])
app.include_router(discovery.router, prefix="/discovery", tags=["discovery"])

@app.get("/health", tags=["system"])
def system_health(db: Session = Depends(get_db)):
    # ping DB
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "db": db_status, "uptime_s": ...}
```

**Startup command:**
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 10. Error Handling

**Standard approach — no custom exception middleware needed for v1.**

Per-route `HTTPException` patterns:

| Situation | HTTP code | Detail |
|-----------|-----------|--------|
| MAC not found | 404 | `"Pi {mac} not found"` |
| Invalid MAC format | 422 | Pydantic validation |
| Invalid action_id | 404 | `"Action {id} not found"` |
| SSH auth failure | 502 | `"SSH auth failed for {ip}"` |
| DB unavailable | 503 | `"Database unavailable"` |
| Process not found on Pi | 200 | result.error field set |
| Service not found on Pi | 200 | result.error field set |

**MAC normalisation in `backend/utils/helpers.py`:**

```python
import re

MAC_RE = re.compile(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$')

def normalise_mac(mac: str) -> str:
    """Lowercase, colon-separated. Raises ValueError if invalid."""
    m = mac.lower().strip()
    if not MAC_RE.match(m):
        raise ValueError(f"Invalid MAC: {mac}")
    return m
```

---

## 11. Tests

### `tests/conftest.py`

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import Base, get_db
from backend.models import Pi, ActionLog

TEST_DB_URL = "postgresql://pi_controller:test@localhost/pi_controller_test"

@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

@pytest.fixture
def db(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()

@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture
def mock_ssh(mocker):
    """Patches ssh_executor.execute to return a canned SSHResult."""
    from backend.services.ssh_executor import SSHResult
    return mocker.patch(
        "backend.services.ssh_executor.execute",
        return_value=SSHResult(mac="aa:bb:cc:dd:ee:ff", exit_code=0,
                               stdout="ok", stderr="", error=None,
                               duration_ms=50, retry_count=0)
    )
```

### `tests/test_ssh_executor.py`

- **`test_execute_success`**: Mock `paramiko.SSHClient`, verify `SSHResult` fields
- **`test_execute_timeout_retries`**: Make connect raise `socket.timeout`, assert retry_count == settings.retry_count
- **`test_execute_auth_fail`**: Raise `AuthenticationException`, assert error field set, no retries
- **`test_execute_nonzero_exit`**: exit_code=1, assert no retry (retries are SSH-level only)

### `tests/test_api_routes.py`

- **`test_pi_list_empty`**: GET /pi/list → 200, empty list
- **`test_pi_list_filter_status`**: Insert reachable + unreachable, filter by status
- **`test_pi_list_filter_tags`**: Insert Pi with tags, query by tag
- **`test_pi_status_not_found`**: GET /pi/aa:bb:cc:dd:ee:99/status → 404
- **`test_health_trigger_all`**: POST /health/trigger `{all:true}`, mock SSH → 200
- **`test_health_trigger_unknown_mac`**: POST with unknown MAC → 422
- **`test_command_execute`**: POST /command/execute, mock SSH, check actions_log row created
- **`test_process_kill_not_found`**: Mock SSH returns exit_code=1, error message in result
- **`test_service_restart`**: Mock SSH returns exit_code=0, status=success
- **`test_logs_query`**: Insert 3 ActionLog rows, query by pi MAC
- **`test_discovery_scan`**: Mock ping + SSH + ARP, verify upsert logic

### `tests/test_database.py`

- **`test_pi_upsert`**: Insert Pi, update IP, verify updated_at changes
- **`test_actions_log_append_only`**: Attempt DELETE → row still exists (rule test)
- **`test_pi_tags_gin_query`**: Insert Pi with tags, query with GIN index path
- **`test_actions_log_status_constraint`**: Insert with invalid status → DB raises IntegrityError

---

## 12. Deployment Artifacts

### `systemd/pi-controller.service`

```ini
[Unit]
Description=Pi Controller API
After=network.target postgresql.service

[Service]
Type=simple
User=pi_controller
WorkingDirectory=/opt/pi-controller
EnvironmentFile=/opt/pi-controller/.env
ExecStart=/opt/pi-controller/venv/bin/uvicorn backend.main:app \
    --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### DB setup script (`scripts/setup_db.sh`)

```bash
#!/bin/bash
set -e
sudo -u postgres psql <<SQL
  CREATE USER pi_controller WITH PASSWORD '${DB_PASSWORD}';
  CREATE DATABASE pi_controller OWNER pi_controller;
  GRANT ALL ON DATABASE pi_controller TO pi_controller;
SQL
psql -U pi_controller -d pi_controller -f migrations/001_init.sql
```

---

## 13. Implementation Order

Execute these steps in order — each builds on the previous.

| Step | File(s) | What to do |
|------|---------|-----------|
| 1 | `requirements.txt`, `requirements-dev.txt` | Pin all deps as listed in §2 |
| 2 | `.env.example`, `config.yaml` | Write config files as in §3 |
| 3 | `backend/config.py` | YAML loader + Settings dataclass + env interpolation |
| 4 | `migrations/001_init.sql` | Full DDL as in §4 |
| 5 | `backend/database.py` | Engine + SessionLocal + get_db |
| 6 | `backend/models.py` | Pi + ActionLog ORM models |
| 7 | `backend/utils/helpers.py` | normalise_mac + pagination helpers |
| 8 | `backend/schemas.py` | All Pydantic DTOs from §6 |
| 9 | `backend/services/audit_log.py` | create/update/get/query |
| 10 | `backend/services/ssh_executor.py` | SSHResult + execute + execute_many |
| 11 | `backend/services/health_check.py` | check_health + run_health_check |
| 12 | `backend/services/discovery.py` | ping + ARP + probe + scan_subnet |
| 13 | `backend/routes/pi.py` | /pi/list + /pi/{mac}/status |
| 14 | `backend/routes/health.py` | /health/trigger + /health/{id} |
| 15 | `backend/routes/command.py` | /command/execute + /command/{id} |
| 16 | `backend/routes/process.py` | /process/kill |
| 17 | `backend/routes/service.py` | /service/restart |
| 18 | `backend/routes/logs.py` | /logs |
| 19 | `backend/routes/discovery.py` | /discovery/scan + /discovery/scan/{id} |
| 20 | `backend/main.py` | App assembly + lifespan + /health endpoint |
| 21 | `tests/conftest.py` | Fixtures: test DB + TestClient + mock_ssh |
| 22 | `tests/test_database.py` | DB-layer unit tests |
| 23 | `tests/test_ssh_executor.py` | SSH executor unit tests |
| 24 | `tests/test_api_routes.py` | Route integration tests |
| 25 | `systemd/pi-controller.service` | Systemd unit |
| 26 | `scripts/setup_db.sh` | DB bootstrap script |

---

## Key Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Sync vs async | Sync (threading) | Paramiko is not async; v1 serial SSH anyway |
| Migration tool | Raw SQL file | Schema is locked; Alembic adds complexity with no benefit |
| Action result storage | `stdout` JSON in actions_log | Avoids extra result tables for v1 |
| Discovery MAC source | ARP table (`ip neigh`) | Faster than reading `/proc/cpuinfo` via SSH for each host |
| v1 execution model | Synchronous in-request | No job queue needed; client polls if needed |
| Error granularity | Per-Pi result errors | Partial failures are normal (Pi may be off) |
| Process/service errors | Error in result, HTTP 200 | SSH succeeded; the Pi reported the error |
