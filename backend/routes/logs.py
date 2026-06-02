from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas import LogEntry
from backend.services import audit_log as al

router = APIRouter()


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
