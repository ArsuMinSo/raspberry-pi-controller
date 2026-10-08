import ipaddress
import json
import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import paramiko
from sqlalchemy import cast, Text
from sqlalchemy.orm import Session

from backend.config import NetworkSettings, SSHSettings
from backend.utils.helpers import extract_pi_version, is_valid_mac, load_private_key
from backend.models import Pi
from backend.schemas import DiscoveredPi, DiscoveryScanResult
from backend.services import audit_log as al
from backend.services import jobs

log = logging.getLogger(__name__)


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
) -> tuple[str | None, int | None, str | None, str | None] | None:
    """Returns (hostname, pi_version, serial, mac) via SSH, or None if the login failed."""
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
        return None
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


HOST_DOWN = "down"
HOST_PING = "ping"
HOST_SSH_MAIN = "ssh_main"
HOST_SSH_BACKUP = "ssh_backup"


def _scan_host(
    ip: str,
    ssh_settings: SSHSettings,
    do_probe: bool,
    probe_timeout: int,
    probe_username: str | None = None,
    probe_backup_username: str = "",
    probe_auth: str = "key",
    probe_password: str | None = None,
    probe_deploy_key: bool = False,
) -> tuple[str, str, str | None, int | None, str | None, str | None]:
    """Ping, then SSH-probe as the main user and (on failure) the backup user.

    Returns (ip, state, hostname, pi_version, serial, mac); state is one of HOST_*.
    """
    if not ping_host(ip):
        return ip, HOST_DOWN, None, None, None, None
    if not do_probe:
        return ip, HOST_PING, None, None, None, None
    attempts = ((HOST_SSH_MAIN, probe_username), (HOST_SSH_BACKUP, probe_backup_username))
    for state, username in attempts:
        if not username:
            continue
        info = probe_pi(
            ip, ssh_settings, probe_timeout,
            probe_username=username,
            auth=probe_auth,
            password=probe_password,
            deploy_key=probe_deploy_key,
        )
        if info is not None:
            return (ip, state, *info)
    return ip, HOST_PING, None, None, None, None


def scan_subnet(
    subnet: str,
    db: Session,
    ssh_settings: SSHSettings,
    net_settings: NetworkSettings | None = None,
    probe_password: str | None = None,
    entry=None,
) -> DiscoveryScanResult:
    """Ping (+ probe) every host in `subnet`, update known Pis. `entry` is the action row (a job's)."""
    if entry is None:
        entry = al.create_action(db, [], "discovery", status="running")
    start = time.monotonic()
    log.info("Discovery scan of %s started (action %s)", subnet, entry.id)

    do_probe = net_settings.probe_ssh if net_settings else True
    probe_timeout = net_settings.probe_timeout_s if net_settings else 3
    probe_username = net_settings.probe_username if net_settings else None
    probe_backup_username = net_settings.probe_backup_username if net_settings else ""
    probe_auth = net_settings.probe_auth if net_settings else "key"
    probe_deploy_key = net_settings.probe_deploy_key if net_settings else False

    hosts = [str(h) for h in _parse_hosts(subnet)]
    workers = min(64, max(1, len(hosts)))
    known_ips = {
        str(ip) for (ip,) in db.query(Pi.current_ip).filter(Pi.last_seen.isnot(None), Pi.current_ip.isnot(None))
    }

    # Parallel ping + probe; each host's state is recorded as soon as it finishes (live grid)
    alive: list[tuple[str, str | None, int | None, str | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                _scan_host, ip, ssh_settings, do_probe, probe_timeout,
                probe_username, probe_backup_username, probe_auth, probe_password, probe_deploy_key,
            ): ip
            for ip in hosts
        }
        for future in as_completed(futures):
            ip, state, hostname, pi_version, serial, mac = future.result()
            if state == HOST_DOWN and ip in known_ips:
                al.add_result(db, entry.id, ip, details={"state": "down_known"})
            elif state != HOST_DOWN:
                alive.append((ip, hostname, pi_version, serial, mac))
                al.add_result(db, entry.id, ip, details={"state": state})

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
            existing.last_seen = datetime.now(timezone.utc)
            if hostname:
                existing.hostname = hostname
            if pi_version:
                existing.pi_version = pi_version
            if serial:
                existing.serial = serial
            if mac and mac != existing.mac:
                if db.query(Pi).filter(Pi.mac == mac, Pi.rid != existing.rid).first():
                    log.warning("%s reports MAC %s, already registered to another Pi — keeping %s",
                                existing.position, mac, existing.mac)
                else:
                    existing.mac = mac
            updated += 1
        else:
            added += 1

    db.commit()

    # Mark reachable Pis whose IP didn't respond as unreachable — but only if the scan actually
    # found *something*. Zero hosts answering across an entire subnet sweep is far more likely a
    # broken scan (ping unavailable/unprivileged for the service user, wrong subnet configured,
    # firewall) than every single Pi genuinely going down at once; trusting it would wipe the
    # whole fleet's status to unreachable on every such failure.
    if discovered_ips:
        db.query(Pi).filter(Pi.status == "reachable", cast(Pi.current_ip, Text).notin_(discovered_ips)).update(
            {"status": "unreachable", "cpu_1m": None, "cpu_5m": None, "cpu_15m": None, "mem_percent": None, "temp_c": None},
            synchronize_session=False,
        )
        db.commit()
    else:
        log.warning("Discovery scan of %s found zero responsive hosts — leaving existing Pi "
                     "statuses untouched (likely a scan failure, not a real outage)", subnet)

    duration_ms = int((time.monotonic() - start) * 1000)
    log.info("Discovery scan of %s finished (action %s): %d alive, %d added, %d updated",
             subnet, entry.id, len(alive), added, updated)
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


def start_discovery(db: Session, subnet: str, ssh_settings: SSHSettings, net_settings: NetworkSettings,
                    probe_password: str | None = None, actor=None, wait: bool = False) -> int:
    """Create the queued action and scan — in the background, or right here if `wait` (scheduler)."""
    entry = al.create_action(db, [], "discovery", status="queued", actor=actor)

    def work(job_db: Session, job_entry) -> None:
        scan_subnet(subnet, job_db, ssh_settings, net_settings, probe_password=probe_password, entry=job_entry)

    if wait:
        jobs.run_action(entry.id, work)
    else:
        jobs.submit(jobs.run_action, entry.id, work)
    return entry.id
