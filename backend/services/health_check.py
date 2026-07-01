import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import paramiko
from sqlalchemy.sql import func

from backend.config import SSHSettings
from backend.utils.helpers import MAC_PLACEHOLDER, extract_pi_version, is_valid_mac, load_private_key
from backend.models import Pi
from backend.schemas import PiHealthResult
from backend.services import audit_log as al


@dataclass
class HealthCheckData:
    result: PiHealthResult
    hostname: str | None
    mac: str | None
    pi_version: int | None
    serial: str | None


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


def check_health(ip: str, position: str, settings: SSHSettings) -> HealthCheckData:
    import socket

    key = load_private_key(settings.private_key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def _error_data(msg: str) -> HealthCheckData:
        return HealthCheckData(
            result=PiHealthResult(
                position=position,
                cpu_percent=None,
                mem_used_mb=None,
                mem_total_mb=None,
                disk_used_gb=None,
                disk_total_gb=None,
                error=msg,
            ),
            hostname=None,
            mac=None,
            pi_version=None,
            serial=None,
        )

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
        hostname_raw = run("hostname").strip() or None
        cpuinfo = run("cat /proc/cpuinfo")
        mac_raw = run(
            "ip link show | awk '/link\\/ether/{print $2; exit}'"
        ).strip().lower()

        model_line = next(
            (l for l in cpuinfo.splitlines() if l.lower().startswith("model")), ""
        )
        serial_line = next(
            (l for l in cpuinfo.splitlines() if l.lower().startswith("serial")), ""
        )
        pi_version = extract_pi_version(model_line)
        serial = serial_line.split(":")[-1].strip() or None if serial_line else None
        mac = mac_raw if is_valid_mac(mac_raw) else None

        cpu = _parse_cpu(cpu_raw)
        mem_total, mem_used = _parse_mem(mem_raw)
        disk_total, disk_used = _parse_disk(disk_raw)

        return HealthCheckData(
            result=PiHealthResult(
                position=position,
                cpu_percent=cpu,
                mem_used_mb=mem_used,
                mem_total_mb=mem_total,
                disk_used_gb=disk_used,
                disk_total_gb=disk_total,
                error=None,
            ),
            hostname=hostname_raw,
            mac=mac,
            pi_version=pi_version,
            serial=serial,
        )
    except (paramiko.SSHException, OSError, socket.timeout) as e:
        return _error_data(str(e))
    finally:
        client.close()


def run_health_check(pis: list[Pi], db, ssh: SSHSettings) -> int:
    positions = [p.position for p in pis]
    entry = al.create_action(db, positions, "health", status="running")
    start = time.monotonic()

    targets = [(str(pi.current_ip), pi.position) for pi in pis if pi.current_ip is not None]
    workers = min(ssh.parallel_limit, max(1, len(targets)))
    data_map: dict[str, HealthCheckData] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(check_health, ip, pos, ssh): pos for ip, pos in targets}
        for future in as_completed(futures):
            d = future.result()
            data_map[d.result.position] = d

    results: list[PiHealthResult] = []
    pi_map = {p.position: p for p in pis}

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

        d = data_map[pi.position]
        results.append(d.result)

        if d.result.error is None:
            pi.status = "reachable"
            pi.last_seen = func.now()
            if d.hostname:
                pi.hostname = d.hostname
            if d.mac and d.mac != MAC_PLACEHOLDER:
                pi.mac = d.mac
            if d.pi_version is not None:
                pi.pi_version = d.pi_version
            if d.serial:
                pi.serial = d.serial
        else:
            pi.status = "unreachable"

    db.commit()

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
