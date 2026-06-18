import os
import socket

import paramiko
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.config import effective_ssh_settings
from backend.database import get_db
from backend.models import Pi
from backend.schemas import (
    DeployKeyRequest, DeployKeyResponse, DeployKeyResult,
    PiCreateRequest, PiDetail, PiSummary, PiUpdateRequest,
)
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


@router.post("/deploy-key", response_model=DeployKeyResponse)
def deploy_key(body: DeployKeyRequest, db: Session = Depends(get_db)):
    ssh = effective_ssh_settings()
    pub_key_path = ssh.private_key_path + ".pub"
    if not os.path.exists(pub_key_path):
        raise HTTPException(status_code=400, detail=f"Public key not found: {pub_key_path}")
    pub_key = open(pub_key_path).read().strip()

    # Shell command equivalent to ssh-copy-id
    install_cmd = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"grep -qF '{pub_key}' ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo '{pub_key}' >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys"
    )

    pis = db.query(Pi).filter(Pi.position.in_(body.pis)).all()
    found = {p.position for p in pis}
    missing = [pos for pos in body.pis if pos not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown positions: {missing}")

    results: list[DeployKeyResult] = []
    for pi in pis:
        ip = str(pi.current_ip) if pi.current_ip else None
        if not ip:
            results.append(DeployKeyResult(
                position=pi.position, ip=None, success=False, error="no IP recorded"
            ))
            continue

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                ip,
                username=ssh.username,
                password=body.password,
                timeout=ssh.timeout_s,
                banner_timeout=ssh.timeout_s,
                auth_timeout=ssh.timeout_s,
                look_for_keys=False,
                allow_agent=False,
            )
            _, stdout_fh, stderr_fh = client.exec_command(install_cmd, timeout=15)
            stdout_fh.channel.recv_exit_status()
            stderr = stderr_fh.read().decode(errors="replace").strip()
            results.append(DeployKeyResult(
                position=pi.position, ip=ip, success=True,
                error=stderr if stderr else None,
            ))
        except paramiko.AuthenticationException:
            results.append(DeployKeyResult(
                position=pi.position, ip=ip, success=False, error="Authentication failed — wrong password?"
            ))
        except (paramiko.SSHException, OSError, socket.timeout) as e:
            results.append(DeployKeyResult(
                position=pi.position, ip=ip, success=False, error=str(e)
            ))
        finally:
            client.close()

    succeeded = sum(1 for r in results if r.success)
    return DeployKeyResponse(results=results, succeeded=succeeded, failed=len(results) - succeeded)


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
