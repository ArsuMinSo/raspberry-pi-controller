import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DB_PASSWORD", "test")

from backend.database import Base, get_db
from backend.main import app
from backend.models import ActionLog, Pi
from backend.services.ssh_executor import SSHResult

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://pi_controller:test@localhost/pi_controller_test",
)


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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
