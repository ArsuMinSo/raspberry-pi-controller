import ipaddress
import json
import re
import subprocess
import time

import paramiko
from sqlalchemy.orm import Session

from backend.config import SSHSettings
from backend.utils.helpers import load_private_key
from backend.models import Pi
from backend.schemas import DiscoveredPi, DiscoveryScanResult
from backend.services import audit_log as al

_MAC_RE = re.compile(r"([0-9a-f]{2}(?::[0-9a-f]{2}){5})", re.IGNORECASE)
_PI_VERSION_RE = re.compile(r"raspberry pi (\d+)", re.IGNORECASE)


def ping_host(ip: str) -> bool:
    result = subprocess.run(
        ["ping", "-c1", "-W1", ip],
        capture_output=True,
    )
    return result.returncode == 0


def get_mac_from_arp(ip: str) -> str | None:
    result = subprocess.run(
        ["ip", "neigh", "show", ip],
        capture_output=True,
        text=True,
    )
    m = _MAC_RE.search(result.stdout)
    if m:
        return m.group(1).lower()
    return None


def _extract_pi_version(model_line: str) -> int | None:
    m = _PI_VERSION_RE.search(model_line)
    if m:
        return int(m.group(1))
    return None


def probe_pi(ip: str, settings) -> tuple[str | None, str | None, int | None]:
    """Returns (hostname, pi_version, serial) via SSH. All None on failure."""
    import socket
    key = load_private_key(settings.private_key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            ip,
            username=settings.username,
            pkey=key,
            timeout=5,
            banner_timeout=5,
            auth_timeout=5,
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


def scan_subnet(subnet: str, db: Session, ssh_settings: SSHSettings) -> DiscoveryScanResult:
    entry = al.create_action(db, [], "discovery", status="running")
    start = time.monotonic()

    hosts = _parse_hosts(subnet)
    discovered: list[DiscoveredPi] = []
    added = 0
    updated = 0

    seen_positions: set[str] = set()

    for host in hosts:
        ip = str(host)
        if not ping_host(ip):
            continue

        mac = get_mac_from_arp(ip)
        if not mac:
            continue

        hostname, pi_version, serial = probe_pi(ip, ssh_settings)

        discovered.append(DiscoveredPi(
            ip=ip,
            mac=mac,
            hostname=hostname,
            pi_version=pi_version,
        ))

        existing = db.query(Pi).filter(Pi.mac == mac).first()
        if existing:
            existing.current_ip = ip
            existing.status = "reachable"
            from sqlalchemy.sql import func
            existing.last_seen = func.now()
            if hostname:
                existing.hostname = hostname
            if pi_version:
                existing.pi_version = pi_version
            if serial:
                existing.serial = serial
            seen_positions.add(existing.position)
            updated += 1
        else:
            added += 1

    db.commit()

    reachable_macs = {d.mac for d in discovered}
    db.query(Pi).filter(
        Pi.mac.notin_(reachable_macs),
        Pi.status == "reachable",
    ).update({"status": "unreachable"}, synchronize_session=False)
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
