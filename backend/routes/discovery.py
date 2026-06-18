import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import get_db
from backend.schemas import ActionQueued, DiscoveredPi, DiscoveryScanResult
from backend.services import audit_log as al
from backend.services.discovery import scan_subnet

router = APIRouter()


@router.post("/scan", response_model=DiscoveryScanResult)
def start_scan(db: Session = Depends(get_db)):
    settings = get_settings()
    result = scan_subnet(settings.network.subnet, db, settings)
    return result


@router.get("/scan/{action_id}", response_model=DiscoveryScanResult)
def get_scan_result(action_id: int, db: Session = Depends(get_db)):
    entry = al.get_action(db, action_id)
    if not entry or entry.action != "discovery":
        raise HTTPException(status_code=404, detail=f"Discovery action {action_id} not found")

    discovered: list[DiscoveredPi] = []
    added = 0
    updated = 0

    if entry.stdout:
        try:
            data = json.loads(entry.stdout)
            discovered = [DiscoveredPi(**d) for d in data.get("discovered", [])]
            added = data.get("added", 0)
            updated = data.get("updated", 0)
        except (json.JSONDecodeError, TypeError):
            pass

    return DiscoveryScanResult(
        action_id=entry.id,
        status=entry.status,
        discovered=discovered,
        added=added,
        updated=updated,
        started_at=entry.timestamp,
        completed_at=None,
    )
