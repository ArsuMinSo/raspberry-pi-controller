"""Tests for data retention cleanup."""
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from backend.models import HealthSample, WifiScan, BleScan, Pi
from backend.services.retention import cleanup
from backend.config import apply_retention_override, effective_retention_settings, RetentionSettings
import backend.config as config_module


_test_counter = 0


@pytest.fixture(autouse=True)
def reset_retention_overrides():
    """Reset retention overrides before each test to avoid test pollution."""
    config_module._retention_overrides.clear()
    yield
    config_module._retention_overrides.clear()


@pytest.fixture
def pi_with_samples(db: Session):
    """Create a Pi with time-series samples."""
    global _test_counter
    _test_counter += 1
    pos = str(_test_counter)
    mac = f"aa:bb:cc:dd:ee:{_test_counter:02x}"
    pi = Pi(mac=mac, position=pos, status="reachable", hostname=f"test-pi-{_test_counter}")
    db.add(pi)
    db.flush()

    now = datetime.now(timezone.utc)

    # Add health samples: 3 recent, 2 old
    for i in range(3):
        ts = now - timedelta(days=i)
        db.add(HealthSample(pi_rid=pi.rid, timestamp=ts, cpu_1m=50.0, mem_percent=60.0, temp_c=45.0))

    for i in range(2):
        ts = now - timedelta(days=100 + i)
        db.add(HealthSample(pi_rid=pi.rid, timestamp=ts, cpu_1m=40.0, mem_percent=50.0, temp_c=40.0))

    # Add WiFi scans: 3 recent, 2 old
    for i in range(3):
        ts = now - timedelta(days=i)
        db.add(WifiScan(pi_rid=pi.rid, bssid="00:11:22:33:44:55", rssi=-60, timestamp=ts))

    for i in range(2):
        ts = now - timedelta(days=100 + i)
        db.add(WifiScan(pi_rid=pi.rid, bssid="00:11:22:33:44:55", rssi=-60, timestamp=ts))

    # Add BLE scans: 3 recent, 2 old
    for i in range(3):
        ts = now - timedelta(days=i)
        db.add(BleScan(pi_rid=pi.rid, device_mac="ff:ee:dd:cc:bb:aa", rssi=-70, timestamp=ts))

    for i in range(2):
        ts = now - timedelta(days=100 + i)
        db.add(BleScan(pi_rid=pi.rid, device_mac="ff:ee:dd:cc:bb:aa", rssi=-70, timestamp=ts))

    db.commit()
    return pi


def test_retention_cleanup_removes_old_records(db: Session, pi_with_samples):
    """Retention should delete records older than the configured threshold."""
    # Set retention to 90 days
    apply_retention_override(enabled=True, health_samples_days=90, wifi_scans_days=90, ble_scans_days=90)

    # Run cleanup
    deleted = cleanup(db)

    # Should delete 2 old records from each table
    assert deleted["health_samples"] == 2
    assert deleted["wifi_scans"] == 2
    assert deleted["ble_scans"] == 2

    # Verify recent records remain
    recent_health = db.query(HealthSample).filter(HealthSample.pi_rid == pi_with_samples.rid).all()
    assert len(recent_health) == 3


def test_retention_disabled(db: Session, pi_with_samples):
    """When disabled, cleanup should not delete anything."""
    apply_retention_override(enabled=False)
    deleted = cleanup(db)
    assert deleted == {}

    # All records should remain
    health_count = db.query(HealthSample).filter(HealthSample.pi_rid == pi_with_samples.rid).count()
    assert health_count == 5


def test_retention_zero_days(db: Session, pi_with_samples):
    """Setting days to 0 should disable that table's cleanup."""
    apply_retention_override(enabled=True, health_samples_days=0, wifi_scans_days=90, ble_scans_days=90)
    deleted = cleanup(db)

    # health_samples not deleted (days=0), others are
    assert "health_samples" not in deleted or deleted["health_samples"] == 0
    assert deleted.get("wifi_scans", 0) == 2
    assert deleted.get("ble_scans", 0) == 2
