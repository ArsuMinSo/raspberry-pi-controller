import json
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import effective_ssh_settings, get_settings
from backend.database import get_db
from backend.models import Pi
from backend.schemas import ActionQueued, PiCommandResult, ServiceRestartRequest
from backend.services import audit_log as al
from backend.services.ssh_executor import execute_many

router = APIRouter()


@router.post("/restart", response_model=ActionQueued)
def restart_service(body: ServiceRestartRequest, db: Session = Depends(get_db)):
    pis = db.query(Pi).filter(Pi.position.in_(body.pis)).all()
    found = {p.position for p in pis}
    missing = [pos for pos in body.pis if pos not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown positions: {missing}")

    positions = [p.position for p in pis]
    command = f"systemctl restart {body.service}"
    entry = al.create_action(db, positions, "restart", command=command, status="running")
    start = time.monotonic()

    targets = [
        (str(p.current_ip), p.position)
        for p in pis
        if p.current_ip
    ]
    skipped = [
        PiCommandResult(position=p.position, exit_code=None, stdout=None, stderr=None, error="no IP recorded")
        for p in pis
        if not p.current_ip
    ]

    ssh_results = execute_many(targets, command, effective_ssh_settings())
    all_results = skipped + [
        PiCommandResult(
            position=r.position,
            exit_code=r.exit_code,
            stdout=r.stdout or None,
            stderr=r.stderr or None,
            error=r.error,
        )
        for r in ssh_results
    ]

    errors = [r for r in all_results if r.error or (r.exit_code is not None and r.exit_code != 0)]
    if len(errors) == 0:
        status = "success"
    elif len(errors) == len(all_results):
        status = "fail"
    else:
        status = "partial_fail"

    duration_ms = int((time.monotonic() - start) * 1000)
    al.update_action(
        db, entry.id, status=status,
        stdout=json.dumps([r.model_dump() for r in all_results]),
        duration_ms=duration_ms,
    )
    return ActionQueued(action_id=entry.id)
