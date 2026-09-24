from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Common ───────────────────────────────────────────────────────────────────

class ActionQueued(BaseModel):
    action_id: int
    status: Literal["queued"] = "queued"


# ─── Pi / Inventory ───────────────────────────────────────────────────────────

class PiSummary(BaseModel):
    mac: str
    hostname: str | None
    position: str
    ip: str | None
    pi_version: int | None
    status: Literal["reachable", "unreachable"]
    last_seen: datetime | None
    tags: list[str]
    cpu_1m: float | None = None
    cpu_5m: float | None = None
    cpu_15m: float | None = None
    mem_percent: float | None = None
    temp_c: float | None = None

    model_config = ConfigDict(from_attributes=True)


class PiDetail(PiSummary):
    serial: str | None
    pi_version: int | None
    created_at: datetime
    updated_at: datetime


class PiListFilters(BaseModel):
    status: Literal["reachable", "unreachable"] | None = None
    tags: list[str] | None = None
    version: int | None = None
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=500)


class PiCreateRequest(BaseModel):
    position: str = Field(..., pattern=r"^(\d{2}-\d{3}|\d{1,10})$")
    mac: str = Field(..., pattern=r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
    hostname: str | None = None
    ip: str | None = None
    pi_version: int | None = Field(None, ge=2, le=5)
    tags: list[str] = []
    status: Literal["reachable", "unreachable"] = "unreachable"

    @model_validator(mode="after")
    def mac_not_placeholder(self) -> "PiCreateRequest":
        if self.mac.lower() == "00:00:00:00:00:00":
            raise ValueError("MAC address must be a real device MAC, not the placeholder")
        return self


class PiUpdateRequest(BaseModel):
    position: str | None = Field(None, pattern=r"^(\d{2}-\d{3}|\d{1,10})$")
    mac: str | None = Field(None, pattern=r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
    hostname: str | None = None
    ip: str | None = None
    pi_version: int | None = Field(None, ge=2, le=5)
    tags: list[str] | None = None
    status: Literal["reachable", "unreachable"] | None = None


# ─── Health Check ─────────────────────────────────────────────────────────────

class HealthTriggerRequest(BaseModel):
    pis: list[str] | None = None
    all: bool = False

    @model_validator(mode="after")
    def exactly_one(self) -> "HealthTriggerRequest":
        if self.all and self.pis:
            raise ValueError("provide either 'pis' or 'all', not both")
        if not self.all and not self.pis:
            raise ValueError("provide either 'pis' or 'all'")
        return self


class PiHealthResult(BaseModel):
    position: str
    cpu_1m: float | None
    cpu_5m: float | None
    cpu_15m: float | None
    mem_percent: float | None
    temp_c: float | None
    pi_time: str | None = None
    uptime_s: int | None = None
    error: str | None


class HealthCheckResult(BaseModel):
    action_id: int
    status: str
    results: list[PiHealthResult]
    started_at: datetime | None
    completed_at: datetime | None


# ─── Bulk Create ──────────────────────────────────────────────────────────────

class BulkPiCreateRequest(BaseModel):
    pis: list[PiCreateRequest] = Field(..., min_length=1)


class BulkPiCreateItemResult(BaseModel):
    position: str
    created: bool
    skipped: bool
    reason: str | None


class BulkPiCreateResponse(BaseModel):
    results: list[BulkPiCreateItemResult]
    created: int
    skipped: int


# ─── Key Deployment ───────────────────────────────────────────────────────────

class DeployKeyRequest(BaseModel):
    pis: list[str] = Field(..., min_length=1)
    password: str


class DeployKeyResult(BaseModel):
    position: str
    ip: str | None
    success: bool
    error: str | None


class DeployKeyResponse(BaseModel):
    results: list[DeployKeyResult]
    succeeded: int
    failed: int


# ─── Command Execution ────────────────────────────────────────────────────────

class CommandExecuteRequest(BaseModel):
    pis: list[str] = Field(..., min_length=1)
    command: str
    ssh_username: str | None = None
    ssh_password: str | None = None


class PiCommandResult(BaseModel):
    position: str
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    error: str | None


class CommandExecutionResult(BaseModel):
    action_id: int
    status: str
    results: list[PiCommandResult]
    started_at: datetime | None
    completed_at: datetime | None


# ─── Process / Service ────────────────────────────────────────────────────────

class ProcessKillRequest(BaseModel):
    pis: list[str] = Field(..., min_length=1)
    process_name: str
    signal: Literal["SIGTERM", "SIGKILL"] = "SIGTERM"


class ServiceRestartRequest(BaseModel):
    pis: list[str] = Field(..., min_length=1)
    service: str


# ─── Logs ─────────────────────────────────────────────────────────────────────

class LogQueryParams(BaseModel):
    pi: str | None = None
    user: str | None = None
    since: datetime | None = None
    limit: int = Field(100, ge=1, le=1000)


class LogEntry(BaseModel):
    id: int
    timestamp: datetime
    user: str
    pis_selected: list[str]
    action: str
    command: str | None
    exit_code: int | None
    status: str
    stdout: str | None
    stderr: str | None
    duration_ms: int | None

    model_config = ConfigDict(from_attributes=True)


# ─── Discovery ────────────────────────────────────────────────────────────────

# ─── Scheduled Tasks ──────────────────────────────────────────────────────────

class ScheduledTaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    cron: str = Field(..., min_length=1, max_length=100)
    task_type: Literal["command", "health", "discovery"]
    command: str | None = None
    pis: list[str] = []
    enabled: bool = True


class ScheduledTaskUpdate(BaseModel):
    name: str | None = None
    cron: str | None = None
    task_type: Literal["command", "health", "discovery"] | None = None
    command: str | None = None
    pis: list[str] | None = None
    enabled: bool | None = None


class ScheduledTaskOut(BaseModel):
    id: int
    name: str
    cron: str
    task_type: str
    command: str | None
    pis: list[str]
    enabled: bool
    last_run: datetime | None
    last_status: str | None
    last_action_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Discovery ────────────────────────────────────────────────────────────────

class DiscoveredPi(BaseModel):
    ip: str
    mac: str | None
    hostname: str | None
    pi_version: int | None


class DiscoveryScanResult(BaseModel):
    action_id: int
    status: str
    discovered: list[DiscoveredPi]
    added: int
    updated: int
    started_at: datetime | None
    completed_at: datetime | None


# ─── Auth / users (migration 003) ─────────────────────────────────────────────

Role = Literal["viewer", "operator", "admin"]


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=1024)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


class MeOut(BaseModel):
    username: str
    role: str
    user: UserOut | None  # None for the TUI break-glass key


class PasswordChange(BaseModel):
    current_password: str = Field(..., max_length=1024)
    new_password: str = Field(..., max_length=1024)
    new_password_confirm: str = Field(..., max_length=1024)


class UserCreate(BaseModel):
    username: str
    role: Role
    password: str = Field(..., max_length=1024)
    password_confirm: str = Field(..., max_length=1024)
    must_change_password: bool = True


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(..., max_length=1024)
    password_confirm: str = Field(..., max_length=1024)
    must_change_password: bool = True


class SessionOut(BaseModel):
    id: int
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool = False

    model_config = ConfigDict(from_attributes=True)


class AuditEventOut(BaseModel):
    id: int
    ts: datetime
    username: str
    event: str
    target: str | None
    details: dict | None
    ip: str | None

    model_config = ConfigDict(from_attributes=True)


# ─── Background actions (migration 004) ───────────────────────────────────────

class ActionResultOut(BaseModel):
    position: str
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    error: str | None
    details: dict | None
    duration_ms: int | None
    finished_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActionProgress(BaseModel):
    action_id: int
    action: str
    status: str                 # queued / running / success / fail / partial_fail / interrupted
    finished: bool
    user: str
    command: str | None
    pis_selected: list[str]
    total: int                  # Pis in the action (0 for discovery)
    done: int                   # Pis finished so far
    results: list[ActionResultOut]
    error: str | None           # job-level failure (not per-Pi)
    started_at: datetime
    duration_ms: int | None


# ─── Fleet actions (reboot / display / diagnostics) + summary ─────────────────

class PiSelection(BaseModel):
    pis: list[str] = Field(..., min_length=1)


class DisplayPowerRequest(PiSelection):
    state: Literal["on", "off"]


class FleetPiValue(BaseModel):
    position: str
    hostname: str | None
    value: float


class FleetSummary(BaseModel):
    total: int
    reachable: int
    unreachable: int
    stale_hours: int
    stale: list[str]            # positions not seen for stale_hours (seen at least once)
    never_seen: list[str]       # positions with no successful contact yet
    hottest: list[FleetPiValue]  # temp_c, top 5
    busiest_cpu: list[FleetPiValue]  # cpu_1m, top 5
    highest_mem: list[FleetPiValue]  # mem_percent, top 5
    last_health_check_at: datetime | None
