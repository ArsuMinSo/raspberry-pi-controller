"""Authentication, roles and the audit trail.

Clients authenticate with ``Authorization: Bearer <token>`` (web page) or, only on
direct connections from 127.0.0.1, with the TUI break-glass key header.
See docs/design/web-service.md.
"""
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AuditEvent, User, UserSession

SESSION_LIFETIME = timedelta(hours=12)
LOCKOUT_FAILURES = 5
LOCKOUT_WINDOW = timedelta(minutes=15)
MIN_PASSWORD_LENGTH = 12

ROLES = ("viewer", "operator", "admin")
_ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}

TUI_KEY_HEADER = "X-PiC-Local-Key"
TUI_USER_HEADER = "X-PiC-Local-User"
TUI_KEY_FILE = os.environ.get("PI_CONTROLLER_TUI_KEY_FILE", ".tui-key")

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")

_hasher = PasswordHasher()  # argon2id
# Verified against when the username doesn't exist, so timing doesn't reveal valid names
DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


# ─── Passwords ────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def check_new_password(password: str, confirm: str) -> None:
    """Raise ValueError unless the password is acceptable and both entries match."""
    if password != confirm:
        raise ValueError("Passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def check_username(username: str) -> None:
    if not USERNAME_RE.match(username):
        raise ValueError("Username: 2–32 characters, lowercase letters, digits, '.', '_' or '-'")
    if username.startswith("local-tui"):
        raise ValueError("Username 'local-tui…' is reserved")


# ─── Sessions ─────────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, ip: str | None, user_agent: str | None) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    session = UserSession(
        user_id=user.id,
        token_hash=_token_hash(token),
        created_at=now,
        last_used_at=now,
        expires_at=now + SESSION_LIFETIME,
        ip=ip,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(session)
    user.last_login_at = now
    db.commit()
    db.refresh(session)
    return token, session


def revoke_user_sessions(db: Session, user_id: int, except_session_id: int | None = None) -> int:
    q = db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_session_id is not None:
        q = q.filter(UserSession.id != except_session_id)
    count = q.update({"revoked_at": utcnow()}, synchronize_session=False)
    db.commit()
    return count


def is_locked_out(db: Session, username: str, ip: str | None) -> bool:
    since = utcnow() - LOCKOUT_WINDOW
    failures = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.event == "login_failed",
            AuditEvent.target == username,
            AuditEvent.ip == ip,
            AuditEvent.ts >= since,
        )
        .count()
    )
    return failures >= LOCKOUT_FAILURES


# ─── Actor (who is calling) ───────────────────────────────────────────────────

@dataclass
class Actor:
    username: str
    role: str
    user_id: int | None = None      # None for the TUI break-glass key
    session_id: int | None = None
    ip: str | None = None
    user_agent: str | None = None

    def has_role(self, role: str) -> bool:
        return _ROLE_RANK[self.role] >= _ROLE_RANK[role]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def is_direct_local(request: Request) -> bool:
    """True only for connections made straight to uvicorn from this machine.

    nginx always sets X-Forwarded-For (and strips the key header), so proxied
    requests never qualify even though they also come from 127.0.0.1.
    """
    return client_ip(request) in ("127.0.0.1", "::1") and "x-forwarded-for" not in request.headers


def read_tui_key() -> str | None:
    try:
        with open(TUI_KEY_FILE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def write_tui_key(path: str = TUI_KEY_FILE) -> None:
    key = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    os.chmod(path, 0o600)


def _tui_actor(request: Request) -> Actor | None:
    presented = request.headers.get(TUI_KEY_HEADER)
    if not presented or not is_direct_local(request):
        return None
    key = read_tui_key()
    if not key or not hmac.compare_digest(presented, key):
        return None
    unix_user = re.sub(r"[^A-Za-z0-9._-]", "", request.headers.get(TUI_USER_HEADER, ""))[:32] or "unknown"
    return Actor(username=f"local-tui ({unix_user})", role="admin", ip=client_ip(request))


# Declares the Bearer scheme in OpenAPI, so /api/v1/docs shows "Authorize" and sends the token.
# auto_error=False: we raise our own 401 (and the TUI key path needs no token).
bearer_scheme = HTTPBearer(auto_error=False, description="Token from POST /api/v1/auth/login")


def current_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Actor:
    tui = _tui_actor(request)
    if tui:
        return tui

    token = credentials.credentials if credentials else ""
    if not token:
        raise HTTPException(status_code=401, detail="Login required", headers={"WWW-Authenticate": "Bearer"})

    now = utcnow()
    session = db.query(UserSession).filter(UserSession.token_hash == _token_hash(token.strip())).first()
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise HTTPException(status_code=401, detail="Session expired — log in again",
                            headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account disabled", headers={"WWW-Authenticate": "Bearer"})

    if (now - session.last_used_at) > timedelta(minutes=1):  # don't write on every request
        session.last_used_at = now
        db.commit()

    return Actor(
        username=user.username, role=user.role, user_id=user.id, session_id=session.id,
        ip=client_ip(request), user_agent=request.headers.get("user-agent"),
    )


def require_role(role: str):
    """Dependency factory: `actor: Actor = Depends(require_role("operator"))`."""
    if role not in _ROLE_RANK:
        raise ValueError(f"unknown role {role}")

    def dependency(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)) -> Actor:
        if not actor.has_role(role):
            record_event(db, actor, "permission_denied", target=f"{request.method} {request.url.path}",
                         details={"required": role, "role": actor.role})
            raise HTTPException(status_code=403, detail=f"Requires role '{role}'")
        return actor

    return dependency


# ─── Audit events ─────────────────────────────────────────────────────────────

def record_event(
    db: Session,
    actor: Actor | None,
    event: str,
    target: str | None = None,
    details: dict | None = None,
    *,
    username: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Append to audit_events and commit. `username`/`ip` override the actor's (e.g. failed logins)."""
    db.add(AuditEvent(
        user_id=actor.user_id if actor else None,
        username=username or (actor.username if actor else "system"),
        event=event,
        target=target,
        details=details,
        ip=ip or (actor.ip if actor else None),
        user_agent=((user_agent or (actor.user_agent if actor else None)) or "")[:255] or None,
    ))
    db.commit()
