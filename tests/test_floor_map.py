"""Floor map: wifi/ble scan parsing (no DB) + scan jobs, AP placement, position calc (needs PostgreSQL test DB)."""
from unittest.mock import patch

from backend.models import AccessPoint, BleScan, Pi, WifiScan
from backend.services.floor_map import (
    WifiReading, compute_pi_position, compute_pi_position_via_ble, filter_target_ssid_top_n, get_pi_ble_edges,
    parse_ble_controller_mac, parse_ble_scan, parse_wifi_scan,
)
from backend.services.ssh_executor import SSHResult
from tests.conftest import API

IW_SCAN_OUTPUT = """BSS aa:bb:cc:dd:ee:01(on wlan0)
\tTSF: 123456 usec
\tfreq: 2437
\tbeacon interval: 100 TUs
\tsignal: -63.00 dBm
\tSSID: OMNIKA-VYROBA
BSS aa:bb:cc:dd:ee:02(on wlan0)
\tfreq: 2412
\tsignal: -80.00 dBm
\tSSID: OtherAP
"""

BLE_SCAN_OUTPUT = (
    "[\x01\x1b[0;93m\x02CHG\x01\x1b[0m\x02] Controller DC:A6:32:89:1C:5A Discovering: yes\n"
    "[\x01\x1b[0;92m\x02NEW\x01\x1b[0m\x02] Device 5A:95:14:3E:41:A7 Y3\n"
    "[\x01\x1b[0;93m\x02CHG\x01\x1b[0m\x02] Device 5A:95:14:3E:41:A7 ManufacturerData Key: 0x004c\n"
    "[\x01\x1b[0;93m\x02CHG\x01\x1b[0m\x02] Device 5A:95:14:3E:41:A7 RSSI: -61\n"
    "[\x01\x1b[0;92m\x02NEW\x01\x1b[0m\x02] Device 4F:AB:46:FD:FB:07 4F-AB-46-FD-FB-07\n"
    "[\x01\x1b[0;93m\x02CHG\x01\x1b[0m\x02] Device 4F:AB:46:FD:FB:07 Name: Galaxy Watch4 (1BGV)\n"
)


def _ssh(position: str, stdout: str = "", exit_code: int = 0) -> SSHResult:
    return SSHResult(position=position, exit_code=exit_code, stdout=stdout, stderr="", error=None,
                     duration_ms=5, retry_count=0)


# ─── Parsing ────────────────────────────────────────────────────────────────

def test_parse_wifi_scan_reads_bssid_signal_ssid():
    readings = parse_wifi_scan(IW_SCAN_OUTPUT)
    by_bssid = {r.bssid: r for r in readings}
    assert by_bssid["aa:bb:cc:dd:ee:01"].rssi == -63
    assert by_bssid["aa:bb:cc:dd:ee:01"].ssid == "OMNIKA-VYROBA"
    assert by_bssid["aa:bb:cc:dd:ee:02"].rssi == -80


def test_parse_wifi_scan_empty():
    assert parse_wifi_scan("") == []


def test_filter_target_ssid_top_n_keeps_strongest_two_of_fleet_ssid():
    readings = [
        WifiReading(bssid="aa:bb:cc:dd:ee:01", rssi=-70, ssid="OMNIKA-VYROBA"),
        WifiReading(bssid="aa:bb:cc:dd:ee:02", rssi=-40, ssid="OMNIKA-VYROBA-5G"),  # strongest
        WifiReading(bssid="aa:bb:cc:dd:ee:03", rssi=-55, ssid="OMNIKA-VYROBA"),  # 2nd strongest
        WifiReading(bssid="aa:bb:cc:dd:ee:04", rssi=-30, ssid="OtherAP"),  # strongest overall, wrong SSID
    ]
    kept = filter_target_ssid_top_n(readings)
    assert [r.bssid for r in kept] == ["aa:bb:cc:dd:ee:02", "aa:bb:cc:dd:ee:03"]


def test_filter_target_ssid_top_n_fewer_than_two_matches():
    readings = [WifiReading(bssid="aa:bb:cc:dd:ee:01", rssi=-70, ssid="OMNIKA-VYROBA")]
    assert filter_target_ssid_top_n(readings) == readings


def test_parse_ble_scan_joins_rssi_and_name_by_mac():
    readings = parse_ble_scan(BLE_SCAN_OUTPUT)
    by_mac = {r.device_mac: r for r in readings}
    assert by_mac["5a:95:14:3e:41:a7"].rssi == -61
    assert by_mac["4f:ab:46:fd:fb:07"].device_name == "Galaxy Watch4 (1BGV)"
    # Device seen but never got an async RSSI line — still logged, rssi stays None
    assert by_mac["4f:ab:46:fd:fb:07"].rssi is None


def test_parse_ble_scan_ignores_controller_line():
    readings = parse_ble_scan(BLE_SCAN_OUTPUT)
    assert all(r.device_mac != "dc:a6:32:89:1c:5a" for r in readings)


def test_parse_ble_controller_mac_reads_own_adapter():
    assert parse_ble_controller_mac(BLE_SCAN_OUTPUT) == "dc:a6:32:89:1c:5a"


def test_parse_ble_controller_mac_none_when_absent():
    assert parse_ble_controller_mac("no controller line here") is None


# ─── Scan job + AP auto-registration ───────────────────────────────────────

def test_wifi_scan_trigger_registers_ap_unplaced(client, sample_pi, db):
    with patch("backend.services.floor_map.execute", return_value=_ssh("01-001", IW_SCAN_OUTPUT)):
        res = client.post(f"{API}/floor-map/wifi-scan", json={"all": True})
    assert res.status_code == 200
    progress = client.get(f"{API}/actions/{res.json()['action_id']}").json()
    assert progress["status"] == "success"

    ap = db.get(AccessPoint, "aa:bb:cc:dd:ee:01")
    assert ap is not None and ap.x is None and ap.y is None and ap.ssid == "OMNIKA-VYROBA"
    assert ap.ssids == ["OMNIKA-VYROBA"]

    # Non-fleet SSID ("OtherAP") is dropped entirely — never scanned/stored, never auto-registered.
    assert db.get(AccessPoint, "aa:bb:cc:dd:ee:02") is None
    scans = db.query(WifiScan).filter(WifiScan.mac == sample_pi.mac).all()
    assert {s.bssid for s in scans} == {"aa:bb:cc:dd:ee:01"}

    db.query(WifiScan).filter(WifiScan.mac == sample_pi.mac).delete()
    db.query(AccessPoint).filter(AccessPoint.bssid == "aa:bb:cc:dd:ee:01").delete()
    db.commit()


def test_wifi_scan_merges_new_ssid_seen_for_known_bssid(client, sample_pi, db):
    """Same BSSID broadcasting a different SSID name on a later scan — merged in, not overwritten."""
    second_name_output = IW_SCAN_OUTPUT.replace("OMNIKA-VYROBA", "OMNIKA-VYROBA-5G")
    with patch("backend.services.floor_map.execute", return_value=_ssh("01-001", IW_SCAN_OUTPUT)):
        client.post(f"{API}/floor-map/wifi-scan", json={"all": True})
    with patch("backend.services.floor_map.execute", return_value=_ssh("01-001", second_name_output)):
        res = client.post(f"{API}/floor-map/wifi-scan", json={"all": True})
    assert client.get(f"{API}/actions/{res.json()['action_id']}").json()["status"] == "success"

    db.expire_all()
    ap = db.get(AccessPoint, "aa:bb:cc:dd:ee:01")
    assert ap.ssid == "OMNIKA-VYROBA"  # first-seen name kept as primary
    assert set(ap.ssids) == {"OMNIKA-VYROBA", "OMNIKA-VYROBA-5G"}

    db.query(WifiScan).filter(WifiScan.mac == sample_pi.mac).delete()
    db.query(AccessPoint).filter(AccessPoint.bssid.in_(["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"])).delete(
        synchronize_session=False)
    db.commit()


def test_wifi_scan_ssh_error_is_partial_fail_not_crash(client, sample_pi):
    with patch("backend.services.floor_map.execute",
              return_value=_ssh("01-001", exit_code=1)):
        res = client.post(f"{API}/floor-map/wifi-scan", json={"all": True})
    progress = client.get(f"{API}/actions/{res.json()['action_id']}").json()
    assert progress["status"] == "fail"  # only Pi targeted, and it errored


# ─── Position calc ──────────────────────────────────────────────────────────

def test_compute_pi_position_weighted_centroid(db, sample_pi):
    ap_near = AccessPoint(bssid="aa:bb:cc:dd:ee:10", x=0.0, y=0.0)
    ap_far = AccessPoint(bssid="aa:bb:cc:dd:ee:11", x=100.0, y=0.0)
    db.add_all([ap_near, ap_far])
    db.add(WifiScan(mac=sample_pi.mac, bssid="aa:bb:cc:dd:ee:10", rssi=-40))  # strong -> close to (0,0)
    db.add(WifiScan(mac=sample_pi.mac, bssid="aa:bb:cc:dd:ee:11", rssi=-80))  # weak -> far
    db.commit()

    pos = compute_pi_position(db, sample_pi.mac)
    assert pos is not None
    x, y = pos
    assert 0.0 < x < 50.0  # pulled toward the stronger (nearer) AP, not the midpoint
    assert y == 0.0

    db.query(WifiScan).filter(WifiScan.mac == sample_pi.mac).delete()
    db.query(AccessPoint).filter(AccessPoint.bssid.in_(["aa:bb:cc:dd:ee:10", "aa:bb:cc:dd:ee:11"])).delete(
        synchronize_session=False)
    db.commit()


def test_compute_pi_position_none_when_no_placed_ap_visible(db, sample_pi):
    db.add(AccessPoint(bssid="aa:bb:cc:dd:ee:12"))  # unplaced
    db.add(WifiScan(mac=sample_pi.mac, bssid="aa:bb:cc:dd:ee:12", rssi=-50))
    db.commit()

    assert compute_pi_position(db, sample_pi.mac) is None

    db.query(WifiScan).filter(WifiScan.mac == sample_pi.mac).delete()
    db.query(AccessPoint).filter(AccessPoint.bssid == "aa:bb:cc:dd:ee:12").delete()
    db.commit()


def test_compute_pi_position_none_when_no_scans(sample_pi, db):
    assert compute_pi_position(db, sample_pi.mac) is None


# ─── Pi<->Pi BLE triangulation (own fleet hardware, not a bystander device) ────

def test_compute_pi_position_via_ble_centroid_of_positioned_peers(db, sample_pi):
    peer = Pi(mac="bb:bb:bb:bb:bb:bb", hostname="kiosk-02", position="01-002", pi_version=4,
              current_ip="10.10.20.6", status="reachable", tags=[], ble_mac="11:11:11:11:11:11")
    db.add(peer)
    db.add(BleScan(mac=sample_pi.mac, device_mac="11:11:11:11:11:11", device_name=None, rssi=-50))
    db.commit()

    ble_mac_to_position = {"11:11:11:11:11:11": "01-002"}
    wifi_positions = {"01-002": (10.0, 20.0)}
    pos = compute_pi_position_via_ble(db, sample_pi.mac, ble_mac_to_position, wifi_positions)
    assert pos == (10.0, 20.0)

    db.query(BleScan).filter(BleScan.mac == sample_pi.mac).delete()
    db.delete(peer)
    db.commit()


def test_compute_pi_position_via_ble_none_without_positioned_peer(db, sample_pi):
    db.add(BleScan(mac=sample_pi.mac, device_mac="99:99:99:99:99:99", device_name=None, rssi=-50))
    db.commit()
    # 99:... isn't any known Pi's ble_mac — just an ambient bystander device, ignored.
    assert compute_pi_position_via_ble(db, sample_pi.mac, {}, {}) is None

    db.query(BleScan).filter(BleScan.mac == sample_pi.mac).delete()
    db.commit()


def test_get_pi_ble_edges_pairs_by_controller_mac(db, sample_pi):
    peer = Pi(mac="bb:bb:bb:bb:bb:bb", hostname="kiosk-02", position="01-002", pi_version=4,
              current_ip="10.10.20.6", status="reachable", tags=[], ble_mac="11:11:11:11:11:11")
    db.add(peer)
    db.add(BleScan(mac=sample_pi.mac, device_mac="11:11:11:11:11:11", device_name=None, rssi=-55))
    db.commit()

    edges = get_pi_ble_edges(db, {"11:11:11:11:11:11": "01-002"})
    assert len(edges) == 1
    assert {edges[0].position_a, edges[0].position_b} == {sample_pi.position, "01-002"}
    assert edges[0].rssi == -55

    db.query(BleScan).filter(BleScan.mac == sample_pi.mac).delete()
    db.delete(peer)
    db.commit()


# ─── AP placement + floor map read ─────────────────────────────────────────

def test_place_and_read_access_point(client, db):
    db.add(AccessPoint(bssid="aa:bb:cc:dd:ee:20", ssid="TestAP"))
    db.commit()

    res = client.patch(f"{API}/floor-map/ap/aa:bb:cc:dd:ee:20", json={"x": 12.5, "y": 34.0})
    assert res.status_code == 200
    body = res.json()
    assert body["x"] == 12.5 and body["y"] == 34.0

    m = client.get(f"{API}/floor-map").json()
    assert any(ap["bssid"] == "aa:bb:cc:dd:ee:20" and ap["x"] == 12.5 for ap in m["access_points"])

    db.query(AccessPoint).filter(AccessPoint.bssid == "aa:bb:cc:dd:ee:20").delete()
    db.commit()


def test_place_unknown_ap_404(client):
    res = client.patch(f"{API}/floor-map/ap/00:11:22:33:44:55", json={"x": 1, "y": 1})
    assert res.status_code == 404


def test_delete_access_point_removes_it_and_its_scans(client, db, sample_pi):
    db.add(AccessPoint(bssid="aa:bb:cc:dd:ee:23", ssid="TestAP"))
    db.add(WifiScan(mac=sample_pi.mac, bssid="aa:bb:cc:dd:ee:23", rssi=-50))
    db.commit()

    res = client.delete(f"{API}/floor-map/ap/aa:bb:cc:dd:ee:23")
    assert res.status_code == 204
    assert db.get(AccessPoint, "aa:bb:cc:dd:ee:23") is None
    assert db.query(WifiScan).filter(WifiScan.bssid == "aa:bb:cc:dd:ee:23").count() == 0


def test_delete_unknown_ap_404(client):
    res = client.delete(f"{API}/floor-map/ap/00:11:22:33:44:66")
    assert res.status_code == 404


def test_unpin_access_point_clears_position(client, db):
    db.add(AccessPoint(bssid="aa:bb:cc:dd:ee:21", ssid="TestAP", x=5.0, y=5.0))
    db.commit()

    res = client.patch(f"{API}/floor-map/ap/aa:bb:cc:dd:ee:21", json={"x": None, "y": None})
    assert res.status_code == 200
    body = res.json()
    assert body["x"] is None and body["y"] is None and body["pinned"] is False

    db.query(AccessPoint).filter(AccessPoint.bssid == "aa:bb:cc:dd:ee:21").delete()
    db.commit()


def test_access_point_update_rejects_mismatched_null(client, db):
    db.add(AccessPoint(bssid="aa:bb:cc:dd:ee:22", ssid="TestAP"))
    db.commit()

    res = client.patch(f"{API}/floor-map/ap/aa:bb:cc:dd:ee:22", json={"x": 1.0, "y": None})
    assert res.status_code == 422

    db.query(AccessPoint).filter(AccessPoint.bssid == "aa:bb:cc:dd:ee:22").delete()
    db.commit()


def test_pin_and_unpin_pi(client, db, sample_pi):
    res = client.patch(f"{API}/floor-map/pi/{sample_pi.position}/pin", json={"x": 7.5, "y": 8.5})
    assert res.status_code == 200
    body = res.json()
    assert body["x"] == 7.5 and body["y"] == 8.5 and body["pinned"] is True

    m = client.get(f"{API}/floor-map").json()
    assert any(p["position"] == sample_pi.position and p["pinned"] is True for p in m["pis"])

    res = client.patch(f"{API}/floor-map/pi/{sample_pi.position}/pin", json={"x": None, "y": None})
    assert res.status_code == 200
    assert res.json()["pinned"] is False


def test_floor_plan_visibility_is_shared_not_per_browser(client, db):
    """One "user" (client session) toggling it is reflected for everyone — not a per-browser
    local setting — since GET /floor-map always re-reads the one shared settings row."""
    assert client.get(f"{API}/floor-map").json()["plan_visible"] is True

    res = client.patch(f"{API}/floor-map/settings", json={"plan_visible": False})
    assert res.status_code == 200 and res.json()["plan_visible"] is False
    assert client.get(f"{API}/floor-map").json()["plan_visible"] is False

    client.patch(f"{API}/floor-map/settings", json={"plan_visible": True})


def test_pin_unknown_pi_404(client):
    res = client.patch(f"{API}/floor-map/pi/99-999/pin", json={"x": 1, "y": 1})
    assert res.status_code == 404


def test_set_and_list_access_point_group(client, db):
    db.add(AccessPoint(bssid="aa:bb:cc:dd:ee:30", ssid="Lobby-2.4"))
    db.add(AccessPoint(bssid="aa:bb:cc:dd:ee:31", ssid="Lobby-5G"))
    db.commit()

    for bssid in ("aa:bb:cc:dd:ee:30", "aa:bb:cc:dd:ee:31"):
        res = client.patch(f"{API}/floor-map/ap/{bssid}/group", json={"group_name": "Lobby router"})
        assert res.status_code == 200
        assert res.json()["group_name"] == "Lobby router"

    groups = client.get(f"{API}/floor-map/groups").json()
    assert "Lobby router" in groups

    res = client.patch(f"{API}/floor-map/ap/aa:bb:cc:dd:ee:30/group", json={"group_name": None})
    assert res.status_code == 200
    assert res.json()["group_name"] is None

    db.query(AccessPoint).filter(AccessPoint.bssid.in_(["aa:bb:cc:dd:ee:30", "aa:bb:cc:dd:ee:31"])).delete(
        synchronize_session=False)
    db.commit()


def test_floor_map_viewer_can_read_but_not_trigger_scan(anon_client, sample_pi, login_as):
    headers = login_as("viewer")
    assert anon_client.get(f"{API}/floor-map", headers=headers).status_code == 200
    assert anon_client.post(f"{API}/floor-map/wifi-scan", json={"all": True}, headers=headers).status_code == 403
