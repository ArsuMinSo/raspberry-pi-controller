from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import (
    DUMMY_HASH, Actor, check_new_password, client_ip, create_session, current_actor, hash_password,
    is_locked_out, record_event, revoke_user_sessions, utcnow, verify_password,
)
from backend.database import get_db
from backend.models import User, UserSession
from backend.schemas import LoginRequest, LoginResponse, MeOut, PasswordChange, SessionOut, UserOut

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    ip = client_ip(request)
    ua = request.headers.get("user-agent")

    if is_locked_out(db, username, ip):
        record_event(db, None, "login_blocked", target=username, username=username, ip=ip, user_agent=ua)
        raise HTTPException(status_code=429, detail="Too many failed logins — try again in 15 minutes")

    user = db.query(User).filter(User.username == username).first()
    # Always run one argon2 verify so response time doesn't reveal whether the user exists
    ok = verify_password(user.password_hash if user else DUMMY_HASH, body.password) and user is not None
    if not ok or not user.is_active:
        reason = "disabled" if ok else "bad_credentials"
        record_event(db, None, "login_failed", target=username, details={"reason": reason},
                     username=username, ip=ip, user_agent=ua)
        raise HTTPException(status_code=401, detail="Wrong username or password")

    token, session = create_session(db, user, ip, ua)
    actor = Actor(username=user.username, role=user.role, user_id=user.id, session_id=session.id, ip=ip, user_agent=ua)
    record_event(db, actor, "login", target=user.username)
    return LoginResponse(token=token, expires_at=session.expires_at, user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.session_id is None:
        return  # TUI key — nothing to end
    session = db.get(UserSession, actor.session_id)
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
        db.commit()
    record_event(db, actor, "logout", target=actor.username)


@router.get("/me", response_model=MeOut)
def me(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    user = db.get(User, actor.user_id) if actor.user_id else None
    return MeOut(username=actor.username, role=actor.role, user=UserOut.model_validate(user) if user else None)


@router.post("/me/password", status_code=204)
def change_own_password(body: PasswordChange, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.user_id is None:
        raise HTTPException(status_code=400, detail="The TUI key has no password")
    user = db.get(User, actor.user_id)
    if not verify_password(user.password_hash, body.current_password):
        record_event(db, actor, "password_change_failed", target=user.username, details={"reason": "wrong_current"})
        raise HTTPException(status_code=403, detail="Current password is wrong")
    try:
        check_new_password(body.new_password, body.new_password_confirm)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    # Other devices must log in again; this session stays
    revoked = revoke_user_sessions(db, user.id, except_session_id=actor.session_id)
    record_event(db, actor, "password_changed", target=user.username, details={"other_sessions_revoked": revoked})


@router.get("/me/sessions", response_model=list[SessionOut])
def my_sessions(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.user_id is None:
        return []
    rows = (
        db.query(UserSession)
        .filter(UserSession.user_id == actor.user_id, UserSession.revoked_at.is_(None),
                UserSession.expires_at > utcnow())
        .order_by(UserSession.created_at.desc())
        .all()
    )
    out = []
    for s in rows:
        item = SessionOut.model_validate(s)
        item.current = s.id == actor.session_id
        out.append(item)
    return out


@router.delete("/me/sessions/{session_id}", status_code=204)
def revoke_my_session(session_id: int, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != actor.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        db.commit()
        record_event(db, actor, "session_revoked", target=actor.username, details={"session_id": session_id})
