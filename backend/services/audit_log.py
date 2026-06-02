from datetime import datetime

from sqlalchemy.orm import Session

from backend.models import ActionLog


def create_action(
    db: Session,
    pis_selected: list[str],
    action: str,
    command: str | None = None,
    status: str = "queued",
) -> ActionLog:
    entry = ActionLog(
        pis_selected=pis_selected,
        action=action,
        command=command,
        status=status,
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


def get_action(db: Session, action_id: int) -> ActionLog | None:
    return db.get(ActionLog, action_id)


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
