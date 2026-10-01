"""Floor map: WiFi/BLE scan capture, AP anchor registration, Pi position estimate.

Access points are fixed anchors, placed manually (drag+save x/y from the UI).
Pi position is *computed* from the latest wifi scan as a signal-weighted
centroid of visible, placed APs — an approximation, not calibrated
trilateration (see plan_floor_map.md). BLE scans are informational only
(ambient devices have no fixed position) and are never used for positioning.
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
from backend.models import AccessPoint, BleScan, Pi, WifiScan
from backend.schemas import AccessPointOut, BleDeviceSeen, FloorMapEdge, FloorMapPiNode, FloorMapResponse
from backend.services import audit_log as al
from backend.services import jobs
from backend.services.ssh_executor import execute
from backend.utils.helpers import is_valid_mac

log = logging.getLogger(__name__)

WIFI_SCAN_CMD = "/usr/sbin/iw dev wlan0 scan"
BLE_SCAN_CMD = "bluetoothctl --timeout 10 scan on"

SCAN_LOOKBACK = timedelta(minutes=5)

# bluetoothctl wraps colored lines in SOH/STX control bytes around an ANSI SGR code
_BLUETOOTHCTL_WRAPPER_RE = re.compile(r"\x01\x1b\[[0-9;]*m\x02")
_BLE_NEW_RE = re.compile(r"\[NEW\] Device ([0-9A-Fa-f:]{17}) (.+)")
_BLE_RSSI_RE = re.compile(r"\[CHG\] Device ([0-9A-Fa-f:]{17}) RSSI:\s*(-?\d+)")
_BLE_NAME_RE = re.compile(r"\[CHG\] Device ([0-9A-Fa-f:]{17}) Name:\s*(.+)")

_WIFI_BSS_RE = re.compile(r"^BSS ([0-9A-Fa-f:]{17})")
_WIFI_SIGNAL_RE = re.compile(r"^\s*signal:\s*(-?\d+(?:\.\d+)?)\s*dBm")
_WIFI_SSID_RE = re.compile(r"^\s*SSID:\s*(.*)")


@dataclass
class WifiReading:
    bssid: str
    rssi: int
    ssid: str | None


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


def _run_wifi_scan_one(ip: str, position: str, settings: SSHSettings):
    return position, execute(ip, position, WIFI_SCAN_CMD, settings)


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
    mac_by_position = {pi.position: pi.mac for pi in pis}

    workers = min(ssh.parallel_limit, max(1, len(targets)))
    all_readings: list[WifiReading] = []
    errors = 0
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
            mac = mac_by_position[position]
            now = datetime.now(timezone.utc)
            for r in readings:
                db.add(WifiScan(mac=mac, bssid=r.bssid, rssi=r.rssi, timestamp=now))
            al.add_result(db, entry.id, position, details={"aps_seen": len(readings)})

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
    mac_by_position = {pi.position: pi.mac for pi in pis}

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
            mac = mac_by_position[position]
            now = datetime.now(timezone.utc)
            for r in readings:
                if not is_valid_mac(r.device_mac):
                    continue
                db.add(BleScan(mac=mac, device_mac=r.device_mac, device_name=r.device_name,
                               rssi=r.rssi, timestamp=now))
            al.add_result(db, entry.id, position, details={"devices_seen": len(readings)})

    db.commit()

    duration_ms = int((time.monotonic() - start) * 1000)
    total = len(targets)
    status = "success" if errors == 0 else ("fail" if errors == total else "partial_fail")
    al.update_action(db, entry.id, status=status, duration_ms=duration_ms)


def compute_pi_position(db: Session, mac: str) -> tuple[float, float] | None:
    """Weighted centroid of placed APs seen in the most recent wifi scan on record.

    Weight = 1 / rssi^2 on the raw dBm value (a rough stand-in for inverse-square
    distance falloff — not a calibrated path-loss model). Returns None if no
    placed AP has ever been seen. Not time-windowed — the last scan persists across
    page reloads instead of disappearing until someone re-scans (check `last_scan_at`
    on the response if staleness matters).
    """
    rows = (
        db.query(WifiScan.bssid, WifiScan.rssi)
        .filter(WifiScan.mac == mac)
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


def get_latest_wifi_edges(db: Session) -> list[FloorMapEdge]:
    """Latest wifi_scans reading per (Pi, AP) pair on record — the graph edges, weighted by
    RSSI on the frontend. Not time-windowed, same reasoning as `compute_pi_position`."""
    rows = (
        db.query(Pi.position, WifiScan.bssid, WifiScan.rssi)
        .join(WifiScan, WifiScan.mac == Pi.mac)
        .order_by(WifiScan.timestamp.desc())
        .all()
    )
    latest: dict[tuple[str, str], int] = {}
    for position, bssid, rssi in rows:
        latest.setdefault((position, bssid), rssi)
    return [FloorMapEdge(position=position, bssid=bssid, rssi=rssi) for (position, bssid), rssi in latest.items()]


def get_floor_map(db: Session) -> FloorMapResponse:
    aps = [AccessPointOut.model_validate(ap) for ap in db.query(AccessPoint).all()]

    pi_nodes: list[FloorMapPiNode] = []
    last_scan = dict(
        db.query(WifiScan.mac, func.max(WifiScan.timestamp)).group_by(WifiScan.mac).all()
    )
    for pi in db.query(Pi).all():
        pos = compute_pi_position(db, pi.mac)
        pi_nodes.append(FloorMapPiNode(
            position=pi.position,
            mac=pi.mac,
            x=pos[0] if pos else None,
            y=pos[1] if pos else None,
            last_scan_at=last_scan.get(pi.mac),
        ))

    return FloorMapResponse(access_points=aps, pis=pi_nodes, edges=get_latest_wifi_edges(db))


def get_ble_devices_for_position(db: Session, position: str) -> list[BleDeviceSeen]:
    pi = db.query(Pi).filter(Pi.position == position).first()
    if pi is None:
        return []
    cutoff = datetime.now(timezone.utc) - SCAN_LOOKBACK
    rows = (
        db.query(BleScan)
        .filter(BleScan.mac == pi.mac, BleScan.timestamp >= cutoff)
        .order_by(BleScan.timestamp.desc())
        .all()
    )
    return [
        BleDeviceSeen(device_mac=r.device_mac, device_name=r.device_name, rssi=r.rssi, timestamp=r.timestamp)
        for r in rows
    ]
