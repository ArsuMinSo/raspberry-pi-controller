import json
import time

import paramiko

from backend.config import SSHSettings
from backend.utils.helpers import load_private_key
from backend.models import ActionLog, Pi
from backend.schemas import PiHealthResult
from backend.services import audit_log as al


def _parse_cpu(raw: str) -> float | None:
    try:
        return round(float(raw.strip()), 2)
    except (ValueError, AttributeError):
        return None


def _parse_mem(raw: str) -> tuple[int | None, int | None]:
    try:
        parts = raw.strip().split()
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None, None


def _parse_disk(raw: str) -> tuple[float | None, float | None]:
    try:
        parts = raw.strip().split()
        return round(int(parts[0]) / 1024, 2), round(int(parts[1]) / 1024, 2)
    except (ValueError, IndexError):
        return None, None


def check_health(ip: str, position: str, settings: SSHSettings) -> PiHealthResult:
    import socket

    key = load_private_key(settings.private_key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            ip,
            username=settings.username,
            pkey=key,
            timeout=settings.timeout_s,
            banner_timeout=settings.timeout_s,
            auth_timeout=settings.timeout_s,
        )

        def run(cmd: str) -> str:
            _, out, _ = client.exec_command(cmd, timeout=settings.timeout_s)
            return out.read().decode(errors="replace")

        cpu_raw = run("top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'")
        mem_raw = run("free -m | awk '/^Mem:/{print $2, $3}'")
        disk_raw = run("df -m / | awk 'NR==2{print $2, $3}'")

        cpu = _parse_cpu(cpu_raw)
        mem_total, mem_used = _parse_mem(mem_raw)
        disk_total, disk_used = _parse_disk(disk_raw)

        return PiHealthResult(
            position=position,
            cpu_percent=cpu,
            mem_used_mb=mem_used,
            mem_total_mb=mem_total,
            disk_used_gb=disk_used,
            disk_total_gb=disk_total,
            error=None,
        )
    except (paramiko.SSHException, OSError, socket.timeout) as e:
        return PiHealthResult(
            position=position,
            cpu_percent=None,
            mem_used_mb=None,
            mem_total_mb=None,
            disk_used_gb=None,
            disk_total_gb=None,
            error=str(e),
        )
    finally:
        client.close()


def run_health_check(pis: list[Pi], db, ssh: SSHSettings) -> int:
    positions = [p.position for p in pis]
    entry = al.create_action(db, positions, "health", status="running")
    start = time.monotonic()

    results: list[PiHealthResult] = []
    for pi in pis:
        if pi.current_ip is None:
            results.append(PiHealthResult(
                position=pi.position,
                cpu_percent=None,
                mem_used_mb=None,
                mem_total_mb=None,
                disk_used_gb=None,
                disk_total_gb=None,
                error="no IP recorded",
            ))
            continue
        results.append(check_health(str(pi.current_ip), pi.position, ssh))

    errors = [r for r in results if r.error]
    if len(errors) == 0:
        status = "success"
    elif len(errors) == len(results):
        status = "fail"
    else:
        status = "partial_fail"

    duration_ms = int((time.monotonic() - start) * 1000)
    al.update_action(
        db,
        entry.id,
        status=status,
        stdout=json.dumps([r.model_dump() for r in results]),
        duration_ms=duration_ms,
    )
    return entry.id
