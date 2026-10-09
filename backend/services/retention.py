"""Data retention — periodic cleanup of time-series tables.

Deletes records older than the configured retention window to keep the database lean.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.config import effective_retention_settings
from backend.models import HealthSample, WifiScan, BleScan

log = logging.getLogger(__name__)


def cleanup(db: Session) -> dict:
    """Delete old records from time-series tables based on retention config.

    Returns dict with counts of deleted rows per table.
    """
    ret = effective_retention_settings()
    if not ret.enabled:
        log.debug("Retention cleanup disabled")
        return {}

    now = datetime.now(timezone.utc)
    deleted = {}

    # health_samples
    if ret.health_samples_days > 0:
        cutoff = now - timedelta(days=ret.health_samples_days)
        stmt = delete(HealthSample).where(HealthSample.timestamp < cutoff)
        result = db.execute(stmt)
        deleted["health_samples"] = result.rowcount
        if result.rowcount > 0:
            log.info("Deleted %d old health_samples (before %s)", result.rowcount, cutoff)

    # wifi_scans
    if ret.wifi_scans_days > 0:
        cutoff = now - timedelta(days=ret.wifi_scans_days)
        stmt = delete(WifiScan).where(WifiScan.timestamp < cutoff)
        result = db.execute(stmt)
        deleted["wifi_scans"] = result.rowcount
        if result.rowcount > 0:
            log.info("Deleted %d old wifi_scans (before %s)", result.rowcount, cutoff)

    # ble_scans
    if ret.ble_scans_days > 0:
        cutoff = now - timedelta(days=ret.ble_scans_days)
        stmt = delete(BleScan).where(BleScan.timestamp < cutoff)
        result = db.execute(stmt)
        deleted["ble_scans"] = result.rowcount
        if result.rowcount > 0:
            log.info("Deleted %d old ble_scans (before %s)", result.rowcount, cutoff)

    db.commit()
    log.info("Retention cleanup complete: %s", deleted)
    return deleted
