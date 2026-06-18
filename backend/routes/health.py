import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import effective_ssh_settings
from backend.database import get_db
from backend.models import Pi
from backend.schemas import ActionQueued, HealthCheckResult, HealthTriggerRequest, PiHealthResult
from backend.services import audit_log as al
from backend.services.health_check import run_health_check

router = APIRouter()


@router.post("/trigger", response_model=ActionQueued)
def trigger_health(body: HealthTriggerRequest, db: Session = Depends(get_db)):
    if body.all:
        pis = db.query(Pi).filter(Pi.status == "reachable").all()
        if not pis:
            raise HTTPException(status_code=404, detail="No reachable Pis found")
    else:
        pis = db.query(Pi).filter(Pi.position.in_(body.pis)).all()
        found = {p.position for p in pis}
        missing = [pos for pos in body.pis if pos not in found]
        if missing:
            raise HTTPException(status_code=422, detail=f"Unknown positions: {missing}")

    action_id = run_health_check(pis, db, effective_ssh_settings())
    return ActionQueued(action_id=action_id)


@router.get("/{action_id}", response_model=HealthCheckResult)
def get_health_result(action_id: int, db: Session = Depends(get_db)):
    entry = al.get_action(db, action_id)
    if not entry or entry.action != "health":
        raise HTTPException(status_code=404, detail=f"Health action {action_id} not found")

    results: list[PiHealthResult] = []
    if entry.stdout:
        try:
            results = [PiHealthResult(**r) for r in json.loads(entry.stdout)]
        except (json.JSONDecodeError, TypeError):
            pass

    return HealthCheckResult(
        action_id=entry.id,
        status=entry.status,
        results=results,
        started_at=entry.timestamp,
        completed_at=None,
    )
