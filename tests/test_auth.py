"""Login, sessions, roles, users and the audit trail (needs the PostgreSQL test DB)."""
from datetime import timedelta
from unittest.mock import patch

from backend.auth import LOCKOUT_FAILURES, utcnow
from backend.models import ActionLog, AuditEvent, User, UserSession
from backend.services.ssh_executor import SSHResult
from tests.conftest import API, TEST_PASSWORD, fake_execute_many, unique_name

NEW_PASSWORD = "another-long-password"


def _login(client, username, password=TEST_PASSWORD):
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


def _bearer(res) -> dict:
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _events(db, event, target=None):
    q = db.query(AuditEvent).filter(AuditEvent.event == event)
    if target is not None:
        q = q.filter(AuditEvent.target == target)
    return q.all()


# ─── Login / sessions ─────────────────────────────────────────────────────────

def test_login_and_me(anon_client, make_user, db):
    name = unique_name("alice")
    make_user(name, "viewer")
    res = _login(anon_client, name)
    body = res.json()
    assert res.status_code == 200
    assert body["user"]["role"] == "viewer"
    me = anon_client.get(f"{API}/auth/me", headers=_bearer(res))
    assert me.status_code == 200
    assert me.json()["username"] == name
    assert _events(db, "login", name)


def test_login_username_is_case_insensitive(anon_client, make_user):
    name = unique_name("bob")
    make_user(name, "viewer")
    assert _login(anon_client, name.upper()).status_code == 200


def test_wrong_password_is_logged(anon_client, make_user, db):
    name = unique_name("carol")
    make_user(name, "viewer")
    res = _login(anon_client, name, "wrong-password")
    assert res.status_code == 401
    [event] = _events(db, "login_failed", name)
    assert event.details == {"reason": "bad_credentials"}


def test_unknown_user_same_error(anon_client):
    res = _login(anon_client, unique_name("nobody"))
    assert res.status_code == 401
    assert res.json()["detail"] == "Wrong username or password"


def test_lockout_after_repeated_failures(anon_client, make_user, db):
    name = unique_name("dave")
    make_user(name, "viewer")
    for _ in range(LOCKOUT_FAILURES):
        assert _login(anon_client, name, "wrong-password").status_code == 401
    # Locked: even the right password is refused
    assert _login(anon_client, name).status_code == 429
    assert _events(db, "login_blocked", name)


def test_disabled_user_cannot_login(anon_client, make_user, db):
    name = unique_name("erin")
    make_user(name, "viewer", is_active=False)
    assert _login(anon_client, name).status_code == 401
    [event] = _events(db, "login_failed", name)
    assert event.details == {"reason": "disabled"}


def test_no_token_401(anon_client):
    assert anon_client.get(f"{API}/pi/list").status_code == 401


def test_expired_session_401(anon_client, make_user, db):
    name = unique_name("frank")
    make_user(name, "viewer")
    headers = _bearer(_login(anon_client, name))
    session = db.query(UserSession).join(User, User.id == UserSession.user_id).filter(User.username == name).one()
    assert session.expires_at - session.created_at == timedelta(hours=12)
    session.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert anon_client.get(f"{API}/auth/me", headers=headers).status_code == 401


def test_logout_ends_session(anon_client, make_user, db):
    name = unique_name("gina")
    make_user(name, "viewer")
    headers = _bearer(_login(anon_client, name))
    assert anon_client.post(f"{API}/auth/logout", headers=headers).status_code == 204
    assert anon_client.get(f"{API}/auth/me", headers=headers).status_code == 401
    assert _events(db, "logout", name)


def test_list_and_revoke_own_sessions(anon_client, make_user):
    name = unique_name("hank")
    make_user(name, "viewer")
    first = _bearer(_login(anon_client, name))
    second = _bearer(_login(anon_client, name))
    sessions = anon_client.get(f"{API}/auth/me/sessions", headers=first).json()
    assert len(sessions) == 2
    other = next(s for s in sessions if not s["current"])
    assert anon_client.delete(f"{API}/auth/me/sessions/{other['id']}", headers=first).status_code == 204
    assert anon_client.get(f"{API}/auth/me", headers=second).status_code == 401
    assert anon_client.get(f"{API}/auth/me", headers=first).status_code == 200


# ─── Own password ─────────────────────────────────────────────────────────────

def test_change_own_password(anon_client, make_user, db):
    name = unique_name("ivy")
    make_user(name, "viewer")
    current = _bearer(_login(anon_client, name))
    other_device = _bearer(_login(anon_client, name))
    url = f"{API}/auth/me/password"

    mismatch = {"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD, "new_password_confirm": "x" * 20}
    assert anon_client.post(url, json=mismatch, headers=current).status_code == 422
    wrong = {"current_password": "nope", "new_password": NEW_PASSWORD, "new_password_confirm": NEW_PASSWORD}
    assert anon_client.post(url, json=wrong, headers=current).status_code == 403
    ok = {"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD, "new_password_confirm": NEW_PASSWORD}
    assert anon_client.post(url, json=ok, headers=current).status_code == 204

    assert anon_client.get(f"{API}/auth/me", headers=current).status_code == 200       # this device stays in
    assert anon_client.get(f"{API}/auth/me", headers=other_device).status_code == 401  # others logged out
    assert _login(anon_client, name).status_code == 401
    assert _login(anon_client, name, NEW_PASSWORD).status_code == 200
    assert _events(db, "password_changed", name)


# ─── Roles ────────────────────────────────────────────────────────────────────

def test_viewer_can_read_but_not_act(anon_client, login_as, db):
    headers = login_as("viewer")
    assert anon_client.get(f"{API}/pi/list", headers=headers).status_code == 200
    assert anon_client.get(f"{API}/logs", headers=headers).status_code == 403  # activity log: operator+
    assert anon_client.get(f"{API}/logs/events", headers=headers).status_code == 403
    res = anon_client.post(f"{API}/health/trigger", json={"all": True}, headers=headers)
    assert res.status_code == 403
    assert _events(db, "permission_denied", f"POST {API}/health/trigger")


def test_operator_can_check_health_but_not_execute(anon_client, login_as):
    headers = login_as("operator")
    # Passes auth; 422 because the Pi doesn't exist
    assert anon_client.post(f"{API}/health/trigger", json={"pis": ["99-999"]}, headers=headers).status_code == 422
    res = anon_client.post(f"{API}/command/execute", json={"pis": ["99-999"], "command": "id"}, headers=headers)
    assert res.status_code == 403


def test_admin_can_execute(anon_client, login_as):
    headers = login_as("admin")
    res = anon_client.post(f"{API}/command/execute", json={"pis": ["99-999"], "command": "id"}, headers=headers)
    assert res.status_code == 422


def test_actions_log_records_user(anon_client, make_user, db, sample_pi):
    name = unique_name("admin")
    user = make_user(name, "admin")
    headers = _bearer(_login(anon_client, name))
    ssh_result = SSHResult(position="01-001", exit_code=0, stdout="ok", stderr="", error=None,
                           duration_ms=5, retry_count=0)
    with patch("backend.services.actions.execute_many", fake_execute_many([ssh_result])):
        res = anon_client.post(f"{API}/command/execute", json={"pis": ["01-001"], "command": "uptime"},
                               headers=headers)
    assert res.status_code == 200
    entry = db.get(ActionLog, res.json()["action_id"])
    assert entry.user == name
    assert entry.user_id == user.id


def test_pi_edits_are_audited(anon_client, login_as, db):
    headers = login_as("admin")
    body = {"position": "4242", "mac": "de:ad:be:ef:42:42"}
    assert anon_client.post(f"{API}/pi", json=body, headers=headers).status_code == 201
    assert anon_client.patch(f"{API}/pi/4242", json={"hostname": "k42"}, headers=headers).status_code == 200
    assert anon_client.delete(f"{API}/pi/4242", headers=headers).status_code == 204
    assert _events(db, "pi_created", "4242")
    [updated] = _events(db, "pi_updated", "4242")
    assert updated.details == {"hostname": "k42"}
    assert _events(db, "pi_deleted", "4242")


# ─── User management ──────────────────────────────────────────────────────────

def test_admin_creates_user(anon_client, login_as, db):
    headers = login_as("admin")
    name = unique_name("newbie")
    url = f"{API}/users"
    base = {"username": name, "role": "operator"}

    assert anon_client.post(url, json={**base, "password": NEW_PASSWORD, "password_confirm": "different-long-pw"},
                            headers=headers).status_code == 422
    assert anon_client.post(url, json={**base, "password": "short", "password_confirm": "short"},
                            headers=headers).status_code == 422
    res = anon_client.post(url, json={**base, "password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD},
                           headers=headers)
    assert res.status_code == 201
    assert res.json()["must_change_password"] is True
    assert anon_client.post(url, json={**base, "password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD},
                            headers=headers).status_code == 409
    assert _login(anon_client, name, NEW_PASSWORD).status_code == 200
    assert _events(db, "user_created", name)


def test_non_admin_cannot_manage_users(anon_client, login_as):
    assert anon_client.get(f"{API}/users", headers=login_as("operator")).status_code == 403


def test_disabling_user_ends_their_sessions(anon_client, login_as, make_user, db):
    admin = login_as("admin")
    name = unique_name("jack")
    user = make_user(name, "viewer")
    victim = _bearer(_login(anon_client, name))
    res = anon_client.patch(f"{API}/users/{user.id}", json={"is_active": False}, headers=admin)
    assert res.status_code == 200
    assert anon_client.get(f"{API}/auth/me", headers=victim).status_code == 401
    assert _events(db, "user_disabled", name)


def test_admin_password_reset_ends_sessions(anon_client, login_as, make_user):
    admin = login_as("admin")
    name = unique_name("kate")
    user = make_user(name, "viewer")
    old = _bearer(_login(anon_client, name))
    body = {"password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD}
    assert anon_client.post(f"{API}/users/{user.id}/password", json=body, headers=admin).status_code == 204
    assert anon_client.get(f"{API}/auth/me", headers=old).status_code == 401
    assert _login(anon_client, name, NEW_PASSWORD).status_code == 200


def test_last_admin_cannot_be_demoted(anon_client, login_as, make_user):
    admin = login_as("admin")
    target = make_user(unique_name("boss"), "admin")
    with patch("backend.routes.users._active_admin_count", return_value=1):
        res = anon_client.patch(f"{API}/users/{target.id}", json={"role": "viewer"}, headers=admin)
    assert res.status_code == 409
