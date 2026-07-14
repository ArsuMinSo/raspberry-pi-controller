import json
import re
import socket
import subprocess
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
    # raw is pre-computed % from awk on /proc/meminfo
    try:
        return round(float((raw or "").strip()), 1)
    except ValueError:
        return None


def _parse_temp(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
        return round(v / 1000.0, 1) if v > 1000 else round(float(v), 1)
    except ValueError:
        return None


_UPTIME_TIME_RE = re.compile(r"^\s*(\d{1,2}:\d{2}:\d{2})")
_UPTIME_DUR_RE = re.compile(r"up\s+(.*?),\s*(?:\d+\s+users?|load average)")
_UPTIME_DAYS_RE = re.compile(r"(\d+)\s+day")
_UPTIME_HHMM_RE = re.compile(r"(\d+):(\d+)$")
_UPTIME_MIN_RE = re.compile(r"(\d+)\s+min")


def _parse_uptime(raw: str) -> tuple[str | None, int | None]:
    """Parse `uptime` command output, e.g.
    '14:32:01 up 3 days, 22:15,  1 user,  load average: 0.10, 0.20, 0.30'
    into (current time-of-day 'HH:MM:SS', uptime in seconds).
    """
    raw = (raw or "").strip()
    if not raw:
        return None, None

    m_time = _UPTIME_TIME_RE.match(raw)
    pi_time = m_time.group(1) if m_time else None

    uptime_s = None
    m_dur = _UPTIME_DUR_RE.search(raw)
    if m_dur:
        dur = m_dur.group(1)
        days = 0
        hours = 0
        minutes = 0
        m_days = _UPTIME_DAYS_RE.search(dur)
        if m_days:
            days = int(m_days.group(1))
        m_hhmm = _UPTIME_HHMM_RE.search(dur)
        if m_hhmm:
            hours, minutes = int(m_hhmm.group(1)), int(m_hhmm.group(2))
        else:
            m_min = _UPTIME_MIN_RE.search(dur)
            if m_min:
                minutes = int(m_min.group(1))
        uptime_s = days * 86400 + hours * 3600 + minutes * 60

    return pi_time, uptime_s


def _ping(ip: str) -> bool:
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def check_health(ip: str, position: str, settings: SSHSettings) -> HealthCheckData:
    def _error(msg: str) -> HealthCheckData:
        return HealthCheckData(
            result=PiHealthResult(
                position=position,
                cpu_1m=None, cpu_5m=None, cpu_15m=None,
                mem_percent=None, temp_c=None,
                pi_time=None, uptime_s=None,
                error=msg,
            ),
            hostname=None, mac=None, pi_version=None, serial=None,
        )

    if not _ping(ip):
        return _error("unreachable (no ping response)")

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

        loadavg_raw  = run("cat /proc/loadavg")
        ncores_raw   = run("nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo")
        mem_pct_raw  = run(
            "awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} "
            "END{if(t>0) printf \"%.1f\", (t-a)/t*100}' /proc/meminfo"
        )
        temp_raw     = run("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
        hostname_raw = run("hostname").strip() or None
        mac_raw      = run("ip link show | awk '/link\\/ether/{print $2; exit}'").strip().lower()
        cpuinfo      = run("cat /proc/cpuinfo")
        uptime_raw   = run("uptime")

        cpu_1m, cpu_5m, cpu_15m = _parse_loadavg_pct(loadavg_raw, ncores_raw)
        mem_percent = _parse_mem_pct(mem_pct_raw)
        temp_c      = _parse_temp(temp_raw)
        pi_time, uptime_s = _parse_uptime(uptime_raw)

        model_line  = next((l for l in cpuinfo.splitlines() if l.lower().startswith("model")), "")
        serial_line = next((l for l in cpuinfo.splitlines() if l.lower().startswith("serial")), "")
        pi_version  = extract_pi_version(model_line)
        serial      = serial_line.split(":")[-1].strip() or None if serial_line else None
        mac         = mac_raw if is_valid_mac(mac_raw) else None

        return HealthCheckData(
            result=PiHealthResult(
                position=position,
                cpu_1m=cpu_1m, cpu_5m=cpu_5m, cpu_15m=cpu_15m,
                mem_percent=mem_percent, temp_c=temp_c,
                pi_time=pi_time, uptime_s=uptime_s,
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
                pi_time=None, uptime_s=None,
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
