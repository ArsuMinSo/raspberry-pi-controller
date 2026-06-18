import ipaddress
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import paramiko
from sqlalchemy import cast, Text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from backend.config import NetworkSettings, SSHSettings
from backend.utils.helpers import load_private_key
from backend.models import Pi
from backend.schemas import DiscoveredPi, DiscoveryScanResult
from backend.services import audit_log as al

_PI_VERSION_RE = re.compile(r"raspberry pi (\d+)", re.IGNORECASE)


def ping_host(ip: str) -> bool:
    result = subprocess.run(
        ["ping", "-c1", "-W1", ip],
        capture_output=True,
    )
    return result.returncode == 0


def _extract_pi_version(model_line: str) -> int | None:
    m = _PI_VERSION_RE.search(model_line)
    if m:
        return int(m.group(1))
    return None


def probe_pi(ip: str, ssh: SSHSettings, probe_timeout_s: int = 3) -> tuple[str | None, str | None, int | None]:
    """Returns (hostname, pi_version, serial) via SSH. All None on failure."""
    import socket
    key = load_private_key(ssh.private_key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            ip,
            username=ssh.username,
            pkey=key,
            timeout=probe_timeout_s,
            banner_timeout=probe_timeout_s,
            auth_timeout=probe_timeout_s,
        )

        def run(cmd):
            _, out, _ = client.exec_command(cmd, timeout=5)
            return out.read().decode(errors="replace").strip()

        hostname = run("hostname") or None
        cpuinfo = run("cat /proc/cpuinfo")
        model_line = next(
            (l for l in cpuinfo.splitlines() if l.lower().startswith("model")), ""
        )
        serial_line = next(
            (l for l in cpuinfo.splitlines() if l.lower().startswith("serial")), ""
        )
        pi_version = _extract_pi_version(model_line)
        serial = serial_line.split(":")[-1].strip() if serial_line else None
        return hostname, pi_version, serial
    except (paramiko.SSHException, OSError, socket.timeout):
        return None, None, None
    finally:
        client.close()


def _parse_hosts(scan_range: str) -> list:
    """Accept CIDR (10.10.20.0/24) or start-end range (10.10.30.25-10.10.30.50)."""
    scan_range = scan_range.strip()
    if "-" in scan_range and "/" not in scan_range:
        start_s, end_s = scan_range.split("-", 1)
        start_ip = ipaddress.IPv4Address(start_s.strip())
        end_ip = ipaddress.IPv4Address(end_s.strip())
        if int(end_ip) < int(start_ip):
            raise ValueError(f"End address {end_ip} is before start {start_ip}")
        return [ipaddress.IPv4Address(i) for i in range(int(start_ip), int(end_ip) + 1)]
    return list(ipaddress.ip_network(scan_range, strict=False).hosts())


def _scan_host(
    ip: str,
    ssh_settings: SSHSettings,
    do_probe: bool,
    probe_timeout: int,
) -> tuple[str, str | None, int | None, str | None] | None:
    """Ping + optional SSH probe for one host. Returns None if host unreachable."""
    if not ping_host(ip):
        return None
    if do_probe:
        hostname, pi_version, serial = probe_pi(ip, ssh_settings, probe_timeout)
    else:
        hostname, pi_version, serial = None, None, None
    return (ip, hostname, pi_version, serial)


def scan_subnet(
    subnet: str,
    db: Session,
    ssh_settings: SSHSettings,
    net_settings: NetworkSettings | None = None,
) -> DiscoveryScanResult:
    entry = al.create_action(db, [], "discovery", status="running")
    start = time.monotonic()

    do_probe = net_settings.probe_ssh if net_settings else True
    probe_timeout = net_settings.probe_timeout_s if net_settings else 3

    hosts = [str(h) for h in _parse_hosts(subnet)]
    workers = min(64, max(1, len(hosts)))

    # Parallel ping + probe
    alive: list[tuple[str, str | None, int | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_scan_host, ip, ssh_settings, do_probe, probe_timeout): ip
            for ip in hosts
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                alive.append(result)

    # Sort by IP for stable output
    alive.sort(key=lambda r: ipaddress.IPv4Address(r[0]))

    discovered: list[DiscoveredPi] = []
    discovered_ips: set[str] = set()
    added = 0
    updated = 0

    for ip, hostname, pi_version, serial in alive:
        discovered.append(DiscoveredPi(ip=ip, mac=None, hostname=hostname, pi_version=pi_version))
        discovered_ips.add(ip)

        existing = db.query(Pi).filter(Pi.current_ip == ip).first()
        if existing:
            existing.status = "reachable"
            existing.last_seen = func.now()
            if hostname:
                existing.hostname = hostname
            if pi_version:
                existing.pi_version = pi_version
            if serial:
                existing.serial = serial
            updated += 1
        else:
            added += 1

    db.commit()

    # Mark reachable Pis whose IP didn't respond as unreachable
    reachable_q = db.query(Pi).filter(Pi.status == "reachable")
    if discovered_ips:
        reachable_q = reachable_q.filter(
            cast(Pi.current_ip, Text).notin_(discovered_ips)
        )
    reachable_q.update({"status": "unreachable"}, synchronize_session=False)
    db.commit()

    duration_ms = int((time.monotonic() - start) * 1000)
    al.update_action(
        db,
        entry.id,
        status="success",
        stdout=json.dumps({
            "discovered": [d.model_dump() for d in discovered],
            "added": added,
            "updated": updated,
        }),
        duration_ms=duration_ms,
    )

    return DiscoveryScanResult(
        action_id=entry.id,
        status="success",
        discovered=discovered,
        added=added,
        updated=updated,
        started_at=entry.timestamp,
        completed_at=None,
    )
