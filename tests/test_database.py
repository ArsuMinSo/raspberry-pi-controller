import pytest
from sqlalchemy.exc import IntegrityError

from backend.models import ActionLog, Pi


def test_pi_insert_and_query(db):
    pi = Pi(mac="11:22:33:44:55:66", position="02-001", status="reachable", tags=[])
    db.add(pi)
    db.commit()
    found = db.query(Pi).filter(Pi.position == "02-001").first()
    assert found is not None
    assert found.mac == "11:22:33:44:55:66"
    db.delete(found)
    db.commit()


def test_pi_position_unique(db):
    pi1 = Pi(mac="aa:bb:cc:dd:ee:01", position="03-001", status="unreachable", tags=[])
    pi2 = Pi(mac="aa:bb:cc:dd:ee:02", position="03-001", status="unreachable", tags=[])
    db.add(pi1)
    db.commit()
    db.add(pi2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.delete(db.query(Pi).filter(Pi.position == "03-001").first())
    db.commit()


def test_pi_mac_allows_duplicates(db):
    pi1 = Pi(mac="ff:ff:ff:ff:ff:ff", position="04-001", status="unreachable", tags=[])
    pi2 = Pi(mac="ff:ff:ff:ff:ff:ff", position="04-002", status="unreachable", tags=[])
    db.add_all([pi1, pi2])
    db.commit()
    count = db.query(Pi).filter(Pi.mac == "ff:ff:ff:ff:ff:ff").count()
    assert count == 2
    db.query(Pi).filter(Pi.position.in_(["04-001", "04-002"])).delete(synchronize_session=False)
    db.commit()


def test_pi_tags_filter(db):
    pi = Pi(mac="cc:dd:ee:ff:00:11", position="05-001", status="reachable", tags=["kiosk", "floor2"])
    db.add(pi)
    db.commit()
    found = db.query(Pi).filter(Pi.tags.contains(["kiosk"])).all()
    positions = [p.position for p in found]
    assert "05-001" in positions
    db.delete(pi)
    db.commit()


def test_actions_log_status_constraint(db):
    entry = ActionLog(
        pis_selected=["01-001"],
        action="execute",
        status="invalid_status",
    )
    db.add(entry)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_actions_log_append_only(db):
    entry = ActionLog(pis_selected=["01-001"], action="health", status="success")
    db.add(entry)
    db.commit()
    entry_id = entry.id
    db.execute(__import__("sqlalchemy").text(f"DELETE FROM actions_log WHERE id = {entry_id}"))
    db.commit()
    still_there = db.get(ActionLog, entry_id)
    assert still_there is not None
    db.expunge(still_there)
