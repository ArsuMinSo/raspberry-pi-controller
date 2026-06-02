from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Pi
from backend.schemas import PiDetail, PiSummary
from backend.utils.helpers import paginate, validate_position

router = APIRouter()


def _pi_to_summary(pi: Pi) -> PiSummary:
    return PiSummary(
        id=pi.id,
        mac=pi.mac,
        hostname=pi.hostname,
        position=pi.position,
        ip=str(pi.current_ip) if pi.current_ip else None,
        status=pi.status,
        last_seen=pi.last_seen,
        tags=pi.tags or [],
    )


def _pi_to_detail(pi: Pi) -> PiDetail:
    return PiDetail(
        id=pi.id,
        mac=pi.mac,
        hostname=pi.hostname,
        position=pi.position,
        ip=str(pi.current_ip) if pi.current_ip else None,
        status=pi.status,
        last_seen=pi.last_seen,
        tags=pi.tags or [],
        serial=pi.serial,
        pi_version=pi.pi_version,
        created_at=pi.created_at,
        updated_at=pi.updated_at,
    )


@router.get("/list", response_model=list[PiSummary])
def list_pis(
    status: str | None = Query(None),
    tags: list[str] | None = Query(None),
    version: int | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Pi)
    if status:
        q = q.filter(Pi.status == status)
    if tags:
        q = q.filter(Pi.tags.contains(tags))
    if version:
        q = q.filter(Pi.pi_version == version)
    q = q.order_by(Pi.position)
    rows = paginate(q, page, limit).all()
    return [_pi_to_summary(p) for p in rows]


@router.get("/{position}/status", response_model=PiDetail)
def get_pi_status(position: str, db: Session = Depends(get_db)):
    try:
        pos = validate_position(position)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    pi = db.query(Pi).filter(Pi.position == pos).first()
    if not pi:
        raise HTTPException(status_code=404, detail=f"Pi at position {position} not found")
    return _pi_to_detail(pi)
