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


# Single script — one SSH exec per Pi instead of N round trips.
# Sections delimited by ---SEP--- so output is split by index.
# Sections: loadavg | ncores | mem(total used) | temp_milli | hostname | mac | cpuinfo
_HEALTH_SCRIPT = (
    "cat /proc/loadavg; echo '---SEP---';"
    " nproc; echo '---SEP---';"
    " free -m | awk '/^Mem:/{print $2, $3}'; echo '---SEP---';"
    " cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0; echo '---SEP---';"
    " hostname; echo '---SEP---';"
    " ip link show | awk '/link\\/ether/{print $2; exit}'; echo '---SEP---';"
    " cat /proc/cpuinfo"
)


def _parse_loadavg_pct(
    loadavg_raw: str, ncores_raw: str
) -> tuple[float | None, float | None, float | None]:
    try:
        ncores = max(int(ncores_raw.strip()), 1)
    except (ValueError, AttributeError):
        ncores = 1
    try:
        parts = loadavg_raw.strip().split()
        l1, l5, l15 = float(parts[0]), float(parts[1]), float(parts[2])
        def pct(load: float) -> float:
            return round(min(load / ncores * 100.0, 100.0), 1)
        return pct(l1), pct(l5), pct(l15)
    except (ValueError, IndexError, AttributeError):
        return None, None, None


def _parse_mem_pct(raw: str) -> float | None:
    try:
        total, used = (int(x) for x in raw.strip().split())
        if total == 0:
            return None
        return round(used / total * 100.0, 1)
    except (ValueError, AttributeError):
        return None


def _parse_temp(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw or raw == "0":
        return None
    try:
        v = int(raw)
        return round(v / 1000.0, 1) if v > 1000 else round(float(v), 1)
    except ValueError:
        return None


def check_health(ip: str, position: str, settings: SSHSettings) -> HealthCheckData:
    import socket

    key = load_private_key(settings.private_key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def _error(msg: str) -> HealthCheckData:
        return HealthCheckData(
            result=PiHealthResult(
                position=position,
                cpu_1m=None, cpu_5m=None, cpu_15m=None,
                mem_percent=None, temp_c=None,
                error=msg,
            ),
            hostname=None, mac=None, pi_version=None, serial=None,
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
        _, out, _ = client.exec_command(_HEALTH_SCRIPT, timeout=settings.timeout_s)
        raw = out.read().decode(errors="replace")

        parts = [p.strip() for p in raw.split("---SEP---")]

        def sec(i: int) -> str:
            return parts[i] if i < len(parts) else ""

        loadavg_raw  = sec(0)
        ncores_raw   = sec(1)
        mem_raw      = sec(2)
        temp_raw     = sec(3)
        hostname_raw = sec(4) or None
        mac_raw      = sec(5).lower()
        cpuinfo      = sec(6)

        cpu_1m, cpu_5m, cpu_15m = _parse_loadavg_pct(loadavg_raw, ncores_raw)
        mem_percent = _parse_mem_pct(mem_raw)
        temp_c = _parse_temp(temp_raw)

        model_line  = next((l for l in cpuinfo.splitlines() if l.lower().startswith("model")), "")
        serial_line = next((l for l in cpuinfo.splitlines() if l.lower().startswith("serial")), "")
        pi_version = extract_pi_version(model_line)
        serial = serial_line.split(":")[-1].strip() or None if serial_line else None
        mac = mac_raw if is_valid_mac(mac_raw) else None

        return HealthCheckData(
            result=PiHealthResult(
                position=position,
                cpu_1m=cpu_1m, cpu_5m=cpu_5m, cpu_15m=cpu_15m,
                mem_percent=mem_percent, temp_c=temp_c,
                error=None,
            ),
            hostname=hostname_raw, mac=mac, pi_version=pi_version, serial=serial,
        )
    except (paramiko.SSHException, OSError, socket.timeout) as e:
        return _error(str(e))
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

    for pi in pis:
        if pi.current_ip is None:
            results.append(PiHealthResult(
                position=pi.position,
                cpu_1m=None, cpu_5m=None, cpu_15m=None,
                mem_percent=None, temp_c=None,
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
        db, entry.id,
        status=status,
        stdout=json.dumps([r.model_dump() for r in results]),
        duration_ms=duration_ms,
    )
    return entry.id
