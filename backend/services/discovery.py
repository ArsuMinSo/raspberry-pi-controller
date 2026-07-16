import ipaddress
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import paramiko
from sqlalchemy import cast, Text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from backend.config import NetworkSettings, SSHSettings
from backend.utils.helpers import extract_pi_version, is_valid_mac, load_private_key
from backend.models import Pi
from backend.schemas import DiscoveredPi, DiscoveryScanResult
from backend.services import audit_log as al


def ping_host(ip: str) -> bool:
    result = subprocess.run(
        ["ping", "-c1", "-W1", ip],
        capture_output=True,
    )
    return result.returncode == 0


def _deploy_pub_key(client: paramiko.SSHClient, private_key_path: str) -> None:
    pub_path = private_key_path + ".pub"
    try:
        with open(pub_path) as f:
            pub_key = f.read().strip()
    except OSError:
        return
    cmd = (
        f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"grep -qF '{pub_key}' ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo '{pub_key}' >> ~/.ssh/authorized_keys && "
        f"chmod 600 ~/.ssh/authorized_keys"
    )
    client.exec_command(cmd, timeout=10)


def probe_pi(
    ip: str,
    ssh: SSHSettings,
    probe_timeout_s: int = 3,
    probe_username: str | None = None,
    auth: str = "key",
    password: str | None = None,
    deploy_key: bool = False,
) -> tuple[str | None, str | None, int | None, str | None]:
    """Returns (hostname, pi_version, serial, mac) via SSH. All None on failure."""
    import socket
    username = probe_username or ssh.username
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs: dict = dict(
        timeout=probe_timeout_s,
        banner_timeout=probe_timeout_s,
        auth_timeout=probe_timeout_s,
    )
    try:
        if auth == "password" and password:
            client.connect(
                ip, username=username, password=password,
                look_for_keys=False, allow_agent=False,
                **connect_kwargs,
            )
            if deploy_key:
                _deploy_pub_key(client, ssh.private_key_path)
        else:
            key = load_private_key(ssh.private_key_path)
            client.connect(ip, username=username, pkey=key, **connect_kwargs)

        def run(cmd):
            _, out, _ = client.exec_command(cmd, timeout=5)
            return out.read().decode(errors="replace").strip()

        hostname = run("hostname") or None
        cpuinfo = run("cat /proc/cpuinfo")
        mac_raw = run("ip link show | awk '/link\\/ether/{print $2; exit}'").lower()

        model_line = next(
            (l for l in cpuinfo.splitlines() if l.lower().startswith("model")), ""
        )
        serial_line = next(
            (l for l in cpuinfo.splitlines() if l.lower().startswith("serial")), ""
        )
        pi_version = extract_pi_version(model_line)
        serial = serial_line.split(":")[-1].strip() if serial_line else None
        mac = mac_raw if is_valid_mac(mac_raw) else None
        return hostname, pi_version, serial, mac
    except (paramiko.SSHException, OSError, socket.timeout):
        return None, None, None, None
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
    probe_username: str | None = None,
    probe_auth: str = "key",
    probe_password: str | None = None,
    probe_deploy_key: bool = False,
) -> tuple[str, str | None, int | None, str | None, str | None] | None:
    """Ping + optional SSH probe for one host. Returns None if host unreachable."""
    if not ping_host(ip):
        return None
    if do_probe:
        hostname, pi_version, serial, mac = probe_pi(
            ip, ssh_settings, probe_timeout,
            probe_username=probe_username,
            auth=probe_auth,
            password=probe_password,
            deploy_key=probe_deploy_key,
        )
    else:
        hostname, pi_version, serial, mac = None, None, None, None
    return (ip, hostname, pi_version, serial, mac)


def scan_subnet(
    subnet: str,
    db: Session,
    ssh_settings: SSHSettings,
    net_settings: NetworkSettings | None = None,
    probe_password: str | None = None,
) -> DiscoveryScanResult:
    entry = al.create_action(db, [], "discovery", status="running")
    start = time.monotonic()

    do_probe = net_settings.probe_ssh if net_settings else True
    probe_timeout = net_settings.probe_timeout_s if net_settings else 3
    probe_username = net_settings.probe_username if net_settings else None
    probe_auth = net_settings.probe_auth if net_settings else "key"
    probe_deploy_key = net_settings.probe_deploy_key if net_settings else False

    hosts = [str(h) for h in _parse_hosts(subnet)]
    workers = min(64, max(1, len(hosts)))

    # Parallel ping + probe
    alive: list[tuple[str, str | None, int | None, str | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                _scan_host, ip, ssh_settings, do_probe, probe_timeout,
                probe_username, probe_auth, probe_password, probe_deploy_key,
            ): ip
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

    for ip, hostname, pi_version, serial, mac in alive:
        discovered.append(DiscoveredPi(ip=ip, mac=mac, hostname=hostname, pi_version=pi_version))
        discovered_ips.add(ip)

        existing = None
        if mac and is_valid_mac(mac):
            existing = db.query(Pi).filter(Pi.mac == mac).first()
        if existing is None:
            existing = db.query(Pi).filter(Pi.current_ip == ip).first()
        if existing:
            existing.current_ip = ip  # update IP if it changed
            existing.status = "reachable"
            existing.last_seen = func.now()
            if hostname:
                existing.hostname = hostname
            if pi_version:
                existing.pi_version = pi_version
            if serial:
                existing.serial = serial
            if mac:
                existing.mac = mac
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
