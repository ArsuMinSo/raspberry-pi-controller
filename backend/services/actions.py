"""SSH command actions (execute / kill / restart) as background jobs."""
import json
import time
from functools import partial

from sqlalchemy.orm import Session

from backend.auth import Actor
from backend.config import effective_ssh_settings
from backend.models import ActionLog, Pi
from backend.schemas import PiCommandResult
from backend.services import audit_log as al
from backend.services import jobs
from backend.services.ssh_executor import SSHResult, execute_many


def overall_status(results: list[PiCommandResult]) -> str:
    errors = [r for r in results if r.error or (r.exit_code is not None and r.exit_code != 0)]
    if not errors:
        return "success"
    return "fail" if len(errors) == len(results) else "partial_fail"


def ssh_job(
    db: Session,
    entry: ActionLog,
    command: str,
    ssh_username: str | None = None,
    ssh_password: str | None = None,
) -> None:
    """Run `command` on the action's Pis; one action_results row per Pi as it finishes."""
    start = time.monotonic()
    pis = db.query(Pi).filter(Pi.position.in_(entry.pis_selected)).all()

    results: list[PiCommandResult] = []
    targets = []
    for pi in pis:
        if pi.current_ip is None:
            results.append(PiCommandResult(position=pi.position, exit_code=None, stdout=None, stderr=None,
                                           error="no IP recorded"))
            al.add_result(db, entry.id, pi.position, error="no IP recorded")
        else:
            targets.append((str(pi.current_ip), pi.position))

    def on_result(r: SSHResult) -> None:
        al.add_result(db, entry.id, r.position, exit_code=r.exit_code, stdout=r.stdout, stderr=r.stderr,
                      error=r.error, duration_ms=r.duration_ms)

    ssh_results = execute_many(targets, command, effective_ssh_settings(), ssh_username, ssh_password,
                               on_result=on_result)
    results += [
        PiCommandResult(position=r.position, exit_code=r.exit_code, stdout=r.stdout or None,
                        stderr=r.stderr or None, error=r.error)
        for r in ssh_results
    ]
    al.update_action(
        db, entry.id,
        status=overall_status(results),
        stdout=json.dumps([r.model_dump() for r in results]),
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def start_ssh_action(
    db: Session,
    action: str,
    positions: list[str],
    command: str,
    actor: Actor | None,
    ssh_username: str | None = None,
    ssh_password: str | None = None,
    wait: bool = False,
) -> int:
    """Create the queued action and run it — in the background, or right here if `wait` (scheduler)."""
    entry = al.create_action(db, positions, action, command=command, status="queued", actor=actor)
    work = partial(ssh_job, command=command, ssh_username=ssh_username, ssh_password=ssh_password)
    if wait:
        jobs.run_action(entry.id, work)
    else:
        jobs.submit(jobs.run_action, entry.id, work)
    return entry.id
