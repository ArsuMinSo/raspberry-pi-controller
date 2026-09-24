from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth import (
    Actor, check_new_password, check_username, hash_password, record_event, require_role, revoke_user_sessions,
)
from backend.database import get_db
from backend.models import User
from backend.schemas import PasswordReset, UserCreate, UserOut, UserUpdate

router = APIRouter()

# Users are never deleted (their history in the audit log refers to them) — disable instead.


@router.get("", response_model=list[UserOut])
def list_users(_: Actor = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.username).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, actor: Actor = Depends(require_role("admin")), db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    try:
        check_username(username)
        check_new_password(body.password, body.password_confirm)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail=f"User {username} already exists")
    user = User(username=username, role=body.role, password_hash=hash_password(body.password),
                must_change_password=body.must_change_password)
    db.add(user)
    db.commit()
    db.refresh(user)
    record_event(db, actor, "user_created", target=username, details={"role": body.role})
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, actor: Actor = Depends(require_role("admin")),
                db: Session = Depends(get_db)):
    user = _get_or_404(db, user_id)
    losing_admin = user.role == "admin" and user.is_active and (
        (body.role is not None and body.role != "admin") or body.is_active is False
    )
    if losing_admin and _active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Can't demote or disable the last active admin")

    if body.role is not None and body.role != user.role:
        record_event(db, actor, "user_role_changed", target=user.username,
                     details={"from": user.role, "to": body.role})
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        if not body.is_active:
            revoke_user_sessions(db, user.id)
        record_event(db, actor, "user_enabled" if body.is_active else "user_disabled", target=user.username)
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/password", status_code=204)
def reset_password(user_id: int, body: PasswordReset, actor: Actor = Depends(require_role("admin")),
                   db: Session = Depends(get_db)):
    user = _get_or_404(db, user_id)
    try:
        check_new_password(body.password, body.password_confirm)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    user.password_hash = hash_password(body.password)
    user.must_change_password = body.must_change_password
    db.commit()
    revoked = revoke_user_sessions(db, user.id)
    record_event(db, actor, "user_password_reset", target=user.username, details={"sessions_revoked": revoked})


@router.post("/{user_id}/revoke-sessions", status_code=204)
def revoke_sessions(user_id: int, actor: Actor = Depends(require_role("admin")), db: Session = Depends(get_db)):
    user = _get_or_404(db, user_id)
    revoked = revoke_user_sessions(db, user.id)
    record_event(db, actor, "session_revoked", target=user.username, details={"sessions_revoked": revoked})


def _get_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


def _active_admin_count(db: Session) -> int:
    return db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()
