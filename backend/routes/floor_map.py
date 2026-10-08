from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import Actor, require_role
from backend.database import get_db
from backend.models import AccessPoint, Pi, WifiScan
from backend.schemas import (
    AccessPointGroupUpdate, AccessPointOut, AccessPointPositionUpdate, ActionQueued, BleDeviceSeen,
    FloorMapPiNode, FloorMapResponse, FloorMapSettingsUpdate, HealthTriggerRequest, PiPinUpdate,
)
from backend.services.floor_map import (
    clear_all_links, compute_pi_position, get_ble_devices_for_position, get_floor_map, set_plan_visible,
    start_ble_scan, start_wifi_scan,
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


@router.patch("/ap/{bssid}/group", response_model=AccessPointOut)
def set_access_point_group(bssid: str, body: AccessPointGroupUpdate,
                            actor: Actor = Depends(require_role("operator")), db: Session = Depends(get_db)):
    ap = db.get(AccessPoint, bssid.lower())
    if ap is None:
        raise HTTPException(status_code=404, detail=f"Access point {bssid} not found")
    ap.group_name = body.group_name
    db.commit()
    db.refresh(ap)
    return AccessPointOut.model_validate(ap)


@router.get("/groups", response_model=list[str], dependencies=[Depends(require_role("viewer"))])
def list_access_point_groups(db: Session = Depends(get_db)):
    rows = db.query(AccessPoint.group_name).filter(AccessPoint.group_name.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows})


@router.delete("/ap/{bssid}", status_code=204)
def delete_access_point(bssid: str, actor: Actor = Depends(require_role("operator")), db: Session = Depends(get_db)):
    """Removes this BSSID entirely — box disappears from the map. A WiFi scan that still sees it
    re-registers it as unplaced, same as any never-before-seen AP."""
    ap = db.get(AccessPoint, bssid.lower())
    if ap is None:
        raise HTTPException(status_code=404, detail=f"Access point {bssid} not found")
    db.query(WifiScan).filter(WifiScan.bssid == bssid.lower()).delete()
    db.delete(ap)
    db.commit()


@router.patch("/pi/{position}/pin", response_model=FloorMapPiNode)
def pin_pi(position: str, body: PiPinUpdate, actor: Actor = Depends(require_role("operator")),
           db: Session = Depends(get_db)):
    pi = db.query(Pi).filter(Pi.position == position).first()
    if pi is None:
        raise HTTPException(status_code=404, detail=f"Pi {position} not found")
    pi.pinned_x = body.x
    pi.pinned_y = body.y
    db.commit()
    db.refresh(pi)

    last_scan = db.query(func.max(WifiScan.timestamp)).filter(WifiScan.pi_rid == pi.rid).scalar()
    if pi.pinned_x is not None and pi.pinned_y is not None:
        x, y, pinned = pi.pinned_x, pi.pinned_y, True
    else:
        pos = compute_pi_position(db, pi.mac)
        x, y, pinned = (pos[0], pos[1], False) if pos else (None, None, False)
    return FloorMapPiNode(position=pi.position, mac=pi.mac, x=x, y=y, pinned=pinned, last_scan_at=last_scan)


@router.get("/pi/{position}/ble", response_model=list[BleDeviceSeen], dependencies=[Depends(require_role("viewer"))])
def read_ble_devices(position: str, db: Session = Depends(get_db)):
    return get_ble_devices_for_position(db, position)


@router.delete("/links")
def delete_all_links(actor: Actor = Depends(require_role("operator")), db: Session = Depends(get_db)):
    cleared = clear_all_links(db)
    return {"cleared": cleared}


@router.patch("/settings")
def patch_floor_map_settings(body: FloorMapSettingsUpdate, actor: Actor = Depends(require_role("viewer")),
                              db: Session = Depends(get_db)):
    return {"plan_visible": set_plan_visible(db, body.plan_visible)}
