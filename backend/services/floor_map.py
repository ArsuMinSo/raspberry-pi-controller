"""Floor map: WiFi/BLE scan capture, AP anchor registration, Pi position estimate.

Access points are fixed anchors, placed manually (drag+save x/y from the UI).
Pi position is *computed*, primarily from the latest wifi scan as a signal-weighted
centroid of visible, placed APs — an approximation, not calibrated trilateration
(see plan_floor_map.md). Ambient BLE devices (bystanders' phones etc.) have no fixed
position and are never used for positioning. A Pi seeing *another Pi's own Bluetooth
controller* over BLE is different — that's our own fleet hardware, not a bystander,
so it's used as a fallback position signal when a Pi has no WiFi-derived position yet
(see `compute_pi_position_via_ble`), and drawn on the map as a Pi<->Pi edge.
"""
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import SSHSettings, effective_ssh_settings
from backend.models import AccessPoint, BleScan, FloorMapSettings, Pi, WifiScan
from backend.schemas import AccessPointOut, BleDeviceSeen, FloorMapEdge, FloorMapPiNode, FloorMapResponse, PiBleEdge
from backend.services import audit_log as al
from backend.services import jobs
from backend.services.ssh_executor import execute
from backend.utils.helpers import is_valid_mac

log = logging.getLogger(__name__)

# No sudo here on purpose: `scripts/provision-pi-controller-user.sh` stamps CAP_NET_ADMIN/
# CAP_NET_RAW directly onto the /usr/sbin/iw binary via `setcap` (a one-time passwordless-sudo
# step run during provisioning), so an unprivileged `iw scan` works from then on. If this
# command starts needing sudo again on a Pi, the capability was likely reset — e.g. an apt
# upgrade of iw/wireless-tools reinstalls the binary and wipes its file capabilities — re-run
# that provisioning script's setcap step (now passwordless, via the sudoers rule it installs).
WIFI_SCAN_CMD = "/usr/sbin/iw dev wlan0 scan"
WIFI_LINK_CMD = "/usr/sbin/iw dev wlan0 link"
# `scan on` alone only puts this Pi into scanning/observer mode — it does NOT make this Pi's
# own controller discoverable to other Pis scanning at the same time (discoverable/advertising
# and scanning are separate adapter states). Toggle discoverable on for the scan window so
# Pi<->Pi BLE sightings actually happen, then back off; `rc=$?; ...; exit $rc` keeps the
# overall exit code tied to the scan step, not the cleanup "discoverable off" step.
BLE_SCAN_CMD = (
    "bluetoothctl discoverable on; "
    "bluetoothctl --timeout 20 scan on; rc=$?; "
    "bluetoothctl discoverable off; "
    "exit $rc"
)

SCAN_LOOKBACK = timedelta(minutes=5)

# bluetoothctl wraps colored lines in SOH/STX control bytes around an ANSI SGR code
_BLUETOOTHCTL_WRAPPER_RE = re.compile(r"\x01\x1b\[[0-9;]*m\x02")
_BLE_NEW_RE = re.compile(r"\[NEW\] Device ([0-9A-Fa-f:]{17}) (.+)")
_BLE_RSSI_RE = re.compile(r"\[CHG\] Device ([0-9A-Fa-f:]{17}) RSSI:\s*(-?\d+)")
_BLE_NAME_RE = re.compile(r"\[CHG\] Device ([0-9A-Fa-f:]{17}) Name:\s*(.+)")
_BLE_CONTROLLER_RE = re.compile(r"Controller ([0-9A-Fa-f:]{17})")

_WIFI_BSS_RE = re.compile(r"^BSS ([0-9A-Fa-f:]{17})")
_WIFI_SIGNAL_RE = re.compile(r"^\s*signal:\s*(-?\d+(?:\.\d+)?)\s*dBm")
_WIFI_SSID_RE = re.compile(r"^\s*SSID:\s*(.*)")
_WIFI_LINK_CONNECTED_RE = re.compile(r"^Connected to ([0-9A-Fa-f:]{17})")
_WIFI_LINK_SSID_RE = re.compile(r"^\s*SSID:\s*(.*)")


@dataclass
class WifiReading:
    bssid: str
    rssi: int
    ssid: str | None


@dataclass
class WifiConnection:
    bssid: str | None = None
    ssid: str | None = None


@dataclass
class BleReading:
    device_mac: str
    device_name: str | None
    rssi: int | None


def parse_wifi_scan(raw: str) -> list[WifiReading]:
    """Parse `iw dev wlan0 scan` output into one reading per BSS block."""
    readings: list[WifiReading] = []
    bssid: str | None = None
    rssi: int | None = None
    ssid: str | None = None

    def flush():
        if bssid is not None and rssi is not None:
            readings.append(WifiReading(bssid=bssid.lower(), rssi=rssi, ssid=ssid))

    for line in raw.splitlines():
        m = _WIFI_BSS_RE.match(line)
        if m:
            flush()
            bssid, rssi, ssid = m.group(1), None, None
            continue
        m = _WIFI_SIGNAL_RE.match(line)
        if m:
            rssi = int(round(float(m.group(1))))
            continue
        m = _WIFI_SSID_RE.match(line)
        if m:
            ssid = m.group(1).strip() or None
    flush()
    return readings


def parse_wifi_connection(raw: str) -> WifiConnection:
    """Parse `iw dev wlan0 link` output to get the connected BSSID/SSID.

    Returns WifiConnection with bssid/ssid set if connected, or both None if not connected.
    """
    bssid: str | None = None
    ssid: str | None = None

    for line in raw.splitlines():
        m = _WIFI_LINK_CONNECTED_RE.match(line)
        if m:
            bssid = m.group(1).lower()
            continue
        m = _WIFI_LINK_SSID_RE.match(line)
        if m and bssid is not None:  # SSID only relevant if we found a connection
            ssid = m.group(1).strip() or None

    return WifiConnection(bssid=bssid, ssid=ssid)


def parse_ble_scan(raw: str) -> list[BleReading]:
    """Parse `bluetoothctl scan on` output. RSSI/name arrive later as async CHG
    lines, not every device gets one within the scan window — that's normal."""
    clean = _BLUETOOTHCTL_WRAPPER_RE.sub("", raw)
    devices: dict[str, BleReading] = {}

    for line in clean.splitlines():
        m = _BLE_NEW_RE.search(line)
        if m:
            mac = m.group(1).lower()
            devices.setdefault(mac, BleReading(device_mac=mac, device_name=m.group(2).strip(), rssi=None))
            continue
        m = _BLE_RSSI_RE.search(line)
        if m:
            mac = m.group(1).lower()
            r = devices.setdefault(mac, BleReading(device_mac=mac, device_name=None, rssi=None))
            r.rssi = int(m.group(2))
            continue
        m = _BLE_NAME_RE.search(line)
        if m:
            mac = m.group(1).lower()
            r = devices.setdefault(mac, BleReading(device_mac=mac, device_name=None, rssi=None))
            r.device_name = m.group(2).strip()

    return list(devices.values())


def parse_ble_controller_mac(raw: str) -> str | None:
    """The scanning Pi's own Bluetooth adapter MAC, from `Controller <mac> ...` lines in its
    own `bluetoothctl` output — used to recognize another Pi seen over BLE as a Pi<->Pi
    proximity reading rather than an ambient (bystander) device."""
    clean = _BLUETOOTHCTL_WRAPPER_RE.sub("", raw)
    m = _BLE_CONTROLLER_RE.search(clean)
    return m.group(1).lower() if m else None


def _first_lines(raw: str, n: int = 3) -> list[str]:
    """First few non-blank lines of a command's stdout, for a quick preview in the action
    log on success — full stdout is only kept on the failure path (see TODO.md re: BLE
    privacy/retention)."""
    clean = _BLUETOOTHCTL_WRAPPER_RE.sub("", raw)
    lines = [line for line in clean.splitlines() if line.strip()]
    return lines[:n]


def _upsert_access_points(db: Session, readings: list[WifiReading]) -> None:
    """Auto-register any BSSID never seen before (unplaced, x/y NULL), and merge in any
    SSID name not seen before for a BSSID already known — the same AP can broadcast
    (or have broadcast) more than one SSID string across scans."""
    seen_ssids: dict[str, set[str]] = {}
    for r in readings:
        if r.ssid:
            seen_ssids.setdefault(r.bssid, set()).add(r.ssid)
    if not seen_ssids and not readings:
        return

    seen = {r.bssid for r in readings}
    existing_aps = {ap.bssid: ap for ap in db.query(AccessPoint).filter(AccessPoint.bssid.in_(seen)).all()}
    for bssid in seen - existing_aps.keys():
        ssids = sorted(seen_ssids.get(bssid, set()))
        db.add(AccessPoint(bssid=bssid, ssid=ssids[0] if ssids else None, ssids=ssids))

    for bssid, ap in existing_aps.items():
        new_names = seen_ssids.get(bssid, set()) - set(ap.ssids or [])
        if new_names:
            ap.ssids = sorted(set(ap.ssids or []) | new_names)
            if not ap.ssid:
                ap.ssid = ap.ssids[0]

    db.commit()


def adjacent_bssid_clusters(bssids: list[str]) -> list[list[str]]:
    """Clusters of BSSIDs that share their first five octets and whose last octet differs by 1
    (chained transitively). Only clusters with more than one member are returned."""
    parent = {b: b for b in bssids}

    def find(b: str) -> str:
        while parent[b] != b:
            parent[b] = parent[parent[b]]
            b = parent[b]
        return b

    by_prefix: dict[str, dict[int, str]] = {}
    for b in bssids:
        by_prefix.setdefault(b[:15], {})[int(b[15:], 16)] = b
    for members in by_prefix.values():
        for last, b in members.items():
            if last + 1 in members:
                parent[find(b)] = find(members[last + 1])

    clusters: dict[str, list[str]] = {}
    for b in bssids:
        clusters.setdefault(find(b), []).append(b)
    return [sorted(c) for c in clusters.values() if len(c) > 1]


def _run_wifi_scan_one(ip: str, position: str, settings: SSHSettings):
    return position, execute(ip, position, WIFI_SCAN_CMD, settings)


def _run_wifi_link_one(ip: str, position: str, settings: SSHSettings):
    return position, execute(ip, position, WIFI_LINK_CMD, settings)


def _run_ble_scan_one(ip: str, position: str, settings: SSHSettings):
    return position, execute(ip, position, BLE_SCAN_CMD, settings)


def start_wifi_scan(db: Session, positions: list[str], actor=None, wait: bool = False) -> int:
    entry = al.create_action(db, positions, "wifi_scan", status="queued", actor=actor)
    work = partial(wifi_scan_job, ssh=effective_ssh_settings())
    if wait:
        jobs.run_action(entry.id, work)
    else:
        jobs.submit(jobs.run_action, entry.id, work)
    return entry.id


def start_ble_scan(db: Session, positions: list[str], actor=None, wait: bool = False) -> int:
    entry = al.create_action(db, positions, "ble_scan", status="queued", actor=actor)
    work = partial(ble_scan_job, ssh=effective_ssh_settings())
    if wait:
        jobs.run_action(entry.id, work)
    else:
        jobs.submit(jobs.run_action, entry.id, work)
    return entry.id


def wifi_scan_job(db: Session, entry, ssh: SSHSettings) -> None:
    start = time.monotonic()
    pis = db.query(Pi).filter(Pi.position.in_(entry.pis_selected)).all()
    targets = [(str(pi.current_ip), pi.position) for pi in pis if pi.current_ip is not None]
    rid_by_position = {pi.position: pi.rid for pi in pis}
    pi_by_position = {pi.position: pi for pi in pis}

    workers = min(ssh.parallel_limit, max(1, len(targets)))
    all_readings: list[WifiReading] = []
    errors = 0
    now = datetime.now(timezone.utc)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run_wifi_scan_one, ip, pos, ssh): pos for ip, pos in targets}
        for future in as_completed(futures):
            position, result = future.result()
            if result.error or result.exit_code != 0:
                errors += 1
                al.add_result(db, entry.id, position, error=result.error or f"exit {result.exit_code}",
                              stdout=result.stdout, stderr=result.stderr)
                continue
            readings = parse_wifi_scan(result.stdout)
            all_readings.extend(readings)
            rid = rid_by_position[position]
            for r in readings:
                db.add(WifiScan(pi_rid=rid, bssid=r.bssid, rssi=r.rssi, timestamp=now))
            al.add_result(db, entry.id, position,
                          details={"aps_seen": len(readings), "preview": _first_lines(result.stdout)})

    # Capture connected network info (separate command, non-critical if it fails)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run_wifi_link_one, ip, pos, ssh): pos for ip, pos in targets}
        for future in as_completed(futures):
            position, result = future.result()
            if result.error or result.exit_code != 0:
                continue
            connection = parse_wifi_connection(result.stdout)
            if connection.bssid is not None:
                pi = pi_by_position[position]
                pi.connected_bssid = connection.bssid
                pi.connected_ssid = connection.ssid
                pi.connected_at = now

    _upsert_access_points(db, all_readings)
    db.commit()

    duration_ms = int((time.monotonic() - start) * 1000)
    total = len(targets)
    status = "success" if errors == 0 else ("fail" if errors == total else "partial_fail")
    al.update_action(db, entry.id, status=status, duration_ms=duration_ms)


def ble_scan_job(db: Session, entry, ssh: SSHSettings) -> None:
    start = time.monotonic()
    pis = db.query(Pi).filter(Pi.position.in_(entry.pis_selected)).all()
    targets = [(str(pi.current_ip), pi.position) for pi in pis if pi.current_ip is not None]
    rid_by_position = {pi.position: pi.rid for pi in pis}
    pi_by_position = {pi.position: pi for pi in pis}

    workers = min(ssh.parallel_limit, max(1, len(targets)))
    errors = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run_ble_scan_one, ip, pos, ssh): pos for ip, pos in targets}
        for future in as_completed(futures):
            position, result = future.result()
            if result.error or result.exit_code != 0:
                errors += 1
                al.add_result(db, entry.id, position, error=result.error or f"exit {result.exit_code}",
                              stdout=result.stdout, stderr=result.stderr)
                continue
            readings = parse_ble_scan(result.stdout)
            rid = rid_by_position[position]
            now = datetime.now(timezone.utc)
            for r in readings:
                if not is_valid_mac(r.device_mac):
                    continue
                db.add(BleScan(pi_rid=rid, device_mac=r.device_mac, device_name=r.device_name,
                               rssi=r.rssi, timestamp=now))

            controller_mac = parse_ble_controller_mac(result.stdout)
            if controller_mac and is_valid_mac(controller_mac):
                pi_by_position[position].ble_mac = controller_mac

            al.add_result(db, entry.id, position,
                          details={"devices_seen": len(readings), "preview": _first_lines(result.stdout)})

    db.commit()

    duration_ms = int((time.monotonic() - start) * 1000)
    total = len(targets)
    status = "success" if errors == 0 else ("fail" if errors == total else "partial_fail")
    al.update_action(db, entry.id, status=status, duration_ms=duration_ms)


def compute_pi_position(db: Session, pi_rid: int) -> tuple[float, float] | None:
    """Weighted centroid of placed APs seen in the most recent wifi scan on record.

    Weight = 1 / rssi^2 on the raw dBm value (a rough stand-in for inverse-square
    distance falloff — not a calibrated path-loss model). Returns None if no
    placed AP has ever been seen. Not time-windowed — the last scan persists across
    page reloads instead of disappearing until someone re-scans (check `last_scan_at`
    on the response if staleness matters).
    """
    rows = (
        db.query(WifiScan.bssid, WifiScan.rssi)
        .filter(WifiScan.pi_rid == pi_rid)
        .order_by(WifiScan.timestamp.desc())
        .all()
    )
    if not rows:
        return None

    latest_rssi: dict[str, int] = {}
    for bssid, rssi in rows:
        latest_rssi.setdefault(bssid, rssi)

    placed = {
        ap.bssid: (ap.x, ap.y)
        for ap in db.query(AccessPoint)
        .filter(AccessPoint.bssid.in_(latest_rssi.keys()), AccessPoint.x.isnot(None), AccessPoint.y.isnot(None))
        .all()
    }
    if not placed:
        return None

    total_weight = 0.0
    wx = 0.0
    wy = 0.0
    for bssid, (x, y) in placed.items():
        rssi = latest_rssi[bssid]
        weight = 1.0 / max(rssi ** 2, 1)
        total_weight += weight
        wx += weight * x
        wy += weight * y

    return (wx / total_weight, wy / total_weight)


def compute_pi_position_via_ble(
    db: Session, pi_rid: int, ble_mac_to_position: dict[str, str], wifi_positions: dict[str, tuple[float, float]],
) -> tuple[float, float] | None:
    """Fallback for a Pi with no WiFi-derived position: weighted centroid of *other* Pis it
    sees over BLE (by their own controller MAC, not a bystander device), using only peers
    that already have a WiFi-derived position. Same 1/rssi^2 weighting as `compute_pi_position`.
    Single pass, no iterative refinement — peers must already be positioned from WiFi."""
    rows = (
        db.query(BleScan.device_mac, BleScan.rssi)
        .filter(BleScan.pi_rid == pi_rid)
        .order_by(BleScan.timestamp.desc())
        .all()
    )
    if not rows:
        return None

    latest_rssi: dict[str, int | None] = {}
    for device_mac, rssi in rows:
        latest_rssi.setdefault(device_mac, rssi)

    total_weight = 0.0
    wx = 0.0
    wy = 0.0
    for device_mac, rssi in latest_rssi.items():
        if rssi is None:
            continue
        peer_position = ble_mac_to_position.get(device_mac)
        if peer_position is None:
            continue
        peer_xy = wifi_positions.get(peer_position)
        if peer_xy is None:
            continue
        weight = 1.0 / max(rssi ** 2, 1)
        total_weight += weight
        wx += weight * peer_xy[0]
        wy += weight * peer_xy[1]

    if total_weight == 0.0:
        return None
    return (wx / total_weight, wy / total_weight)


def get_pi_ble_edges(db: Session, ble_mac_to_position: dict[str, str]) -> list[PiBleEdge]:
    """Latest BLE reading per Pi-pair where the sighted device is another Pi's own
    controller MAC — a real proximity reading between our own fleet, not a bystander."""
    rows = (
        db.query(Pi.position, BleScan.device_mac, BleScan.rssi)
        .join(BleScan, BleScan.pi_rid == Pi.rid)
        .order_by(BleScan.timestamp.desc())
        .all()
    )
    latest: dict[tuple[str, str], int] = {}
    for position, device_mac, rssi in rows:
        if rssi is None:
            continue
        peer_position = ble_mac_to_position.get(device_mac)
        if peer_position is None or peer_position == position:
            continue
        key = tuple(sorted((position, peer_position)))
        latest.setdefault(key, rssi)
    return [PiBleEdge(position_a=a, position_b=b, rssi=rssi) for (a, b), rssi in latest.items()]


def get_latest_wifi_edges(db: Session) -> list[FloorMapEdge]:
    """Latest wifi_scans reading per (Pi, AP) pair on record — the graph edges, weighted by
    RSSI on the frontend. Not time-windowed, same reasoning as `compute_pi_position`."""
    rows = (
        db.query(Pi.position, WifiScan.bssid, WifiScan.rssi)
        .join(WifiScan, WifiScan.pi_rid == Pi.rid)
        .order_by(WifiScan.timestamp.desc())
        .all()
    )
    latest: dict[tuple[str, str], int] = {}
    for position, bssid, rssi in rows:
        latest.setdefault((position, bssid), rssi)
    return [FloorMapEdge(position=position, bssid=bssid, rssi=rssi) for (position, bssid), rssi in latest.items()]


def get_floor_map(db: Session) -> FloorMapResponse:
    aps = [AccessPointOut.model_validate(ap) for ap in db.query(AccessPoint).all()]

    all_pis = db.query(Pi).all()
    last_scan = dict(
        db.query(WifiScan.pi_rid, func.max(WifiScan.timestamp)).group_by(WifiScan.pi_rid).all()
    )

    pi_nodes: list[FloorMapPiNode] = []
    wifi_positions: dict[str, tuple[float, float]] = {}
    for pi in all_pis:
        if pi.pinned_x is not None and pi.pinned_y is not None:
            pi_nodes.append(FloorMapPiNode(
                position=pi.position, mac=pi.mac, ip=str(pi.current_ip) if pi.current_ip else None,
                x=pi.pinned_x, y=pi.pinned_y, pinned=True, last_scan_at=last_scan.get(pi.rid),
                connected_bssid=pi.connected_bssid, connected_ssid=pi.connected_ssid,
                connected_at=pi.connected_at,
            ))
            continue
        pos = compute_pi_position(db, pi.rid)
        if pos:
            wifi_positions[pi.position] = pos
        pi_nodes.append(FloorMapPiNode(
            position=pi.position,
            mac=pi.mac,
            ip=str(pi.current_ip) if pi.current_ip else None,
            x=pos[0] if pos else None,
            y=pos[1] if pos else None,
            pinned=False,
            last_scan_at=last_scan.get(pi.rid),
            connected_bssid=pi.connected_bssid, connected_ssid=pi.connected_ssid,
            connected_at=pi.connected_at,
        ))

    # BLE fallback: a Pi with no WiFi position yet, but seen over BLE by a WiFi-positioned peer.
    ble_mac_to_position = {pi.ble_mac.lower(): pi.position for pi in all_pis if pi.ble_mac}
    rid_by_mac = {pi.mac: pi.rid for pi in all_pis}
    for node in pi_nodes:
        if node.x is not None:
            continue
        pos = compute_pi_position_via_ble(db, rid_by_mac[node.mac], ble_mac_to_position, wifi_positions)
        if pos:
            node.x, node.y = pos

    return FloorMapResponse(
        access_points=aps, pis=pi_nodes, edges=get_latest_wifi_edges(db),
        pi_ble_edges=get_pi_ble_edges(db, ble_mac_to_position), plan_visible=get_plan_visible(db),
    )


def get_plan_visible(db: Session) -> bool:
    row = db.get(FloorMapSettings, 1)
    return row.plan_visible if row else True


def set_plan_visible(db: Session, visible: bool) -> bool:
    """Shared, not per-browser — see `FloorMapSettings`. Upserts the singleton row since a fresh
    install has none yet (migration 014 only seeds it going forward)."""
    row = db.get(FloorMapSettings, 1)
    if row is None:
        row = FloorMapSettings(id=1, plan_visible=visible)
        db.add(row)
    else:
        row.plan_visible = visible
    db.commit()
    return visible


def get_ble_devices_for_position(db: Session, position: str) -> list[BleDeviceSeen]:
    pi = db.query(Pi).filter(Pi.position == position).first()
    if pi is None:
        return []
    cutoff = datetime.now(timezone.utc) - SCAN_LOOKBACK
    rows = (
        db.query(BleScan)
        .filter(BleScan.pi_rid == pi.rid, BleScan.timestamp >= cutoff)
        .order_by(BleScan.timestamp.desc())
        .all()
    )
    return [
        BleDeviceSeen(device_mac=r.device_mac, device_name=r.device_name, rssi=r.rssi, timestamp=r.timestamp)
        for r in rows
    ]


def clear_all_links(db: Session) -> int:
    """Wipe every stored WiFi and BLE scan reading — the map's edges (Pi<->AP and Pi<->Pi)
    disappear until the next scan repopulates them. AP placements, groups and Pi pins are
    untouched; only the scan-derived link data is cleared."""
    wifi_deleted = db.query(WifiScan).delete()
    ble_deleted = db.query(BleScan).delete()
    db.commit()
    return wifi_deleted + ble_deleted
