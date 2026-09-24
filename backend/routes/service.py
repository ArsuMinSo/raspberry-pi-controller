import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth import Actor, require_role
from backend.database import get_db
from backend.models import Pi
from backend.schemas import ActionQueued, CommandExecutionResult, PiCommandResult, ServiceRestartRequest
from backend.services import audit_log as al
from backend.services.actions import start_ssh_action

router = APIRouter()


@router.post("/restart", response_model=ActionQueued)
def restart_service(body: ServiceRestartRequest, actor: Actor = Depends(require_role("operator")),
                    db: Session = Depends(get_db)):
    pis = db.query(Pi).filter(Pi.position.in_(body.pis)).all()
    found = {p.position for p in pis}
    missing = [pos for pos in body.pis if pos not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown positions: {missing}")

    positions = [p.position for p in pis]
    command = f"systemctl restart {body.service}"
    action_id = start_ssh_action(db, "restart", positions, command, actor)
    return ActionQueued(action_id=action_id)


@router.get("/restart/{action_id}", response_model=CommandExecutionResult, dependencies=[Depends(require_role("viewer"))])
def get_restart_result(action_id: int, db: Session = Depends(get_db)):
    entry = al.get_action(db, action_id)
    if not entry or entry.action != "restart":
        raise HTTPException(status_code=404, detail=f"Restart action {action_id} not found")

    results: list[PiCommandResult] = []
    if entry.stdout:
        try:
            results = [PiCommandResult(**r) for r in json.loads(entry.stdout)]
        except (json.JSONDecodeError, TypeError):
            pass

    return CommandExecutionResult(
        action_id=entry.id,
        status=entry.status,
        results=results,
        started_at=entry.timestamp,
        completed_at=None,
    )
