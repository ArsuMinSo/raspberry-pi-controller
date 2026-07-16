import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from backend.database import SessionLocal
from backend.models import ScheduledTask

log = logging.getLogger(__name__)
_scheduler = BackgroundScheduler(timezone="UTC")


def start(db: Session) -> None:
    tasks = db.query(ScheduledTask).filter(ScheduledTask.enabled == True).all()
    for task in tasks:
        _add_job(task)
    _scheduler.start()
    log.info("Scheduler started with %d task(s)", len(tasks))


def stop() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


def add_or_replace(task: ScheduledTask) -> None:
    job_id = _job_id(task.id)
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    if task.enabled:
        _add_job(task)


def remove(task_id: int) -> None:
    job_id = _job_id(task_id)
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)


def _job_id(task_id: int) -> str:
    return f"task_{task_id}"


def _add_job(task: ScheduledTask) -> None:
    try:
        trigger = CronTrigger.from_crontab(task.cron, timezone="UTC")
    except Exception as e:
        log.warning("Invalid cron '%s' for task %s: %s", task.cron, task.id, e)
        return
    _scheduler.add_job(
        _run_task,
        trigger=trigger,
        id=_job_id(task.id),
        args=[task.id],
        replace_existing=True,
        misfire_grace_time=60,
    )
    log.info("Scheduled task %s (%s) with cron '%s'", task.id, task.name, task.cron)


def _run_task(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        if not task or not task.enabled:
            return

        action_id = None
        status = "success"
        try:
            if task.task_type == "command":
                action_id = _exec_command(task, db)
            elif task.task_type == "health":
                action_id = _exec_health(task, db)
            elif task.task_type == "discovery":
                action_id = _exec_discovery(db)
        except Exception as e:
            log.error("Scheduled task %s (%s) failed: %s", task_id, task.name, e)
            status = "fail"

        task.last_run = func.now()
        task.last_status = status
        if action_id is not None:
            task.last_action_id = action_id
        db.commit()
        log.info("Scheduled task %s (%s) completed: %s", task_id, task.name, status)
    finally:
        db.close()


def _exec_command(task: ScheduledTask, db: Session) -> int | None:
    from backend.config import effective_ssh_settings
    from backend.models import Pi
    from backend.routes.command import _run_command
    pis = (
        db.query(Pi).filter(Pi.position.in_(task.pis)).all()
        if task.pis
        else db.query(Pi).filter(Pi.status == "reachable").all()
    )
    if not pis or not task.command:
        return None
    return _run_command(pis, task.command, db)


def _exec_health(task: ScheduledTask, db: Session) -> int | None:
    from backend.config import effective_ssh_settings
    from backend.models import Pi
    from backend.services.health_check import run_health_check
    pis = (
        db.query(Pi).filter(Pi.position.in_(task.pis)).all()
        if task.pis
        else db.query(Pi).filter(Pi.status == "reachable").all()
    )
    if not pis:
        return None
    return run_health_check(pis, db, effective_ssh_settings())


def _exec_discovery(db: Session) -> int | None:
    from backend.config import effective_network_settings, effective_ssh_settings
    from backend.services.discovery import scan_subnet
    net = effective_network_settings()
    result = scan_subnet(net.subnet, db, effective_ssh_settings(), net)
    return result.action_id if result else None
