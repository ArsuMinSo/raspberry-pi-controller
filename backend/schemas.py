from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Common ───────────────────────────────────────────────────────────────────

class ActionQueued(BaseModel):
    action_id: int
    status: Literal["queued"] = "queued"


# ─── Pi / Inventory ───────────────────────────────────────────────────────────

class PiSummary(BaseModel):
    id: int
    mac: str
    hostname: str | None
    position: str
    ip: str | None
    status: Literal["reachable", "unreachable"]
    last_seen: datetime | None
    tags: list[str]

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
    position: str = Field(..., pattern=r"^\d{2}-\d{3}$")
    mac: str = Field(..., pattern=r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
    hostname: str | None = None
    ip: str | None = None
    pi_version: int | None = Field(None, ge=2, le=5)
    tags: list[str] = []
    status: Literal["reachable", "unreachable"] = "unreachable"


class PiUpdateRequest(BaseModel):
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
    cpu_percent: float | None
    mem_used_mb: int | None
    mem_total_mb: int | None
    disk_used_gb: float | None
    disk_total_gb: float | None
    error: str | None


class HealthCheckResult(BaseModel):
    action_id: int
    status: str
    results: list[PiHealthResult]
    started_at: datetime | None
    completed_at: datetime | None


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
