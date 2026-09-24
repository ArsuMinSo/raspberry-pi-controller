"""Fleet actions (reboot / diagnostics) + fleet summary (needs the PostgreSQL test DB)."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.config import PiCommands
from backend.models import Pi
from backend.services import audit_log as al
from backend.services import diagnostics
from backend.services.ssh_executor import SSHResult
from tests.conftest import API

DF_OK = """Filesystem     1024-blocks    Used Available Capacity Mounted on
/dev/root         30375756 8123456  20889012      29% /
"""


def _ssh(position: str, stdout: str = "", exit_code: int = 0, stderr: str = "") -> SSHResult:
    return SSHResult(position=position, exit_code=exit_code, stdout=stdout, stderr=stderr, error=None,
                     duration_ms=5, retry_count=0)


def _recording_execute_many(results, calls: list):
    """Like conftest.fake_execute_many, but remembers the command that was sent."""
    def _fake(targets, command, settings, ssh_username=None, ssh_password=None, on_result=None):
        calls.append(command)
        for r in results:
            if on_result:
                on_result(r)
        return results
    return _fake


def _progress(client, res):
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "queued"
    return client.get(f"{API}/actions/{res.json()['action_id']}").json()


# ─── Reboot ───────────────────────────────────────────────────────────────────

def test_reboot_uses_configured_command(client, sample_pi):
    calls: list = []
    with patch("backend.services.actions.execute_many", _recording_execute_many([_ssh("01-001")], calls)):
        progress = _progress(client, client.post(f"{API}/pi/reboot", json={"pis": ["01-001"]}))
    assert calls == [PiCommands().reboot]
    assert progress["action"] == "reboot" and progress["status"] == "success"
    assert (progress["done"], progress["total"]) == (1, 1)


def test_reboot_not_permitted_has_clear_error(client, sample_pi):
    failed = _ssh("01-001", exit_code=1, stderr="Failed to reboot system via logind: Access denied\n")
    with patch("backend.services.actions.execute_many", _recording_execute_many([failed], [])):
        progress = _progress(client, client.post(f"{API}/pi/reboot", json={"pis": ["01-001"]}))
    assert progress["status"] == "fail"
    assert progress["results"][0]["error"] == diagnostics.REBOOT_NOT_PERMITTED


def test_unknown_position_422(client):
    assert client.post(f"{API}/pi/reboot", json={"pis": ["99-999"]}).status_code == 422


# ─── Diagnostics ──────────────────────────────────────────────────────────────

def test_diagnostics_parsed_details(client, sample_pi):
    out = "throttled=0x50005\n" + diagnostics.SEPARATOR + "\n" + DF_OK
    calls: list = []
    with patch("backend.services.actions.execute_many", _recording_execute_many([_ssh("01-001", out)], calls)):
        progress = _progress(client, client.post(f"{API}/diagnostics", json={"pis": ["01-001"]}))
    assert calls == [diagnostics.build_command(PiCommands().throttled, PiCommands().disk)]
    assert progress["action"] == "diagnostics" and progress["status"] == "success"
    [row] = progress["results"]
    assert row["error"] is None
    assert row["details"]["throttled"]["under_voltage_now"] is True
    assert row["details"]["disk"]["used_percent"] == 29


def test_diagnostics_unparseable_is_per_pi_error(client, sample_pi):
    out = "bash: vcgencmd: command not found\n" + diagnostics.SEPARATOR + "\n" + DF_OK
    with patch("backend.services.actions.execute_many", _recording_execute_many([_ssh("01-001", out)], [])):
        progress = _progress(client, client.post(f"{API}/diagnostics", json={"pis": ["01-001"]}))
    assert progress["status"] == "fail"                       # the only Pi has an error
    [row] = progress["results"]
    assert row["error"].startswith("throttled:")
    assert row["details"]["disk"]["used_percent"] == 29       # partial result kept


# ─── Roles ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path, body", [
    ("/pi/reboot", {"pis": ["01-001"]}),
    ("/diagnostics", {"pis": ["01-001"]}),
])
def test_viewer_cannot_run_fleet_actions(anon_client, login_as, path, body):
    assert anon_client.post(f"{API}{path}", json=body, headers=login_as("viewer")).status_code == 403


def test_viewer_can_read_summary(anon_client, login_as):
    assert anon_client.get(f"{API}/fleet/summary", headers=login_as("viewer")).status_code == 200


# ─── Summary ──────────────────────────────────────────────────────────────────

def test_fleet_summary(client, db):
    # Rows persist across tests: unique positions (digits only, ≤ 10) and MACs per run
    n = uuid.uuid4().int % 10_000_000
    b = uuid.uuid4().bytes
    mac = lambda i: f"f1:ee:{i:02x}:{b[0]:02x}:{b[1]:02x}:{b[2]:02x}"  # noqa: E731
    now = datetime.now(timezone.utc)
    hot = Pi(mac=mac(0), position=f"8{n:07d}0", hostname="hot", status="reachable", tags=[], last_seen=now,
             temp_c=999.0, cpu_1m=998.0, mem_percent=997.0)
    stale = Pi(mac=mac(1), position=f"8{n:07d}1", hostname="stale", status="unreachable", tags=[],
               last_seen=now - timedelta(hours=48))
    never = Pi(mac=mac(2), position=f"8{n:07d}2", hostname="never", status="unreachable", tags=[],
               last_seen=None)
    db.add_all([hot, stale, never])
    db.commit()
    al.create_action(db, [hot.position], "health", status="success")
    try:
        body = client.get(f"{API}/fleet/summary", params={"stale_hours": 24}).json()
        assert body["total"] >= 3 and body["reachable"] >= 1 and body["unreachable"] >= 2
        assert body["total"] == body["reachable"] + body["unreachable"]
        assert stale.position in body["stale"] and hot.position not in body["stale"]
        assert never.position in body["never_seen"] and never.position not in body["stale"]
        assert body["hottest"][0] == {"position": hot.position, "hostname": "hot", "value": 999.0}
        assert body["busiest_cpu"][0]["position"] == hot.position
        assert body["highest_mem"][0]["position"] == hot.position
        assert len(body["hottest"]) <= 5
        assert body["last_health_check_at"] is not None
    finally:
        db.query(Pi).filter(Pi.position.in_([hot.position, stale.position, never.position])).delete(
            synchronize_session=False)
        db.commit()
