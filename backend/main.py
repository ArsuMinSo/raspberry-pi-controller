import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from backend.database import check_db, get_db
from backend.routes import command, discovery, health, logs, pi, process, service

_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.monotonic()
    yield


app = FastAPI(
    title="Pi Controller API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(pi.router,        prefix="/pi",        tags=["inventory"])
app.include_router(health.router,    prefix="/health",    tags=["health"])
app.include_router(command.router,   prefix="/command",   tags=["command"])
app.include_router(process.router,   prefix="/process",   tags=["process"])
app.include_router(service.router,   prefix="/service",   tags=["service"])
app.include_router(logs.router,      prefix="/logs",      tags=["logs"])
app.include_router(discovery.router, prefix="/discovery", tags=["discovery"])


@app.get("/health", tags=["system"])
def system_health(db: Session = Depends(get_db)):
    return {
        "status": "ok",
        "db": "ok" if check_db() else "error",
        "uptime_s": int(time.monotonic() - _start_time),
    }
