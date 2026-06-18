import json
from unittest.mock import patch

import pytest

from backend.models import ActionLog, Pi
from backend.services.ssh_executor import SSHResult


# ─── Pi / Inventory ───────────────────────────────────────────────────────────

def test_pi_list_empty(client):
    res = client.get("/pi/list")
    assert res.status_code == 200
    assert res.json() == []


def test_pi_list_returns_pis(client, sample_pi):
    res = client.get("/pi/list")
    assert res.status_code == 200
    data = res.json()
    assert any(p["position"] == "01-001" for p in data)


def test_pi_list_filter_status(client, db, sample_pi):
    unreachable = Pi(mac="00:11:22:33:44:55", position="09-001", status="unreachable", tags=[])
    db.add(unreachable)
    db.commit()

    res = client.get("/pi/list?status=reachable")
    positions = [p["position"] for p in res.json()]
    assert "01-001" in positions
    assert "09-001" not in positions

    db.delete(unreachable)
    db.commit()


def test_pi_list_filter_tags(client, db):
    pi = Pi(mac="aa:00:00:00:00:01", position="08-001", status="reachable", tags=["lobby"])
    db.add(pi)
    db.commit()

    res = client.get("/pi/list?tags=lobby")
    positions = [p["position"] for p in res.json()]
    assert "08-001" in positions

    db.delete(pi)
    db.commit()


def test_pi_status_found(client, sample_pi):
    res = client.get("/pi/01-001/status")
    assert res.status_code == 200
    assert res.json()["position"] == "01-001"


def test_pi_status_not_found(client):
    res = client.get("/pi/99-999/status")
    assert res.status_code == 404


def test_pi_status_invalid_position(client):
    res = client.get("/pi/bad/status")
    assert res.status_code == 422


# ─── Health ───────────────────────────────────────────────────────────────────

def test_health_trigger_unknown_position(client):
    res = client.post("/health/trigger", json={"pis": ["99-999"]})
    assert res.status_code == 422


def test_health_trigger_no_reachable(client):
    res = client.post("/health/trigger", json={"all": True})
    assert res.status_code == 404


def test_health_trigger_success(client, db, sample_pi):
    with patch("backend.routes.health.run_health_check", return_value=1) as mock_hc:
        res = client.post("/health/trigger", json={"pis": ["01-001"]})
    assert res.status_code == 200
    assert res.json()["action_id"] == 1


def test_health_result_not_found(client):
    res = client.get("/health/99999")
    assert res.status_code == 404


# ─── Command ──────────────────────────────────────────────────────────────────

def test_command_execute_unknown_position(client):
    res = client.post("/command/execute", json={"pis": ["99-999"], "command": "uptime"})
    assert res.status_code == 422


def test_command_execute_success(client, db, sample_pi):
    ssh_result = SSHResult(
        position="01-001", exit_code=0, stdout="up 1 day", stderr="", error=None,
        duration_ms=50, retry_count=0,
    )
    with patch("backend.routes.command.execute_many", return_value=[ssh_result]):
        res = client.post("/command/execute", json={"pis": ["01-001"], "command": "uptime"})
    assert res.status_code == 200
    action_id = res.json()["action_id"]

    res2 = client.get(f"/command/{action_id}")
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
    with patch("backend.routes.process.execute_many", return_value=[ssh_result]):
        res = client.post("/process/kill", json={"pis": ["01-001"], "process_name": "chromium"})
    assert res.status_code == 200


def test_process_kill_not_found(client, db, sample_pi):
    ssh_result = SSHResult(
        position="01-001", exit_code=1, stdout="", stderr="process not found: chromium",
        error=None, duration_ms=30, retry_count=0,
    )
    with patch("backend.routes.process.execute_many", return_value=[ssh_result]):
        res = client.post("/process/kill", json={"pis": ["01-001"], "process_name": "chromium"})
    assert res.status_code == 200
    assert res.json()["action_id"] is not None


# ─── Service ──────────────────────────────────────────────────────────────────

def test_service_restart_success(client, db, sample_pi):
    ssh_result = SSHResult(
        position="01-001", exit_code=0, stdout="", stderr="", error=None,
        duration_ms=40, retry_count=0,
    )
    with patch("backend.routes.service.execute_many", return_value=[ssh_result]):
        res = client.post("/service/restart", json={"pis": ["01-001"], "service": "kiosk.service"})
    assert res.status_code == 200


# ─── Logs ─────────────────────────────────────────────────────────────────────

def test_logs_empty(client):
    res = client.get("/logs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_logs_filter_by_position(client, db):
    entry = ActionLog(pis_selected=["07-001"], action="execute", status="success")
    db.add(entry)
    db.commit()

    res = client.get("/logs?pi=07-001")
    assert res.status_code == 200
    data = res.json()
    assert any("07-001" in e["pis_selected"] for e in data)

    db.delete(entry)
    db.commit()


# ─── System health ────────────────────────────────────────────────────────────

def test_system_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "uptime_s" in body
