"""TUI API client (no backend, no DB)."""
from unittest.mock import patch

from frontend.api_client import ApiClient


def _client() -> ApiClient:
    return ApiClient("http://127.0.0.1:8000", "key", "bob")


def test_base_url_and_break_glass_headers():
    c = _client()
    assert c._base == "http://127.0.0.1:8000/api/v1"
    assert c._session.headers["X-PiC-Local-Key"] == "key"
    assert c._session.headers["X-PiC-Local-User"] == "bob"


def test_actions_wait_until_finished():
    c = _client()
    polls = iter([{"finished": False}, {"finished": False}, {"finished": True}])
    with patch.object(c, "_post", return_value={"action_id": 5, "status": "queued"}) as post, \
         patch.object(c, "_get", side_effect=lambda path, params=None: next(polls)) as get, \
         patch("frontend.api_client.time.sleep"):
        resp = c.trigger_health(positions=["01-001"])
    assert resp == {"action_id": 5, "status": "queued"}
    post.assert_called_once_with("/health/trigger", {"pis": ["01-001"]})
    assert get.call_count == 3
    get.assert_called_with("/actions/5")


def test_discovery_returns_scan_result_after_wait():
    c = _client()
    gets = {"/actions/9": {"finished": True}, "/discovery/scan/9": {"discovered": [{"ip": "10.10.20.7"}]}}
    with patch.object(c, "_post", return_value={"action_id": 9, "status": "queued"}), \
         patch.object(c, "_get", side_effect=lambda path, params=None: gets[path]):
        result = c.scan_discovery()
    assert result["discovered"][0]["ip"] == "10.10.20.7"
