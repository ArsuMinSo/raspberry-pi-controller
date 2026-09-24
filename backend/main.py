import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy.orm import Session

from backend.database import check_db, get_db, SessionLocal
from backend.routes import (
    actions, auth, command, discovery, health, logs, pi, process, service, settings, tasks, users,
)
from backend.services import audit_log as al
from backend.services import scheduler as sched

_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.monotonic()
    # Tests set this: startup DB work would connect to the real DB from config.yaml
    run_scheduler = os.environ.get("PI_CONTROLLER_DISABLE_SCHEDULER") != "1"
    if run_scheduler:
        db = SessionLocal()
        try:
            interrupted = al.mark_interrupted(db)  # jobs cut off by the last restart
            if interrupted:
                logging.getLogger(__name__).warning("Marked %d unfinished action(s) as interrupted", interrupted)
            sched.start(db)
        finally:
            db.close()
    yield
    if run_scheduler:
        sched.stop()


app = FastAPI(
    title="Pi Controller API",
    version="1.0.0",
    lifespan=lifespan,
    # Everything lives under /api/v1 (nginx serves the web page at /)
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    redoc_url=None,
)

API = "/api/v1"

app.include_router(auth.router,      prefix=f"{API}/auth",      tags=["auth"])
app.include_router(users.router,     prefix=f"{API}/users",     tags=["users"])
app.include_router(pi.router,        prefix=f"{API}/pi",        tags=["inventory"])
app.include_router(actions.router,   prefix=f"{API}/actions",   tags=["actions"])
app.include_router(health.router,    prefix=f"{API}/health",    tags=["health"])
app.include_router(command.router,   prefix=f"{API}/command",   tags=["command"])
app.include_router(process.router,   prefix=f"{API}/process",   tags=["process"])
app.include_router(service.router,   prefix=f"{API}/service",   tags=["service"])
app.include_router(logs.router,      prefix=f"{API}/logs",      tags=["logs"])
app.include_router(discovery.router, prefix=f"{API}/discovery", tags=["discovery"])
app.include_router(settings.router,  prefix=f"{API}/settings",  tags=["settings"])
app.include_router(tasks.router,     prefix=f"{API}/tasks",     tags=["tasks"])

system = APIRouter(prefix=API, tags=["system"])


@system.get("/health")
def system_health():
    """Liveness check — no login required."""
    return {
        "status": "ok",
        "db": "ok" if check_db() else "error",
        "uptime_s": int(time.monotonic() - _start_time),
    }


app.include_router(system)
