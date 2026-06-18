from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Pi
from backend.schemas import PiCreateRequest, PiDetail, PiSummary, PiUpdateRequest
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


@router.post("", response_model=PiDetail, status_code=201)
def create_pi(body: PiCreateRequest, db: Session = Depends(get_db)):
    if db.query(Pi).filter(Pi.position == body.position).first():
        raise HTTPException(status_code=409, detail=f"Position {body.position} already exists")
    pi = Pi(
        position=body.position,
        mac=body.mac.lower(),
        hostname=body.hostname,
        current_ip=body.ip,
        pi_version=body.pi_version,
        tags=body.tags,
        status=body.status,
    )
    db.add(pi)
    db.commit()
    db.refresh(pi)
    return _pi_to_detail(pi)


@router.patch("/{position}", response_model=PiDetail)
def update_pi(position: str, body: PiUpdateRequest, db: Session = Depends(get_db)):
    try:
        pos = validate_position(position)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    pi = db.query(Pi).filter(Pi.position == pos).first()
    if not pi:
        raise HTTPException(status_code=404, detail=f"Pi at position {position} not found")
    if body.mac is not None:
        pi.mac = body.mac.lower()
    if body.hostname is not None:
        pi.hostname = body.hostname
    if body.ip is not None:
        pi.current_ip = body.ip
    if body.pi_version is not None:
        pi.pi_version = body.pi_version
    if body.tags is not None:
        pi.tags = body.tags
    if body.status is not None:
        pi.status = body.status
    db.commit()
    db.refresh(pi)
    return _pi_to_detail(pi)


@router.delete("/{position}", status_code=204)
def delete_pi(position: str, db: Session = Depends(get_db)):
    try:
        pos = validate_position(position)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    pi = db.query(Pi).filter(Pi.position == pos).first()
    if not pi:
        raise HTTPException(status_code=404, detail=f"Pi at position {position} not found")
    db.delete(pi)
    db.commit()
