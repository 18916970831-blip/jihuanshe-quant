import os
import threading
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATA_DIR, DB_PATH

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
swap_lock = threading.RLock()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def replace_database(src: Path) -> None:
    """Swap in a verified SQLite file between requests."""
    with swap_lock:
        engine.dispose()
        for suffix in ("-wal", "-shm"):
            extra = Path(str(DB_PATH) + suffix)
            if extra.exists():
                extra.unlink()
        os.replace(src, DB_PATH)


def init_db():
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
