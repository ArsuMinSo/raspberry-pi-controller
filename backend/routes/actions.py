from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth import require_role
from backend.database import get_db
from backend.schemas import ActionProgress, ActionResultOut
from backend.services import audit_log as al

router = APIRouter(dependencies=[Depends(require_role("viewer"))])

FINISHED = {"success", "fail", "partial_fail", "interrupted"}


@router.get("/{action_id}", response_model=ActionProgress)
def get_action_progress(action_id: int, db: Session = Depends(get_db)):
    """Poll this while an action runs: per-Pi results appear as each Pi finishes."""
    entry = al.get_action(db, action_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    results = al.get_results(db, action_id)
    return ActionProgress(
        action_id=entry.id,
        action=entry.action,
        status=entry.status,
        finished=entry.status in FINISHED,
        user=entry.user,
        command=entry.command,
        pis_selected=entry.pis_selected or [],
        total=len(entry.pis_selected or []),
        done=len(results),
        results=[ActionResultOut.model_validate(r) for r in results],
        error=entry.stderr if entry.status == "fail" and not results else None,
        started_at=entry.timestamp,
        duration_ms=entry.duration_ms,
    )
