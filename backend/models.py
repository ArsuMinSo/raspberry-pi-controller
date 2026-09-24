from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.orm import mapped_column, MappedColumn
from sqlalchemy.sql import func

from backend.database import Base


class Pi(Base):
    __tablename__ = "raspberries"

    mac: MappedColumn[str] = mapped_column(String(17), primary_key=True, nullable=False)
    serial: MappedColumn[str | None] = mapped_column(String(255))
    hostname: MappedColumn[str | None] = mapped_column(String(255))
    position: MappedColumn[str] = mapped_column(String(20), nullable=False, unique=True)
    pi_version: MappedColumn[int | None] = mapped_column(SmallInteger)
    current_ip = mapped_column(INET)
    status: MappedColumn[str] = mapped_column(String(20), nullable=False, default="unreachable")
    last_seen = mapped_column(DateTime)
    tags = mapped_column(ARRAY(Text), nullable=False, default=list)
    cpu_1m = mapped_column(Float)
    cpu_5m = mapped_column(Float)
    cpu_15m = mapped_column(Float)
    mem_percent = mapped_column(Float)
    temp_c = mapped_column(Float)
    created_at = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ActionLog(Base):
    __tablename__ = "actions_log"

    id: MappedColumn[int] = mapped_column(Integer, primary_key=True)
    timestamp = mapped_column(DateTime, nullable=False, server_default=func.now())
    user: MappedColumn[str] = mapped_column(String(255), nullable=False, default="admin")
    pis_selected = mapped_column(ARRAY(Text), nullable=False)
    action: MappedColumn[str] = mapped_column(String(50), nullable=False)
    command = mapped_column(Text)
    exit_code = mapped_column(Integer)
    stdout = mapped_column(Text)
    stderr = mapped_column(Text)
    status: MappedColumn[str] = mapped_column(String(20), nullable=False)
    retry_count: MappedColumn[int] = mapped_column(SmallInteger, nullable=False, default=0)
    duration_ms = mapped_column(Integer)
    user_id = mapped_column(Integer, ForeignKey("users.id"))


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: MappedColumn[int] = mapped_column(Integer, primary_key=True)
    name: MappedColumn[str] = mapped_column(String(255), nullable=False)
    cron: MappedColumn[str] = mapped_column(String(100), nullable=False)
    task_type: MappedColumn[str] = mapped_column(String(20), nullable=False)  # command/health/discovery
    command = mapped_column(Text)
    pis = mapped_column(ARRAY(Text), nullable=False, default=list)
    enabled: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run = mapped_column(DateTime)
    last_status = mapped_column(String(20))
    last_action_id = mapped_column(Integer)
    owner_user_id = mapped_column(Integer, ForeignKey("users.id"))  # scheduled runs are logged as this user
    created_at = mapped_column(DateTime, nullable=False, server_default=func.now())


# ─── Auth (migration 003) ─────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: MappedColumn[int] = mapped_column(Integer, primary_key=True)
    username: MappedColumn[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: MappedColumn[str] = mapped_column(Text, nullable=False)
    role: MappedColumn[str] = mapped_column(String(10), nullable=False)  # viewer/operator/admin
    is_active: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: MappedColumn[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    last_login_at = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "sessions"

    id: MappedColumn[int] = mapped_column(Integer, primary_key=True)
    user_id: MappedColumn[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: MappedColumn[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at = mapped_column(DateTime(timezone=True))
    ip = mapped_column(String(45))
    user_agent = mapped_column(String(255))


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: MappedColumn[int] = mapped_column(Integer, primary_key=True)
    ts = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    user_id = mapped_column(Integer, ForeignKey("users.id"))
    username: MappedColumn[str] = mapped_column(String(64), nullable=False)
    event: MappedColumn[str] = mapped_column(String(40), nullable=False)
    target = mapped_column(String(255))
    details = mapped_column(JSONB)
    ip = mapped_column(String(45))
    user_agent = mapped_column(String(255))
