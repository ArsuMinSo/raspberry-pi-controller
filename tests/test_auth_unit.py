"""Auth checks that need no database (run anywhere)."""
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend import auth
from backend.database import get_db
from backend.main import app

API = "/api/v1"

# Design: docs/design/web-service.md → "Roles & permissions". None = public, "any" = any logged-in user.
EXPECTED_ROLES = {
    ("POST", "/auth/login"): None,
    ("POST", "/auth/logout"): "any",
    ("GET", "/auth/me"): "any",
    ("POST", "/auth/me/password"): "any",
    ("GET", "/auth/me/sessions"): "any",
    ("DELETE", "/auth/me/sessions/{session_id}"): "any",
    ("GET", "/users"): "admin",
    ("POST", "/users"): "admin",
    ("PATCH", "/users/{user_id}"): "admin",
    ("POST", "/users/{user_id}/password"): "admin",
    ("POST", "/users/{user_id}/revoke-sessions"): "admin",
    ("GET", "/pi/list"): "viewer",
    ("GET", "/pi/{position}/status"): "viewer",
    ("POST", "/pi"): "admin",
    ("PATCH", "/pi/{position}"): "admin",
    ("POST", "/pi/bulk"): "admin",
    ("POST", "/pi/deploy-key"): "admin",
    ("DELETE", "/pi/{position}"): "admin",
    ("POST", "/health/trigger"): "operator",
    ("GET", "/health/{action_id}"): "viewer",
    ("POST", "/command/execute"): "admin",
    ("GET", "/command/{action_id}"): "viewer",
    ("POST", "/process/kill"): "operator",
    ("GET", "/process/kill/{action_id}"): "viewer",
    ("POST", "/service/restart"): "operator",
    ("GET", "/service/restart/{action_id}"): "viewer",
    ("GET", "/logs"): "viewer",
    ("GET", "/logs/events"): "viewer",
    ("POST", "/discovery/scan"): "operator",
    ("GET", "/discovery/scan/{action_id}"): "viewer",
    ("GET", "/settings"): "admin",
    ("PATCH", "/settings"): "admin",
    ("POST", "/settings/test"): "admin",
    ("GET", "/tasks"): "operator",
    ("POST", "/tasks"): "admin",
    ("PATCH", "/tasks/{task_id}"): "admin",
    ("DELETE", "/tasks/{task_id}"): "admin",
    ("GET", "/health"): None,
}


class _NoDB:
    """Stand-in session: any use fails at once — these tests must never reach a real database."""
    def __getattr__(self, name):
        raise AssertionError(f"database used (session.{name}) — route is not protected before DB access")


@pytest.fixture
def no_db_client():
    app.dependency_overrides[get_db] = lambda: _NoDB()
    try:
        yield TestClient(app)  # no lifespan → no scheduler
    finally:
        app.dependency_overrides.clear()


def _api_routes():
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                yield method, route


def _required_role(route: APIRoute) -> str | None:
    """Role enforced by the route's dependencies (None = public)."""
    def walk(dependant):
        for dep in dependant.dependencies:
            if dep.call.__qualname__ == "require_role.<locals>.dependency":
                cells = dict(zip(dep.call.__code__.co_freevars, dep.call.__closure__))
                yield cells["role"].cell_contents
            elif dep.call is auth.current_actor:
                yield "any"
            yield from walk(dep)
    found = set(walk(route.dependant))
    if not found:
        return None
    named = found - {"any"}
    assert len(named) <= 1, f"{route.path}: several roles {found}"
    return named.pop() if named else "any"


def test_role_matrix_matches_design():
    actual = {(m, r.path.removeprefix(API)): _required_role(r) for m, r in _api_routes()}
    assert actual == EXPECTED_ROLES


def test_every_route_requires_login(no_db_client):
    client = no_db_client
    for method, route in _api_routes():
        if EXPECTED_ROLES.get((method, route.path.removeprefix(API))) is None:
            continue
        path = route.path
        for param in ("{position}", "{action_id}", "{user_id}", "{task_id}", "{session_id}"):
            path = path.replace(param, "1")
        res = client.request(method, path, json={})
        assert res.status_code == 401, f"{method} {path} → {res.status_code}"


def test_bad_bearer_token_is_rejected_before_db(no_db_client):
    res = no_db_client.get(f"{API}/pi/list", headers={"Authorization": "Basic abc"})
    assert res.status_code == 401


# ─── Passwords / usernames ────────────────────────────────────────────────────

def test_password_hash_roundtrip():
    h = auth.hash_password("correct-horse-battery")
    assert h.startswith("$argon2id$")
    assert auth.verify_password(h, "correct-horse-battery")
    assert not auth.verify_password(h, "wrong")
    assert not auth.verify_password("not-a-hash", "x")


@pytest.mark.parametrize("pw, confirm, ok", [
    ("correct-horse-battery", "correct-horse-battery", True),
    ("correct-horse-battery", "correct-horse-batterx", False),  # mismatch
    ("short", "short", False),
])
def test_check_new_password(pw, confirm, ok):
    if ok:
        auth.check_new_password(pw, confirm)
    else:
        with pytest.raises(ValueError):
            auth.check_new_password(pw, confirm)


@pytest.mark.parametrize("name, ok", [
    ("alice", True), ("jan.novak", True), ("op_1", True),
    ("A", False), ("Alice", False), ("has space", False), ("local-tui", False), ("x" * 33, False),
])
def test_check_username(name, ok):
    if ok:
        auth.check_username(name)
    else:
        with pytest.raises(ValueError):
            auth.check_username(name)


# ─── TUI break-glass key ──────────────────────────────────────────────────────

def _request(host: str, headers: dict | None = None) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (host, 50000),
    })


@pytest.mark.parametrize("host, headers, expected", [
    ("127.0.0.1", {}, True),
    ("::1", {}, True),
    ("127.0.0.1", {"X-Forwarded-For": "10.10.20.50"}, False),  # came through nginx
    ("10.10.20.50", {}, False),
])
def test_is_direct_local(host, headers, expected):
    assert auth.is_direct_local(_request(host, headers)) is expected


@pytest.fixture
def tui_key(tmp_path, monkeypatch):
    path = tmp_path / ".tui-key"
    monkeypatch.setattr(auth, "TUI_KEY_FILE", str(path))
    auth.write_tui_key(str(path))
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    return path.read_text().strip()


def test_tui_key_grants_admin_locally(tui_key):
    actor = auth._tui_actor(_request("127.0.0.1", {auth.TUI_KEY_HEADER: tui_key, auth.TUI_USER_HEADER: "bob"}))
    assert actor is not None
    assert actor.role == "admin" and actor.username == "local-tui (bob)" and actor.user_id is None


@pytest.mark.parametrize("host, headers", [
    ("127.0.0.1", {auth.TUI_KEY_HEADER: "wrong"}),
    ("10.10.20.50", "KEY"),                               # right key, from the network
    ("127.0.0.1", "KEY+XFF"),                             # right key, through nginx
])
def test_tui_key_rejected(tui_key, host, headers):
    if headers == "KEY":
        headers = {auth.TUI_KEY_HEADER: tui_key}
    elif headers == "KEY+XFF":
        headers = {auth.TUI_KEY_HEADER: tui_key, "X-Forwarded-For": "10.10.20.50"}
    assert auth._tui_actor(_request(host, headers)) is None


def test_tui_user_header_is_sanitised(tui_key):
    actor = auth._tui_actor(_request("127.0.0.1", {auth.TUI_KEY_HEADER: tui_key,
                                                   auth.TUI_USER_HEADER: "bob; DROP TABLE users"}))
    assert actor.username == "local-tui (bobDROPTABLEusers)"
