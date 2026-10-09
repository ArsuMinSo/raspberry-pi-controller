from datetime import datetime

from sqlalchemy.orm import Session

from backend.auth import Actor
from backend.models import ActionLog, ActionResult


def create_action(
    db: Session,
    pis_selected: list[str],
    action: str,
    command: str | None = None,
    status: str = "queued",
    actor: Actor | None = None,
) -> ActionLog:
    entry = ActionLog(
        pis_selected=pis_selected,
        action=action,
        command=command,
        status=status,
        user=actor.username if actor else "system",
        user_id=actor.user_id if actor else None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_action(
    db: Session,
    action_id: int,
    status: str,
    exit_code: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    retry_count: int = 0,
    duration_ms: int | None = None,
) -> ActionLog:
    entry = db.get(ActionLog, action_id)
    if entry is None:
        raise ValueError(f"ActionLog {action_id} not found")
    entry.status = status
    if exit_code is not None:
        entry.exit_code = exit_code
    if stdout is not None:
        entry.stdout = stdout
    if stderr is not None:
        entry.stderr = stderr
    entry.retry_count = retry_count
    if duration_ms is not None:
        entry.duration_ms = duration_ms
    db.commit()
    db.refresh(entry)
    return entry


def add_result(
    db: Session,
    action_id: int,
    position: str,
    exit_code: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    error: str | None = None,
    details: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    """Record one Pi's result as soon as it finishes (progress for the web page)."""
    db.add(ActionResult(
        action_id=action_id, position=position, exit_code=exit_code, stdout=stdout or None,
        stderr=stderr or None, error=error, details=details, duration_ms=duration_ms,
    ))
    db.commit()


def get_results(db: Session, action_id: int) -> list[ActionResult]:
    return db.query(ActionResult).filter(ActionResult.action_id == action_id).order_by(ActionResult.id).all()


def mark_interrupted(db: Session) -> int:
    """At startup: jobs that were queued/running when the process stopped will never finish."""
    count = (
        db.query(ActionLog)
        .filter(ActionLog.status.in_(("queued", "running")))
        .update({"status": "interrupted"}, synchronize_session=False)
    )
    db.commit()
    return count


def get_action(db: Session, action_id: int) -> ActionLog | None:
    # Always re-read: a background job (own session) may have changed the row since this session loaded it
    return db.get(ActionLog, action_id, populate_existing=True)


def query_actions(
    db: Session,
    pi_position: str | None = None,
    user: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[ActionLog]:
    q = db.query(ActionLog)
    if pi_position:
        q = q.filter(ActionLog.pis_selected.contains([pi_position]))
    if user:
        q = q.filter(ActionLog.user == user)
    if since:
        q = q.filter(ActionLog.timestamp >= since)
    return q.order_by(ActionLog.timestamp.desc()).limit(limit).all()
