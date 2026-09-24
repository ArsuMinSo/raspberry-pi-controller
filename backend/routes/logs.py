from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.auth import require_role
from backend.database import get_db
from backend.models import AuditEvent
from backend.schemas import AuditEventOut, LogEntry
from backend.services import audit_log as al

router = APIRouter(dependencies=[Depends(require_role("viewer"))])


@router.get("", response_model=list[LogEntry])
def get_logs(
    pi: str | None = Query(None, description="Filter by position e.g. 01-003"),
    user: str | None = Query(None),
    since: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    entries = al.query_actions(db, pi_position=pi, user=user, since=since, limit=limit)
    return [LogEntry.model_validate(e) for e in entries]


@router.get("/events", response_model=list[AuditEventOut])
def get_audit_events(
    user: str | None = Query(None),
    event: str | None = Query(None),
    since: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Logins, edits, settings and user changes (everything that isn't a Pi operation)."""
    q = db.query(AuditEvent)
    if user:
        q = q.filter(AuditEvent.username == user)
    if event:
        q = q.filter(AuditEvent.event == event)
    if since:
        q = q.filter(AuditEvent.ts >= since)
    return q.order_by(AuditEvent.ts.desc()).limit(limit).all()
