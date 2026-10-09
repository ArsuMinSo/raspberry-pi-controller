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
    # Count before cleanup
    health_before = db.query(HealthSample).filter(HealthSample.pi_rid == pi_with_samples.rid).count()
    wifi_before = db.query(WifiScan).filter(WifiScan.pi_rid == pi_with_samples.rid).count()
    ble_before = db.query(BleScan).filter(BleScan.pi_rid == pi_with_samples.rid).count()

    # Set retention to 90 days
    apply_retention_override(enabled=True, health_samples_days=90, wifi_scans_days=90, ble_scans_days=90)
    cleanup(db)

    # Verify old records deleted from this Pi only
    health_after = db.query(HealthSample).filter(HealthSample.pi_rid == pi_with_samples.rid).count()
    wifi_after = db.query(WifiScan).filter(WifiScan.pi_rid == pi_with_samples.rid).count()
    ble_after = db.query(BleScan).filter(BleScan.pi_rid == pi_with_samples.rid).count()

    assert health_before == 5 and health_after == 3  # 2 deleted
    assert wifi_before == 5 and wifi_after == 3
    assert ble_before == 5 and ble_after == 3


def test_retention_disabled(db: Session, pi_with_samples):
    """When disabled, cleanup should not delete anything."""
    health_before = db.query(HealthSample).filter(HealthSample.pi_rid == pi_with_samples.rid).count()

    apply_retention_override(enabled=False)
    cleanup(db)

    health_after = db.query(HealthSample).filter(HealthSample.pi_rid == pi_with_samples.rid).count()
    assert health_before == health_after  # No deletion


def test_retention_zero_days(db: Session, pi_with_samples):
    """Setting days to 0 should disable that table's cleanup."""
    health_before = db.query(HealthSample).filter(HealthSample.pi_rid == pi_with_samples.rid).count()
    wifi_before = db.query(WifiScan).filter(WifiScan.pi_rid == pi_with_samples.rid).count()

    apply_retention_override(enabled=True, health_samples_days=0, wifi_scans_days=90, ble_scans_days=90)
    cleanup(db)

    health_after = db.query(HealthSample).filter(HealthSample.pi_rid == pi_with_samples.rid).count()
    wifi_after = db.query(WifiScan).filter(WifiScan.pi_rid == pi_with_samples.rid).count()

    # health_samples not deleted (days=0), wifi_scans are
    assert health_before == health_after  # No deletion for health_samples
    assert wifi_before == 5 and wifi_after == 3  # 2 deleted
