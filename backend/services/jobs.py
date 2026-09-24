"""Background jobs: long operations run here, not in the HTTP request.

A route creates the `actions_log` row (status "queued"), calls `submit(run_action, id, work)`
and returns the action id at once. Clients poll GET /api/v1/actions/{id}.
Runs in-process (single uvicorn worker) — see docs/design/web-service.md.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import ActionLog
from backend.services import audit_log as al

log = logging.getLogger(__name__)

MAX_CONCURRENT_JOBS = 4
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="job")

# Replaced by tests: their own DB, and jobs run synchronously so results are deterministic
session_factory: Callable[[], Session] = SessionLocal
run_inline = False

Work = Callable[[Session, ActionLog], None]


def submit(fn: Callable, *args, **kwargs) -> None:
    if run_inline:
        fn(*args, **kwargs)
    else:
        _executor.submit(fn, *args, **kwargs)


def run_action(action_id: int, work: Work) -> None:
    """Run `work(db, entry)` for a queued action in its own DB session.

    `work` records per-Pi results and sets the final status; any exception marks the action "fail".
    """
    db = session_factory()
    start = time.monotonic()
    try:
        entry = db.get(ActionLog, action_id)
        if entry is None:
            log.error("job for missing action %s", action_id)
            return
        entry.status = "running"
        db.commit()
        try:
            work(db, entry)
        except Exception as e:
            log.exception("action %s (%s) failed", action_id, entry.action)
            db.rollback()
            al.update_action(db, action_id, status="fail", stderr=f"{type(e).__name__}: {e}",
                             duration_ms=int((time.monotonic() - start) * 1000))
    finally:
        db.close()
