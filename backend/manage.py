"""Server-side admin commands (run on the controller, as the service user).

    cd /opt/pi-controller
    sudo -u pi_controller --preserve-env=DB_PASSWORD .venv/bin/python -m backend.manage <command>

Commands:
    create-user <username> --role viewer|operator|admin   password asked twice
    reset-password <username>                             password asked twice
    list-users
    ensure-tui-key      create the TUI break-glass key if missing (used by deploy.sh)
    rotate-tui-key      replace the TUI break-glass key
"""
import argparse
import getpass
import os
import sys

from backend import auth


def _prompt_new_password() -> str:
    """Ask twice; both entries must match (web service rule: set/change = 2×)."""
    while True:
        first = getpass.getpass("New password: ")
        second = getpass.getpass("New password again: ")
        try:
            auth.check_new_password(first, second)
            return first
        except ValueError as e:
            print(f"  {e} — try again.", file=sys.stderr)


def _cli_actor() -> auth.Actor:
    unix_user = os.environ.get("SUDO_USER") or getpass.getuser()
    return auth.Actor(username=f"cli ({unix_user})", role="admin")


def create_user(username: str, role: str) -> int:
    from backend.database import SessionLocal
    from backend.models import User

    username = username.strip().lower()
    try:
        auth.check_username(username)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            print(f"User {username} already exists — use reset-password.", file=sys.stderr)
            return 1
        password = _prompt_new_password()
        user = User(username=username, role=role, password_hash=auth.hash_password(password))
        db.add(user)
        db.commit()
        auth.record_event(db, _cli_actor(), "user_created", target=username, details={"role": role, "via": "cli"})
        print(f"Created {role} {username}.")
        return 0
    finally:
        db.close()


def reset_password(username: str) -> int:
    from backend.database import SessionLocal
    from backend.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username.strip().lower()).first()
        if user is None:
            print(f"No user {username}.", file=sys.stderr)
            return 1
        user.password_hash = auth.hash_password(_prompt_new_password())
        user.must_change_password = False
        if not user.is_active:
            print("Note: account is disabled — enable it in the web page (Users).")
        db.commit()
        revoked = auth.revoke_user_sessions(db, user.id)
        auth.record_event(db, _cli_actor(), "user_password_reset", target=user.username,
                          details={"sessions_revoked": revoked, "via": "cli"})
        print(f"Password for {user.username} reset; {revoked} session(s) ended.")
        return 0
    finally:
        db.close()


def list_users() -> int:
    from backend.database import SessionLocal
    from backend.models import User

    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.username).all()
        if not users:
            print("No users yet — create the first admin with: create-user <name> --role admin")
        for u in users:
            state = "active" if u.is_active else "disabled"
            last = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "never"
            print(f"{u.username:32} {u.role:9} {state:9} last login: {last}")
        return 0
    finally:
        db.close()


def ensure_tui_key() -> int:
    if auth.read_tui_key():
        print(f"TUI key present: {os.path.abspath(auth.TUI_KEY_FILE)}")
        return 0
    auth.write_tui_key()
    print(f"Created TUI key: {os.path.abspath(auth.TUI_KEY_FILE)}")
    return 0


def rotate_tui_key() -> int:
    auth.write_tui_key()
    print(f"Rotated TUI key: {os.path.abspath(auth.TUI_KEY_FILE)}")
    try:
        from backend.database import SessionLocal
        db = SessionLocal()
        try:
            auth.record_event(db, _cli_actor(), "tui_key_rotated")
        finally:
            db.close()
    except Exception as e:  # key rotation must work even if the DB is down
        print(f"(not logged — database unavailable: {e})", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.manage", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-user")
    p.add_argument("username")
    p.add_argument("--role", required=True, choices=auth.ROLES)
    p = sub.add_parser("reset-password")
    p.add_argument("username")
    sub.add_parser("list-users")
    sub.add_parser("ensure-tui-key")
    sub.add_parser("rotate-tui-key")
    args = parser.parse_args(argv)

    if args.command == "create-user":
        return create_user(args.username, args.role)
    if args.command == "reset-password":
        return reset_password(args.username)
    if args.command == "list-users":
        return list_users()
    if args.command == "ensure-tui-key":
        return ensure_tui_key()
    return rotate_tui_key()


if __name__ == "__main__":
    sys.exit(main())
