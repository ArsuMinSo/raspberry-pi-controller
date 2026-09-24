"""Background jobs + progress endpoint (needs the PostgreSQL test DB)."""
from unittest.mock import patch

from backend.models import ActionLog
from backend.services import audit_log as al
from backend.services.ssh_executor import SSHResult
from tests.conftest import API, fake_execute_many


def _ssh(position: str, exit_code: int = 0, **kw) -> SSHResult:
    return SSHResult(position=position, exit_code=exit_code, stdout=kw.get("stdout", "ok"),
                     stderr=kw.get("stderr", ""), error=kw.get("error"), duration_ms=7, retry_count=0)


def test_post_returns_queued_immediately(client, sample_pi):
    with patch("backend.services.actions.jobs.submit") as submit:  # job not run
        res = client.post(f"{API}/command/execute", json={"pis": ["01-001"], "command": "uptime"})
    assert res.status_code == 200
    assert res.json()["status"] == "queued"
    submit.assert_called_once()
    progress = client.get(f"{API}/actions/{res.json()['action_id']}").json()
    assert progress["status"] == "queued" and progress["finished"] is False
    assert (progress["done"], progress["total"]) == (0, 1)


def test_progress_has_per_pi_results(client, sample_pi):
    with patch("backend.services.actions.execute_many", fake_execute_many([_ssh("01-001", stdout="up 3 days")])):
        res = client.post(f"{API}/command/execute", json={"pis": ["01-001"], "command": "uptime"})
    progress = client.get(f"{API}/actions/{res.json()['action_id']}").json()
    assert progress["status"] == "success" and progress["finished"] is True
    assert progress["user"] == "test-admin"
    assert progress["command"] == "uptime"
    [row] = progress["results"]
    assert row["position"] == "01-001" and row["exit_code"] == 0 and row["stdout"] == "up 3 days"


def test_failed_exit_code_is_fail(client, sample_pi):
    with patch("backend.services.actions.execute_many", fake_execute_many([_ssh("01-001", exit_code=1)])):
        res = client.post(f"{API}/service/restart", json={"pis": ["01-001"], "service": "kiosk.service"})
    assert client.get(f"{API}/actions/{res.json()['action_id']}").json()["status"] == "fail"


def test_job_crash_marks_action_fail(client, sample_pi):
    with patch("backend.services.actions.execute_many", side_effect=RuntimeError("boom")):
        res = client.post(f"{API}/process/kill", json={"pis": ["01-001"], "process_name": "chromium"})
    progress = client.get(f"{API}/actions/{res.json()['action_id']}").json()
    assert progress["status"] == "fail" and progress["finished"] is True
    assert progress["error"] == "RuntimeError: boom"


def test_pi_without_ip_gets_a_result_row(client, db):
    from backend.models import Pi
    pi = Pi(mac="12:34:56:78:9a:bc", position="7777", status="unreachable", tags=[])
    db.add(pi)
    db.commit()
    with patch("backend.services.actions.execute_many", fake_execute_many([])):
        res = client.post(f"{API}/command/execute", json={"pis": ["7777"], "command": "id"})
    progress = client.get(f"{API}/actions/{res.json()['action_id']}").json()
    assert progress["done"] == 1
    assert progress["results"][0]["error"] == "no IP recorded"
    db.delete(pi)
    db.commit()


def test_discovery_runs_as_job(client):
    with patch("backend.services.discovery._scan_host", return_value=None):
        res = client.post(f"{API}/discovery/scan", json={})
    assert res.status_code == 200
    action_id = res.json()["action_id"]
    assert client.get(f"{API}/actions/{action_id}").json()["status"] == "success"
    result = client.get(f"{API}/discovery/scan/{action_id}").json()
    assert result["discovered"] == [] and result["updated"] == 0


def test_unknown_action_404(client):
    assert client.get(f"{API}/actions/999999").status_code == 404


def test_mark_interrupted(db):
    entry = al.create_action(db, ["01-001"], "execute", command="sleep 100", status="running")
    assert al.mark_interrupted(db) >= 1
    db.expire_all()
    assert db.get(ActionLog, entry.id).status == "interrupted"
