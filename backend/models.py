from sqlalchemy import ARRAY, DateTime, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import mapped_column, MappedColumn
from sqlalchemy.sql import func

from backend.database import Base


class Pi(Base):
    __tablename__ = "raspberries"

    id: MappedColumn[int] = mapped_column(Integer, primary_key=True)
    mac: MappedColumn[str] = mapped_column(String(17), nullable=False)
    serial: MappedColumn[str | None] = mapped_column(String(255))
    hostname: MappedColumn[str | None] = mapped_column(String(255))
    position: MappedColumn[str] = mapped_column(String(6), nullable=False, unique=True)
    pi_version: MappedColumn[int | None] = mapped_column(SmallInteger)
    current_ip = mapped_column(INET)
    status: MappedColumn[str] = mapped_column(String(20), nullable=False, default="unreachable")
    last_seen = mapped_column(DateTime)
    tags = mapped_column(ARRAY(Text), nullable=False, default=list)
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
