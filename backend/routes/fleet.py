"""Fleet actions (reboot, diagnostics) and the fleet summary."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import Actor, require_role
from backend.config import get_settings
from backend.database import get_db
from backend.models import ActionLog, Pi
from backend.schemas import ActionQueued, FleetPiValue, FleetSummary, PiSelection
from backend.services import diagnostics
from backend.services.actions import start_ssh_action

router = APIRouter()

TOP_N = 5


def _known_positions(db: Session, positions: list[str]) -> list[str]:
    """The requested positions, all known — else 422 (same rule as the other action endpoints)."""
    found = {p for (p,) in db.query(Pi.position).filter(Pi.position.in_(positions)).all()}
    missing = [pos for pos in positions if pos not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown positions: {missing}")
    return [pos for pos in dict.fromkeys(positions)]  # keep order, drop duplicates


@router.post("/pi/reboot", response_model=ActionQueued)
def reboot(body: PiSelection, actor: Actor = Depends(require_role("operator")), db: Session = Depends(get_db)):
    """Schedules a reboot a few seconds out, so the SSH command returns before the Pi goes down."""
    positions = _known_positions(db, body.pis)
    action_id = start_ssh_action(db, "reboot", positions, get_settings().pi_commands.reboot, actor,
                                 explain=diagnostics.reboot_error)
    return ActionQueued(action_id=action_id)


@router.post("/diagnostics", response_model=ActionQueued)
def run_diagnostics(body: PiSelection, actor: Actor = Depends(require_role("operator")),
                    db: Session = Depends(get_db)):
    """Throttling/undervoltage flags + root disk usage per Pi (results in action_results.details)."""
    positions = _known_positions(db, body.pis)
    cmds = get_settings().pi_commands
    command = diagnostics.build_command(cmds.throttled, cmds.disk)
    action_id = start_ssh_action(db, "diagnostics", positions, command, actor, parse=diagnostics.parse_output)
    return ActionQueued(action_id=action_id)


@router.get("/fleet/summary", response_model=FleetSummary, dependencies=[Depends(require_role("viewer"))])
def fleet_summary(stale_hours: int = Query(24, ge=1, le=24 * 365), db: Session = Depends(get_db)):
    """Database only (no SSH): counts, stale Pis and the top Pis by temperature / CPU / memory."""
    counts = dict(db.query(Pi.status, func.count()).group_by(Pi.status).all())

    # Compare in the database (now() - interval) — last_seen is written in the DB session's time zone
    cutoff = func.now() - timedelta(hours=stale_hours)
    stale = [p for (p,) in db.query(Pi.position).filter(Pi.last_seen < cutoff).order_by(Pi.position).all()]
    never = [p for (p,) in db.query(Pi.position).filter(Pi.last_seen.is_(None)).order_by(Pi.position).all()]

    def top(column) -> list[FleetPiValue]:
        rows = (
            db.query(Pi.position, Pi.hostname, column)
            .filter(column.isnot(None))
            .order_by(column.desc())
            .limit(TOP_N)
            .all()
        )
        return [FleetPiValue(position=p, hostname=h, value=v) for p, h, v in rows]

    last_health = db.query(func.max(ActionLog.timestamp)).filter(ActionLog.action == "health").scalar()
    return FleetSummary(
        total=sum(counts.values()),
        reachable=counts.get("reachable", 0),
        unreachable=counts.get("unreachable", 0),
        stale_hours=stale_hours,
        stale=stale,
        never_seen=never,
        hottest=top(Pi.temp_c),
        busiest_cpu=top(Pi.cpu_1m),
        highest_mem=top(Pi.mem_percent),
        last_health_check_at=last_health,
    )
