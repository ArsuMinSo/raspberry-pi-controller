from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth import Actor, require_role
from backend.database import get_db
from backend.models import AccessPoint, Pi
from backend.schemas import (
    AccessPointOut, AccessPointPositionUpdate, ActionQueued, BleDeviceSeen,
    FloorMapResponse, HealthTriggerRequest,
)
from backend.services.floor_map import (
    get_ble_devices_for_position, get_floor_map, start_ble_scan, start_wifi_scan,
)

router = APIRouter()


def _resolve_targets(db: Session, body: HealthTriggerRequest) -> list[str]:
    if body.all:
        pis = db.query(Pi).filter(Pi.status == "reachable").all()
        if not pis:
            raise HTTPException(status_code=404, detail="No reachable Pis found")
        return [p.position for p in pis]

    pis = db.query(Pi).filter(Pi.position.in_(body.pis)).all()
    found = {p.position for p in pis}
    missing = [pos for pos in body.pis if pos not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown positions: {missing}")
    return [p.position for p in pis]


@router.post("/wifi-scan", response_model=ActionQueued)
def trigger_wifi_scan(body: HealthTriggerRequest, actor: Actor = Depends(require_role("operator")),
                       db: Session = Depends(get_db)):
    action_id = start_wifi_scan(db, _resolve_targets(db, body), actor=actor)
    return ActionQueued(action_id=action_id)


@router.post("/ble-scan", response_model=ActionQueued)
def trigger_ble_scan(body: HealthTriggerRequest, actor: Actor = Depends(require_role("operator")),
                      db: Session = Depends(get_db)):
    action_id = start_ble_scan(db, _resolve_targets(db, body), actor=actor)
    return ActionQueued(action_id=action_id)


@router.get("", response_model=FloorMapResponse, dependencies=[Depends(require_role("viewer"))])
def read_floor_map(db: Session = Depends(get_db)):
    return get_floor_map(db)


@router.patch("/ap/{bssid}", response_model=AccessPointOut)
def place_access_point(bssid: str, body: AccessPointPositionUpdate,
                        actor: Actor = Depends(require_role("operator")), db: Session = Depends(get_db)):
    ap = db.get(AccessPoint, bssid.lower())
    if ap is None:
        raise HTTPException(status_code=404, detail=f"Access point {bssid} not found")
    ap.x = body.x
    ap.y = body.y
    ap.placed_by_user_id = actor.user_id
    db.commit()
    db.refresh(ap)
    return AccessPointOut.model_validate(ap)


@router.get("/pi/{position}/ble", response_model=list[BleDeviceSeen], dependencies=[Depends(require_role("viewer"))])
def read_ble_devices(position: str, db: Session = Depends(get_db)):
    return get_ble_devices_for_position(db, position)
