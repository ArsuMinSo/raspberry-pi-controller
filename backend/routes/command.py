import json
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import get_db
from backend.models import Pi
from backend.schemas import (
    ActionQueued,
    CommandExecuteRequest,
    CommandExecutionResult,
    PiCommandResult,
)
from backend.services import audit_log as al
from backend.services.ssh_executor import execute_many

router = APIRouter()


def _run_command(pis: list[Pi], command: str, db: Session) -> int:
    settings = get_settings()
    positions = [p.position for p in pis]
    entry = al.create_action(db, positions, "execute", command=command, status="running")
    start = time.monotonic()

    targets = []
    skipped: list[PiCommandResult] = []
    for pi in pis:
        if pi.current_ip is None or pi.status == "unreachable":
            skipped.append(PiCommandResult(
                position=pi.position,
                exit_code=None,
                stdout=None,
                stderr=None,
                error="unreachable",
            ))
        else:
            targets.append((str(pi.current_ip), pi.position))

    ssh_results = execute_many(targets, command, settings.ssh)

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
        db,
        entry.id,
        status=status,
        stdout=json.dumps([r.model_dump() for r in all_results]),
        duration_ms=duration_ms,
    )
    return entry.id


@router.post("/execute", response_model=ActionQueued)
def execute_command(body: CommandExecuteRequest, db: Session = Depends(get_db)):
    pis = db.query(Pi).filter(Pi.position.in_(body.pis)).all()
    found = {p.position for p in pis}
    missing = [pos for pos in body.pis if pos not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown positions: {missing}")

    action_id = _run_command(pis, body.command, db)
    return ActionQueued(action_id=action_id)


@router.get("/{action_id}", response_model=CommandExecutionResult)
def get_command_result(action_id: int, db: Session = Depends(get_db)):
    entry = al.get_action(db, action_id)
    if not entry or entry.action != "execute":
        raise HTTPException(status_code=404, detail=f"Command action {action_id} not found")

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
