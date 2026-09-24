import os
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault(  # tests never depend on (or write) a local config.yaml
    "PI_CONTROLLER_CONFIG",
    str(pathlib.Path(__file__).parent.parent / "config.example.yaml"),
)
os.environ["PI_CONTROLLER_DISABLE_SCHEDULER"] = "1"  # don't touch the real DB on app startup

from backend.auth import Actor, create_session, current_actor, hash_password
from backend.database import Base, get_db
from backend.main import app
from backend.models import ActionLog, Pi, User
from backend.services import jobs
from backend.services.ssh_executor import SSHResult

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://pi_controller:test@localhost/pi_controller_test",
)

_MIGRATIONS = sorted(
    (pathlib.Path(__file__).parent.parent / "migrations").glob("*.sql")
)


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DB_URL)
    _drop_tables(engine)
    # Raw cursor: whole files (DO $$ blocks) in one go, no bind-param parsing of '%'
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            for path in _MIGRATIONS:
                cur.execute(path.read_text())
        raw.commit()
    finally:
        raw.close()
    yield engine
    _drop_tables(engine)


def _drop_tables(engine):
    with engine.begin() as conn:
        for table in ("action_results", "audit_events", "sessions", "scheduled_tasks", "actions_log", "users",
                      "raspberries"):
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))


@pytest.fixture
def db(test_engine, monkeypatch):
    Session = sessionmaker(bind=test_engine)
    # Background jobs: run synchronously, on the test database
    monkeypatch.setattr(jobs, "session_factory", Session)
    monkeypatch.setattr(jobs, "run_inline", True)
    session = Session()
    yield session
    session.rollback()
    session.close()


def fake_execute_many(results):
    """Stand-in for ssh_executor.execute_many that also reports each result (like the real one)."""
    def _fake(targets, command, settings, ssh_username=None, ssh_password=None, on_result=None):
        for r in results:
            if on_result:
                on_result(r)
        return results
    return _fake


API = "/api/v1"
TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture
def client(db):
    """Authenticated as an admin (auth itself is covered in test_auth.py)."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_actor] = lambda: Actor(username="test-admin", role="admin")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client(db):
    """No authentication — real auth dependencies."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def unique_name(prefix: str) -> str:
    """Usernames must be unique across the whole test session (rows persist between tests)."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def make_user(db):
    """make_user("alice", "viewer") → User with password TEST_PASSWORD."""
    def _make(username: str, role: str, **kw) -> User:
        user = User(username=username, role=role, password_hash=hash_password(TEST_PASSWORD), **kw)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    return _make


@pytest.fixture
def login_as(db, make_user):
    """login_as("operator") → Authorization headers for a fresh user with that role."""
    def _login(role: str) -> dict:
        user = make_user(unique_name(role), role)
        token, _ = create_session(db, user, "testclient", "pytest")
        return {"Authorization": f"Bearer {token}"}
    return _login


@pytest.fixture
def sample_pi(db) -> Pi:
    pi = Pi(
        mac="aa:bb:cc:dd:ee:ff",
        hostname="kiosk-01",
        position="01-001",
        pi_version=4,
        current_ip="10.10.20.5",
        status="reachable",
        tags=["kiosk"],
    )
    db.add(pi)
    db.commit()
    db.refresh(pi)
    yield pi
    db.delete(pi)
    db.commit()


@pytest.fixture
def mock_ssh(mocker):
    return mocker.patch(
        "backend.services.ssh_executor.execute",
        return_value=SSHResult(
            position="01-001",
            exit_code=0,
            stdout="ok",
            stderr="",
            error=None,
            duration_ms=50,
            retry_count=0,
        ),
    )
