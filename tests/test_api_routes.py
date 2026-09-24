import json
from unittest.mock import patch

import pytest

from backend.models import ActionLog, Pi
from backend.services.ssh_executor import SSHResult
from backend.schemas import PiHealthResult
from backend.services.health_check import HealthCheckData
from tests.conftest import API, fake_execute_many


# ─── Pi / Inventory ───────────────────────────────────────────────────────────

def test_pi_list_empty(client):
    res = client.get(f"{API}/pi/list")
    assert res.status_code == 200
    assert res.json() == []


def test_pi_list_returns_pis(client, sample_pi):
    res = client.get(f"{API}/pi/list")
    assert res.status_code == 200
    data = res.json()
    assert any(p["position"] == "01-001" for p in data)


def test_pi_list_filter_status(client, db, sample_pi):
    unreachable = Pi(mac="00:11:22:33:44:55", position="09-001", status="unreachable", tags=[])
    db.add(unreachable)
    db.commit()

    res = client.get(f"{API}/pi/list?status=reachable")
    positions = [p["position"] for p in res.json()]
    assert "01-001" in positions
    assert "09-001" not in positions

    db.delete(unreachable)
    db.commit()


def test_pi_list_filter_tags(client, db):
    pi = Pi(mac="aa:00:00:00:00:01", position="08-001", status="reachable", tags=["lobby"])
    db.add(pi)
    db.commit()

    res = client.get(f"{API}/pi/list?tags=lobby")
    positions = [p["position"] for p in res.json()]
    assert "08-001" in positions

    db.delete(pi)
    db.commit()


def test_pi_status_found(client, sample_pi):
    res = client.get(f"{API}/pi/01-001/status")
    assert res.status_code == 200
    assert res.json()["position"] == "01-001"


def test_pi_status_not_found(client):
    res = client.get(f"{API}/pi/99-999/status")
    assert res.status_code == 404


def test_pi_status_invalid_position(client):
    res = client.get(f"{API}/pi/bad/status")
    assert res.status_code == 422


# ─── Health ───────────────────────────────────────────────────────────────────

def test_health_trigger_unknown_position(client):
    res = client.post(f"{API}/health/trigger", json={"pis": ["99-999"]})
    assert res.status_code == 422


def test_health_trigger_no_reachable(client):
    res = client.post(f"{API}/health/trigger", json={"all": True})
    assert res.status_code == 404


def test_health_trigger_success(client, db, sample_pi):
    data = HealthCheckData(
        result=PiHealthResult(position="01-001", cpu_1m=12.5, cpu_5m=10.0, cpu_15m=8.0, mem_percent=40.0,
                              temp_c=50.0, pi_time="12:00:00", uptime_s=3600, error=None),
        hostname="kiosk-01", mac=None, pi_version=4, serial=None,
    )
    with patch("backend.services.health_check.check_health", return_value=data):
        res = client.post(f"{API}/health/trigger", json={"pis": ["01-001"]})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "queued"

    progress = client.get(f"{API}/actions/{body['action_id']}").json()
    assert progress["status"] == "success" and progress["finished"] is True
    assert (progress["done"], progress["total"]) == (1, 1)
    assert progress["results"][0]["details"]["cpu_1m"] == 12.5
    # Old result endpoint still works
    old = client.get(f"{API}/health/{body['action_id']}").json()
    assert old["results"][0]["temp_c"] == 50.0


def test_health_result_not_found(client):
    res = client.get(f"{API}/health/99999")
    assert res.status_code == 404


# ─── Command ──────────────────────────────────────────────────────────────────

def test_command_execute_unknown_position(client):
    res = client.post(f"{API}/command/execute", json={"pis": ["99-999"], "command": "uptime"})
    assert res.status_code == 422


def test_command_execute_success(client, db, sample_pi):
    ssh_result = SSHResult(
        position="01-001", exit_code=0, stdout="up 1 day", stderr="", error=None,
        duration_ms=50, retry_count=0,
    )
    with patch("backend.services.actions.execute_many", fake_execute_many([ssh_result])):
        res = client.post(f"{API}/command/execute", json={"pis": ["01-001"], "command": "uptime"})
    assert res.status_code == 200
    action_id = res.json()["action_id"]

    res2 = client.get(f"{API}/command/{action_id}")
    assert res2.status_code == 200
    results = res2.json()["results"]
    assert results[0]["exit_code"] == 0
    assert results[0]["stdout"] == "up 1 day"


# ─── Process ──────────────────────────────────────────────────────────────────

def test_process_kill_success(client, db, sample_pi):
    ssh_result = SSHResult(
        position="01-001", exit_code=0, stdout="", stderr="", error=None,
        duration_ms=30, retry_count=0,
    )
    with patch("backend.services.actions.execute_many", fake_execute_many([ssh_result])):
        res = client.post(f"{API}/process/kill", json={"pis": ["01-001"], "process_name": "chromium"})
    assert res.status_code == 200


def test_process_kill_not_found(client, db, sample_pi):
    ssh_result = SSHResult(
        position="01-001", exit_code=1, stdout="", stderr="process not found: chromium",
        error=None, duration_ms=30, retry_count=0,
    )
    with patch("backend.services.actions.execute_many", fake_execute_many([ssh_result])):
        res = client.post(f"{API}/process/kill", json={"pis": ["01-001"], "process_name": "chromium"})
    assert res.status_code == 200
    assert res.json()["action_id"] is not None


# ─── Service ──────────────────────────────────────────────────────────────────

def test_service_restart_success(client, db, sample_pi):
    ssh_result = SSHResult(
        position="01-001", exit_code=0, stdout="", stderr="", error=None,
        duration_ms=40, retry_count=0,
    )
    with patch("backend.services.actions.execute_many", fake_execute_many([ssh_result])):
        res = client.post(f"{API}/service/restart", json={"pis": ["01-001"], "service": "kiosk.service"})
    assert res.status_code == 200


# ─── Logs ─────────────────────────────────────────────────────────────────────

def test_logs_empty(client):
    res = client.get(f"{API}/logs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_logs_filter_by_position(client, db):
    entry = ActionLog(pis_selected=["07-001"], action="execute", status="success")
    db.add(entry)
    db.commit()

    res = client.get(f"{API}/logs?pi=07-001")
    assert res.status_code == 200
    data = res.json()
    assert any("07-001" in e["pis_selected"] for e in data)
    # No cleanup: actions_log is append-only (DB rule turns DELETE into a no-op)


# ─── System health ────────────────────────────────────────────────────────────

def test_system_health(client):
    res = client.get(f"{API}/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "uptime_s" in body
