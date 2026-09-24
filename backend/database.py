from collections.abc import Generator

from sqlalchemy import URL, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings


def _build_url(cfg) -> URL:
    db = cfg.database
    # URL.create escapes the password — '@', ':', '/', '#', '%' are safe
    return URL.create(
        "postgresql",
        username=db.user,
        password=db.password,
        host=db.host,
        port=db.port,
        database=db.db_name,
    )


def _make_engine():
    cfg = get_settings()
    return create_engine(
        _build_url(cfg),
        pool_size=cfg.database.pool_size,
        max_overflow=0,
        pool_pre_ping=True,
    )


engine = _make_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
