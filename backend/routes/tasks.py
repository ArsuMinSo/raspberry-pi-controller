from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ScheduledTask
from backend.schemas import ScheduledTaskCreate, ScheduledTaskOut, ScheduledTaskUpdate
from backend.services import scheduler

router = APIRouter()


@router.get("", response_model=list[ScheduledTaskOut])
def list_tasks(db: Session = Depends(get_db)):
    return db.query(ScheduledTask).order_by(ScheduledTask.id).all()


@router.post("", response_model=ScheduledTaskOut, status_code=201)
def create_task(body: ScheduledTaskCreate, db: Session = Depends(get_db)):
    _validate_cron(body.cron)
    task = ScheduledTask(**body.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    scheduler.add_or_replace(task)
    return task


@router.patch("/{task_id}", response_model=ScheduledTaskOut)
def update_task(task_id: int, body: ScheduledTaskUpdate, db: Session = Depends(get_db)):
    task = _get_or_404(task_id, db)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(task, field, value)
    if body.cron is not None:
        _validate_cron(body.cron)
    db.commit()
    db.refresh(task)
    scheduler.add_or_replace(task)
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = _get_or_404(task_id, db)
    scheduler.remove(task_id)
    db.delete(task)
    db.commit()


def _get_or_404(task_id: int, db: Session) -> ScheduledTask:
    task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


def _validate_cron(cron: str) -> None:
    from apscheduler.triggers.cron import CronTrigger
    try:
        CronTrigger.from_crontab(cron)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid cron expression: {e}")
