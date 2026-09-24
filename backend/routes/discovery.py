import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import Actor, require_role
from backend.config import effective_network_settings, effective_ssh_settings
from backend.database import get_db
from backend.schemas import ActionQueued, DiscoveredPi, DiscoveryScanResult
from backend.services import audit_log as al
from backend.services.discovery import start_discovery

router = APIRouter()


class ScanRequest(BaseModel):
    probe_password: str | None = None


@router.post("/scan", response_model=ActionQueued)
def start_scan(body: ScanRequest = None, actor: Actor = Depends(require_role("operator")),
               db: Session = Depends(get_db)):
    net = effective_network_settings()
    action_id = start_discovery(db, net.subnet, effective_ssh_settings(), net,
                                probe_password=body.probe_password if body else None, actor=actor)
    return ActionQueued(action_id=action_id)


@router.get("/scan/{action_id}", response_model=DiscoveryScanResult, dependencies=[Depends(require_role("viewer"))])
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
